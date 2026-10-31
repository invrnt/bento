"""One activity summary for the status bar, the Actividad panel, and the tray."""

from __future__ import annotations

import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from bento.domain.activity import (
    Activity,
    ActivitySummary,
    AttentionAction,
    AttentionItem,
    AttentionKind,
    TransferStats,
)
from bento.domain.backup import BackupPolicy
from bento.domain.sync import SyncState, SyncStatus
from bento.domain.vault import DEVICE_REMOVED_REASON, VaultState, VaultStatus
from bento.ports.backup import BackupPolicyRepositoryPort
from bento.ports.repositories import ClockPort

LOGGER = logging.getLogger("bento.activity")
FLOOD_WAIT_ATTENTION_SECONDS = 60
MAX_ATTENTION_PER_KIND = 20
THROUGHPUT_WINDOW_SECONDS = 600
MIN_THROUGHPUT_WINDOW_SECONDS = 30


@dataclass(frozen=True, slots=True)
class FailedUpload:
    job_id: str
    asset_id: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class FailedBackupSource:
    job_id: str
    source_id: str
    label: str
    failed_files: int


@dataclass(frozen=True, slots=True)
class FailedInboxItem:
    message_id: int
    error_code: str | None


@dataclass(frozen=True, slots=True)
class NewDevice:
    """A device this one first learned about through sync, not yet acknowledged by the person."""

    device_id: str
    name: str
    first_seen_at: datetime | None
    introduced_by: str | None


@dataclass(frozen=True, slots=True)
class ActivitySnapshot:
    """Raw counters read from the local database."""

    uploads_running: int = 0
    uploads_queued: int = 0
    derived_pending: int = 0
    upload_bytes_total: int = 0
    upload_bytes_done: int = 0
    backup_pending_files: int = 0
    backup_pending_bytes: int = 0
    recent_uploaded_bytes: int = 0
    recent_window_seconds: float = 0
    flood_wait_until: datetime | None = None
    """Latest `run_after` of uploads rescheduled for a Telegram flood wait."""
    telegram_flood_wait_until: datetime | None = None
    """`sync_state["telegram.flood_wait_until"]`: any long wait the Telegram client of this device reported."""
    failed_uploads: tuple[FailedUpload, ...] = ()
    failed_backups: tuple[FailedBackupSource, ...] = ()
    failed_inbox: tuple[FailedInboxItem, ...] = ()
    new_devices: tuple[NewDevice, ...] = ()


class ActivitySourcePort(Protocol):
    async def snapshot(self, *, now: datetime) -> ActivitySnapshot: ...


class DownloadStatsPort(Protocol):
    def snapshot(self) -> TransferStats: ...


@dataclass(frozen=True, slots=True)
class ActivityInputs:
    snapshot: ActivitySnapshot
    policy: BackupPolicy
    downloads: TransferStats = TransferStats()
    sync: SyncStatus | None = None
    vault: VaultStatus | None = None
    now: datetime | None = None


class ActivityService:
    def __init__(
        self,
        *,
        source: ActivitySourcePort,
        policy: BackupPolicyRepositoryPort,
        clock: ClockPort,
        downloads: DownloadStatsPort | None = None,
        sync_status: Callable[[], Awaitable[SyncStatus | None]] | None = None,
        vault_status: Callable[[], Awaitable[VaultStatus | None]] | None = None,
    ) -> None:
        self._source = source
        self._policy = policy
        self._clock = clock
        self._downloads = downloads
        self._sync_status = sync_status
        self._vault_status = vault_status

    async def current(self) -> Activity:
        now = self._clock.now()
        return build_activity(
            ActivityInputs(
                snapshot=await self._source.snapshot(now=now),
                policy=await self._policy.get(),
                downloads=self._downloads.snapshot() if self._downloads is not None else TransferStats(),
                sync=await _optional(self._sync_status),
                vault=await _optional(self._vault_status),
                now=now,
            )
        )


def build_activity(inputs: ActivityInputs) -> Activity:
    snapshot = inputs.snapshot
    paused = inputs.policy.effective_paused
    uploads = _upload_stats(snapshot)
    attention = _attention(inputs)
    flood_wait = any(item.kind == AttentionKind.FLOOD_WAIT for item in attention)
    sync_state = inputs.sync.state if inputs.sync is not None else SyncState.DISABLED
    remote_work = snapshot.uploads_running + snapshot.uploads_queued + snapshot.derived_pending
    backup_work = 0 if paused else snapshot.backup_pending_files

    if sync_state == SyncState.OFFLINE:
        summary = ActivitySummary.OFFLINE
    elif flood_wait:
        summary = ActivitySummary.ATTENTION
    elif remote_work or backup_work:
        summary = ActivitySummary.UPLOADING
    elif inputs.downloads.active:
        summary = ActivitySummary.DOWNLOADING
    elif sync_state in {SyncState.SYNCING, SyncState.BOOTSTRAPPING}:
        summary = ActivitySummary.SYNCING
    elif paused:
        summary = ActivitySummary.PAUSED
    elif attention:
        summary = ActivitySummary.ATTENTION
    else:
        summary = ActivitySummary.UP_TO_DATE
    return Activity(summary=summary, uploads=uploads, downloads=inputs.downloads, attention=tuple(attention))


