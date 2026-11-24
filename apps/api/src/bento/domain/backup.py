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
    # Phone original removed through "Liberar espacio" after its upload was verified; the asset stays.
    FREED = "freed"


class BackupSourceKind(StrEnum):
    FOLDER = "folder"
    MEDIA_STORE = "media_store"


class BackupSuggestionKind(StrEnum):
    PICTURES = "pictures"
    DOCUMENTS = "documents"
    DESKTOP = "desktop"
    DOWNLOADS = "downloads"
    MEDIA_STORE = "media_store"


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
    kind: BackupSourceKind = BackupSourceKind.FOLDER
    bucket_id: str | None = None


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
    # MediaStore id for `media_store` sources (`relative_path` is then the display name inside the bucket).
    source_key: str | None = None


@dataclass(frozen=True, slots=True)
class BackupSuggestion:
    path: str
    label: str
    kind: BackupSuggestionKind
    # MediaStore buckets (Android): bucket id, item count, and whether it is on by default (Camera, Screenshots).
    bucket_id: str | None = None
    count: int | None = None
    suggested: bool = False


@dataclass(frozen=True, slots=True)
class MediaAccess:
    full: bool
    partial: bool
    location: bool


@dataclass(frozen=True, slots=True)
class MediaBucket:
    bucket_id: str
    name: str
    relative_path: str
    count: int
    video_count: int = 0


@dataclass(frozen=True, slots=True)
class MediaItem:
    media_id: str
    uri: str
    bucket_id: str
    display_name: str
    mime_type: str
    size_bytes: int
    generation: int
    date_taken_ms: int | None = None
    date_modified_s: int | None = None
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    relative_path: str = ""

    @property
    def change_token(self) -> int:
        """Stored in `backup_files.mtime_ns`: the MediaStore generation (or modification time) changes on edit."""
        if self.generation > 0:
            return self.generation
        return (self.date_modified_s or 0) * 1_000_000_000


@dataclass(frozen=True, slots=True)
class BackupPolicy:
    paused: bool = False
    pause_on_battery: bool = True
    bandwidth_limit_kbps: int = 0
    on_battery: bool = False

    @property
    def effective_paused(self) -> bool:
        return self.paused or (self.pause_on_battery and self.on_battery)
