"""The Telegram Inbox ("Bento · Bandeja"): anything forwarded there becomes a normal upload.

The worker's inbox loop calls `scan()` (queues one `inbox_import` job per new message), the job handler calls
`import_item()`, and `cleanup()` deletes imported messages after `inbox_keep_hours`.

Every device of the account runs the loop, so devices coordinate through the account's own reactions (shared by
all its sessions): an item that already carries a result reaction was handled elsewhere, 👀 marks an item being
imported, and devices other than the first one (by `added_at`) wait `FOLLOWER_DELAY` before stepping in.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from bento.application.ingestion import UploadedAssetFile
from bento.application.upload import UploadAssetResult
from bento.application.vault import VaultStatePort
from bento.domain.assets import AssetOrigin
from bento.domain.errors import (
    DomainError,
    StorageUnavailableError,
    TelegramAccountError,
    TelegramFloodWaitError,
    VaultLockedError,
)
from bento.domain.jobs import Job, JobPriority, JobType
from bento.domain.telegram import InboxItem
from bento.domain.vault import VaultLayout
from bento.ports.jobs import JobQueuePort
from bento.ports.pairing import DeviceRepositoryPort
from bento.ports.repositories import ClockPort
from bento.ports.telegram import VaultTransportPort
from bento.ports.vault import VaultSessionPort

LOGGER = logging.getLogger("bento.inbox")

SUCCESS_REACTIONS = ("✅", "👍")
FAILURE_REACTION = "⚠️"
CLAIM_REACTION = "👀"
RESULT_REACTIONS = frozenset((*SUCCESS_REACTIONS, FAILURE_REACTION))
FOLLOWER_DELAY = timedelta(minutes=2)
STALE_CLAIM = timedelta(minutes=30)
SCAN_LIMIT = 50
CURSOR_KEY_PREFIX = "inbox.cursor."


class InboxState(StrEnum):
    QUEUED = "queued"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class InboxRecord:
    message_id: int
    state: InboxState
    created_at: datetime
    updated_at: datetime
    asset_id: str | None = None
    error_code: str | None = None


class InboxItemStorePort(Protocol):
    async def get(self, message_id: int) -> InboxRecord | None: ...

    async def save(self, record: InboxRecord) -> None: ...

    async def in_state(
        self, state: InboxState, *, updated_before: datetime | None = None, limit: int = 100
    ) -> tuple[InboxRecord, ...]: ...


class IngestionPort(Protocol):
    async def upload_file(self, file: UploadedAssetFile) -> UploadAssetResult: ...


TransportResolver = Callable[[], VaultTransportPort | None]


class InboxService:
    def __init__(
        self,
        *,
        vault: VaultSessionPort,
        transport: TransportResolver,
        items: InboxItemStorePort,
        state: VaultStatePort,
        jobs: JobQueuePort,
        devices: DeviceRepositoryPort,
        ingestion: IngestionPort,
        clock: ClockPort,
        temp_dir: Path | str,
        keep_hours: int = 24,
    ) -> None:
        self._vault = vault
        self._transport = transport
        self._items = items
        self._state = state
        self._jobs = jobs
        self._devices = devices
        self._ingestion = ingestion
        self._clock = clock
        self._temp_dir = Path(temp_dir)
        self._keep = timedelta(hours=keep_hours)

    async def scan(self) -> int:
        """Queue an import for each new Inbox message this device should handle. Returns how many were queued."""
        context = await self._vault.current()
        transport = self._transport()
        if context is None or transport is None:
            return 0
        layout = context.layout
        cursor_key = CURSOR_KEY_PREFIX + layout.vault_id
        cursor = int(await self._state.get_value(cursor_key) or 0)
        delay = FOLLOWER_DELAY * await self._rank(context.device.device_id)
        now = self._clock.now()
        queued = 0
        advance = cursor
        deferred = False
        for item in await transport.list_inbox(layout, after_message_id=cursor, limit=SCAN_LIMIT):
            if await self._items.get(item.message_id) is None:
                if RESULT_REACTIONS.intersection(item.reactions) or self._claimed_elsewhere(item, now):
                    await self._record(item.message_id, InboxState.SKIPPED)
                elif now - item.date < delay:
                    deferred = True
                else:
                    await self._queue(transport, layout, item)
                    queued += 1
            if not deferred:
                advance = item.message_id
        if advance != cursor:
            await self._state.set_value(cursor_key, str(advance))
        return queued

    async def import_item(self, job: Job) -> str:
        """`inbox_import` job: download, ingest as a normal upload, react, record. Returns the asset id."""
        message_id = int(job.payload["message_id"])
        record = await self._items.get(message_id)
        if record is not None and record.state in {InboxState.DONE, InboxState.DELETED} and record.asset_id:
            return record.asset_id
        context = await self._vault.require()
        transport = self._require_transport()
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="inbox-", dir=self._temp_dir, delete=False) as handle:
            temp_path = Path(handle.name)
        try:
            await transport.download_inbox_item(context.layout, message_id, temp_path)
            result = await self._ingestion.upload_file(
                UploadedAssetFile(
                    source_path=temp_path,
                    original_filename=str(job.payload.get("filename") or f"telegram-{message_id}"),
                    declared_mime_type=_optional_str(job.payload.get("mime_type")),
                    origin=AssetOrigin.TELEGRAM_INBOX,
                )
            )
        except Exception as exc:
            if not _transient(exc) or job.attempts + 1 >= job.max_attempts:
                await self._fail(transport, context.layout, message_id, exc)
            raise
        finally:
            temp_path.unlink(missing_ok=True)
        await self._react(transport, context.layout, message_id, SUCCESS_REACTIONS)
        await self._record(message_id, InboxState.DONE, asset_id=result.asset.id)
        if self._keep <= timedelta(0):
            await self.cleanup()
        return result.asset.id

    async def cleanup(self) -> int:
        """Delete imported Inbox messages older than `inbox_keep_hours`. Returns how many were deleted."""
        context = await self._vault.current()
        transport = self._transport()
        if context is None or transport is None:
            return 0
        due = await self._items.in_state(InboxState.DONE, updated_before=self._clock.now() - self._keep)
        if not due:
            return 0
        await transport.delete_inbox_items(context.layout, tuple(record.message_id for record in due))
        for record in due:
            await self._record(record.message_id, InboxState.DELETED, asset_id=record.asset_id)
        return len(due)

    async def failures(self, *, limit: int = 20) -> tuple[InboxRecord, ...]:
        """Failed imports, for attention items."""
        return await self._items.in_state(InboxState.FAILED, limit=limit)

    async def _queue(self, transport: VaultTransportPort, layout: VaultLayout, item: InboxItem) -> None:
        await self._record(item.message_id, InboxState.QUEUED)
        await self._react(transport, layout, item.message_id, (CLAIM_REACTION,))
        await self._jobs.enqueue(
            type=JobType.INBOX_IMPORT,
            priority=int(JobPriority.BLOB_ASSET),
            payload={"message_id": item.message_id, "filename": item.filename, "mime_type": item.mime_type},
        )

    async def _fail(self, transport: VaultTransportPort, layout: VaultLayout, message_id: int, exc: Exception) -> None:
        code = exc.code if isinstance(exc, DomainError) else "inbox_import_failed"
        LOGGER.warning("Inbox item %s could not be imported: %s", message_id, code)
        await self._react(transport, layout, message_id, (FAILURE_REACTION,))
        await self._record(message_id, InboxState.FAILED, error_code=code)

    async def _react(
        self, transport: VaultTransportPort, layout: VaultLayout, message_id: int, emojis: tuple[str, ...]
    ) -> None:
        """Best effort: channels may restrict reactions, so try each emoji and then give up silently."""
        for emoji in emojis:
            try:
                await transport.react_inbox_item(layout, message_id, emoji)
                return
            except DomainError as exc:
                if isinstance(exc, TelegramFloodWaitError):
                    return
                continue

    async def _record(
        self, message_id: int, state: InboxState, *, asset_id: str | None = None, error_code: str | None = None
    ) -> None:
        now = self._clock.now()
        existing = await self._items.get(message_id)
        await self._items.save(
            InboxRecord(
                message_id=message_id,
                state=state,
                created_at=existing.created_at if existing is not None else now,
                updated_at=now,
                asset_id=asset_id,
                error_code=error_code,
            )
        )

    async def _rank(self, device_id: str) -> int:
        active = sorted(await self._devices.list(), key=lambda device: (device.added_at, device.id))
        ids = [device.id for device in active]
        return ids.index(device_id) if device_id in ids else 0

    def _claimed_elsewhere(self, item: InboxItem, now: datetime) -> bool:
        return CLAIM_REACTION in item.reactions and now - item.date < STALE_CLAIM

    def _require_transport(self) -> VaultTransportPort:
        transport = self._transport()
        if transport is None:
            raise StorageUnavailableError("telegram")
        return transport


def _transient(exc: Exception) -> bool:
    if isinstance(exc, (TelegramFloodWaitError, StorageUnavailableError, VaultLockedError)):
        return True
    if isinstance(exc, TelegramAccountError):
        return exc.code in {"telegram_network", "telegram_not_authorized"}
    return not isinstance(exc, DomainError)


def _optional_str(value: object) -> str | None:
    return str(value) if isinstance(value, str) and value else None