def _upload_stats(snapshot: ActivitySnapshot) -> TransferStats:
    bytes_total = snapshot.upload_bytes_total + snapshot.backup_pending_bytes
    bytes_done = min(snapshot.upload_bytes_done, bytes_total)
    remaining = bytes_total - bytes_done
    eta = None
    if remaining > 0 and snapshot.recent_uploaded_bytes > 0:
        window = max(snapshot.recent_window_seconds, MIN_THROUGHPUT_WINDOW_SECONDS)
        rate = snapshot.recent_uploaded_bytes / window
        eta = math.ceil(remaining / rate) if rate > 0 else None
    return TransferStats(
        active=snapshot.uploads_running,
        queued=snapshot.uploads_queued + snapshot.backup_pending_files,
        bytes_total=bytes_total,
        bytes_done=bytes_done,
        eta_seconds=eta,
    )


def _attention(inputs: ActivityInputs) -> list[AttentionItem]:
    snapshot = inputs.snapshot
    items: list[AttentionItem] = []
    wait_seconds = _flood_wait_seconds(inputs)
    if wait_seconds is not None and wait_seconds > FLOOD_WAIT_ATTENTION_SECONDS:
        items.append(
            _item(
                "flood_wait",
                AttentionKind.FLOOD_WAIT,
                AttentionAction.NONE,
                retry_after_seconds=wait_seconds,
                retry_after_minutes=math.ceil(wait_seconds / 60),
            )
        )
    sync = inputs.sync
    if sync is not None and sync.state == SyncState.ERROR:
        items.append(_item("sync_error", AttentionKind.SYNC_ERROR, AttentionAction.RETRY, code=sync.error_code))
    if sync is not None and sync.clock_skew_ms is not None:
        # Retrying cannot help: the person fixes the device clock (automatic date and time).
        skew_seconds = abs(sync.clock_skew_ms) // 1000
        items.append(
            _item(
                "clock_skew",
                AttentionKind.CLOCK_SKEW,
                AttentionAction.NONE,
                direction="ahead" if sync.clock_skew_ms > 0 else "behind",
                skew_seconds=skew_seconds,
                skew_minutes=math.ceil(skew_seconds / 60),
            )
        )
    for failed in snapshot.failed_uploads[:MAX_ATTENTION_PER_KIND]:
        items.append(
            _item(
                f"upload_failed:{failed.job_id}",
                AttentionKind.UPLOAD_FAILED,
                AttentionAction.RETRY,
                job_id=failed.job_id,
                asset_id=failed.asset_id,
            )
        )
    for failed_source in snapshot.failed_backups[:MAX_ATTENTION_PER_KIND]:
        items.append(
            _item(
                f"backup_failed:{failed_source.source_id}",
                AttentionKind.UPLOAD_FAILED,
                AttentionAction.RETRY,
                job_id=failed_source.job_id,
                source_id=failed_source.source_id,
                label=failed_source.label,
                count=failed_source.failed_files,
            )
        )
    vault = inputs.vault
    if vault is not None and vault.state == VaultState.READY and not vault.recovery_kit_saved:
        # `stale`: the kit wraps an older key epoch ("genera un nuevo kit").
        reason = "stale" if vault.recovery_kit_stale else None
        items.append(_item("recovery_kit", AttentionKind.RECOVERY_KIT, AttentionAction.SAVE_RECOVERY_KIT, reason=reason))
    if vault is not None and vault.reason == DEVICE_REMOVED_REASON:
        items.append(_item("device_removed", AttentionKind.DEVICE_REMOVED, AttentionAction.OPEN_SETTINGS))
    for device in snapshot.new_devices[:MAX_ATTENTION_PER_KIND]:
        # "Se añadió «name» a tu nube": a device can only appear here through another device's sync data.
        items.append(
            _item(
                f"new_device:{device.device_id}",
                AttentionKind.NEW_DEVICE,
                AttentionAction.OPEN_DEVICES,
                device_id=device.device_id,
                name=device.name,
                first_seen_at=device.first_seen_at.isoformat() if device.first_seen_at is not None else None,
            )
        )
    for inbox in snapshot.failed_inbox[:MAX_ATTENTION_PER_KIND]:
        items.append(
            _item(
                f"inbox_failed:{inbox.message_id}",
                AttentionKind.INBOX_FAILED,
                AttentionAction.NONE,
                message_id=inbox.message_id,
                code=inbox.error_code,
            )
        )
    return items


def _flood_wait_seconds(inputs: ActivityInputs) -> int | None:
    if inputs.now is None:
        return None
    # Every source of a wait collapses into one `flood_wait` item showing the longest remaining wait.
    candidates = [inputs.snapshot.flood_wait_until, inputs.snapshot.telegram_flood_wait_until]
    if inputs.sync is not None and inputs.sync.state == SyncState.WAITING:
        candidates.append(inputs.sync.waiting_until)
    remaining = [math.ceil((until - inputs.now).total_seconds()) for until in candidates if until is not None]
    remaining = [value for value in remaining if value > 0]
    return max(remaining) if remaining else None


def _item(item_id: str, kind: AttentionKind, action: AttentionAction, **params: object) -> AttentionItem:
    return AttentionItem(
        id=item_id,
        kind=kind,
        title_key=f"activity.attention.{kind.value}",
        action=action,
        params={key: value for key, value in params.items() if value is not None},
    )


async def _optional[T](provider: Callable[[], Awaitable[T | None]] | None) -> T | None:
    if provider is None:
        return None
    try:
        return await provider()
    except Exception as exc:  # status providers of other features must never break the activity panel
        LOGGER.debug("Activity status provider unavailable: %s", exc.__class__.__name__)
        return None
