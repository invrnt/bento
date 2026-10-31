from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Any

from bento.domain.errors import JobNotRetryableError, ValidationFailedError


class JobType(StrEnum):
    THUMBNAIL = "thumbnail"
    METADATA = "metadata"
    OCR = "ocr"
    EMBEDDING = "embedding"
    PDF_THUMBNAIL = "pdf_thumbnail"
    VIDEO_THUMBNAIL = "video_thumbnail"
    REINDEX = "reindex"
    TELEGRAM_IMPORT = "telegram_import"
    JOURNAL_EXPORT = "journal_export"
    ACCOUNT_RELOAD = "account_reload"
    INBOX_IMPORT = "inbox_import"
    REMOTE_UPLOAD = "remote_upload"
    BACKUP_SCAN = "backup_scan"
    BACKUP_UPLOAD = "backup_upload"
    TRASH_PURGE = "trash_purge"
    CACHE_EVICT = "cache_evict"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"


class JobPriority(IntEnum):
    BLOB_ASSET = 0
    THUMBNAIL = 1
    METADATA = 2
    OCR = 3
    EMBEDDING = 4


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    type: JobType
    status: JobStatus
    priority: int
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    asset_id: str | None = None
    locked_by: str | None = None
    locked_at: datetime | None = None
    run_after: datetime | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValidationFailedError("Job id is required")
        if self.attempts < 0:
            raise ValidationFailedError("Job attempts cannot be negative")
        if self.max_attempts < 1:
            raise ValidationFailedError("Job max_attempts must be positive")

    @property
    def can_retry(self) -> bool:
        return self.status == JobStatus.FAILED and self.attempts < self.max_attempts

    def claim(self, worker_id: str, at: datetime) -> Job:
        if self.status not in {JobStatus.QUEUED, JobStatus.RETRYING}:
            raise ValidationFailedError("Only queued or retrying jobs can be claimed")
        return replace(self, status=JobStatus.RUNNING, locked_by=worker_id, locked_at=at, updated_at=at)

    def complete(self, at: datetime) -> Job:
        return replace(self, status=JobStatus.SUCCEEDED, locked_by=None, locked_at=None, updated_at=at, error=None)

    def fail(self, error: str, at: datetime, base_delay: timedelta = timedelta(seconds=30)) -> Job:
        attempts = self.attempts + 1
        if attempts < self.max_attempts:
            delay = base_delay * (2 ** max(attempts - 1, 0))
            return replace(
                self,
                status=JobStatus.RETRYING,
                attempts=attempts,
                locked_by=None,
                locked_at=None,
                run_after=at + delay,
                updated_at=at,
                error=error,
            )
        return replace(
            self,
            status=JobStatus.FAILED,
            attempts=attempts,
            locked_by=None,
            locked_at=None,
            updated_at=at,
            error=error,
        )

    def retry(self, at: datetime) -> Job:
        if not self.can_retry:
            raise JobNotRetryableError(self.id, self.status.value)
        return replace(self, status=JobStatus.QUEUED, run_after=None, error=None, updated_at=at)
