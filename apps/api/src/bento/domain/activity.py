from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ActivitySummary(StrEnum):
    UP_TO_DATE = "up_to_date"
    UPLOADING = "uploading"
    DOWNLOADING = "downloading"
    SYNCING = "syncing"
    PAUSED = "paused"
    OFFLINE = "offline"
    ATTENTION = "attention"


class AttentionKind(StrEnum):
    UPLOAD_FAILED = "upload_failed"
    SYNC_ERROR = "sync_error"
    FLOOD_WAIT = "flood_wait"
    RECOVERY_KIT = "recovery_kit"
    INBOX_FAILED = "inbox_failed"
    NEW_DEVICE = "new_device"
    DEVICE_REMOVED = "device_removed"


class AttentionAction(StrEnum):
    RETRY = "retry"
    OPEN_SETTINGS = "open_settings"
    SAVE_RECOVERY_KIT = "save_recovery_kit"
    OPEN_DEVICES = "open_devices"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class TransferStats:
    active: int = 0
    queued: int = 0
    bytes_total: int = 0
    bytes_done: int = 0
    eta_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class AttentionItem:
    id: str
    kind: AttentionKind
    title_key: str
    action: AttentionAction = AttentionAction.NONE
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Activity:
    summary: ActivitySummary
    uploads: TransferStats = TransferStats()
    downloads: TransferStats = TransferStats()
    attention: tuple[AttentionItem, ...] = ()
