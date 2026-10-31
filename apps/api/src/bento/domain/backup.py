from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class BackupSourceState(StrEnum):
    IDLE = "idle"
    SCANNING = "scanning"
    UPLOADING = "uploading"
    PAUSED = "paused"
    ERROR = "error"


class BackupFileState(StrEnum):
    PENDING = "pending"
    UPLOADING = "uploading"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class BackupSuggestionKind(StrEnum):
    PICTURES = "pictures"
    DOCUMENTS = "documents"
    DESKTOP = "desktop"
    DOWNLOADS = "downloads"


@dataclass(frozen=True, slots=True)
class BackupSource:
    id: str
    path: str
    label: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    state: BackupSourceState = BackupSourceState.IDLE
    files_total: int = 0
    files_done: int = 0
    files_pending: int = 0
    bytes_pending: int = 0
    last_scan_at: datetime | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class BackupFile:
    source_id: str
    relative_path: str
    size_bytes: int
    mtime_ns: int
    state: BackupFileState
    updated_at: datetime
    sha256: str | None = None
    asset_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class BackupSuggestion:
    path: str
    label: str
    kind: BackupSuggestionKind


@dataclass(frozen=True, slots=True)
class BackupPolicy:
    paused: bool = False
    pause_on_battery: bool = True
    bandwidth_limit_kbps: int = 0
    on_battery: bool = False

    @property
    def effective_paused(self) -> bool:
        return self.paused or (self.pause_on_battery and self.on_battery)
