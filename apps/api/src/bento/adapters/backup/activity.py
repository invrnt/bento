"""SQLite counters behind `GET /activity` (jobs, upload sessions, backup files, inbox items)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.backup.pipeline import job_payload_value
from bento.adapters.repositories.mappers import require_aware
from bento.application.account import FLOOD_WAIT_UNTIL_KEY
from bento.application.activity import (
    MAX_ATTENTION_PER_KIND,
    THROUGHPUT_WINDOW_SECONDS,
    ActivitySnapshot,
    FailedBackupSource,
    FailedInboxItem,
    FailedUpload,
)
from bento.domain.backup import BackupFileState
from bento.domain.jobs import JobStatus, JobType
from bento.domain.storage import BlobKind, StorageBackend
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import (
    BackupFileModel,
    BackupSourceModel,
    BlobRefModel,
    InboxItemModel,
    JobModel,
    SyncStateModel,
    UploadSessionModel,
)

_WAITING = (JobStatus.QUEUED.value, JobStatus.RETRYING.value)
_FINISHED_SESSION_STATES = frozenset({"completed", "complete", "done", "failed", "discarded", "abandoned"})
_FAILED_INBOX_STATES = ("failed", "error")


class SQLiteActivitySource:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def snapshot(self, *, now: datetime) -> ActivitySnapshot:
        with session_scope(self._session_factory) as session:
            uploads = list(
                session.scalars(
                    select(JobModel).where(
                        JobModel.type == JobType.REMOTE_UPLOAD.value,
                        JobModel.status.in_((*_WAITING, JobStatus.RUNNING.value)),
                    )
                )
            )
            running = [job for job in uploads if job.status == JobStatus.RUNNING.value]
            waiting = [job for job in uploads if job.status != JobStatus.RUNNING.value]
            original = BlobKind.ORIGINAL.value
            bytes_total = sum(_size(job) for job in uploads)
            bytes_done = sum(self._progress(session, job) for job in running)
            flood_until = max(
                (until for until in (_flood_until(job) for job in waiting) if until is not None and until > now),
                default=None,
            )

            window_start = now - timedelta(seconds=THROUGHPUT_WINDOW_SECONDS)
            recent = list(
                session.execute(
                    select(JobModel.payload_json, JobModel.updated_at).where(
                        JobModel.type == JobType.REMOTE_UPLOAD.value,
                        JobModel.status == JobStatus.SUCCEEDED.value,
                        JobModel.updated_at >= window_start,
                    )
                )
            )
            recent_bytes = sum(int((payload or {}).get("size_bytes") or 0) for payload, _ in recent)
            oldest = min((require_aware(updated) for _, updated in recent), default=None)

            pending_states = (BackupFileState.PENDING.value, BackupFileState.UPLOADING.value)
            backup_row = session.execute(
                select(func.count(), func.coalesce(func.sum(BackupFileModel.size_bytes), 0))
                .select_from(BackupFileModel)
                .join(BackupSourceModel, BackupSourceModel.id == BackupFileModel.source_id)
                .where(BackupFileModel.state.in_(pending_states), BackupSourceModel.enabled.is_(True))
            ).one()

            return ActivitySnapshot(
                uploads_running=sum(1 for job in running if _kind(job) == original),
                uploads_queued=sum(1 for job in waiting if _kind(job) == original),
                derived_pending=sum(1 for job in uploads if _kind(job) != original),
                upload_bytes_total=bytes_total,
                upload_bytes_done=bytes_done,
                backup_pending_files=int(backup_row[0]),
                backup_pending_bytes=int(backup_row[1]),
                recent_uploaded_bytes=recent_bytes,
                recent_window_seconds=(now - oldest).total_seconds() if oldest is not None else 0,
                flood_wait_until=flood_until,
                telegram_flood_wait_until=_telegram_flood_until(session, now),
                failed_uploads=self._failed_uploads(session),
                failed_backups=self._failed_backups(session),
                failed_inbox=self._failed_inbox(session),
            )

    def _progress(self, session: Session, job: JobModel) -> int:
        blob_id = (job.payload_json or {}).get("blob_id")
        statement = select(UploadSessionModel).order_by(UploadSessionModel.updated_at.desc()).limit(5)
        if blob_id:
            candidates = list(session.scalars(statement.where(UploadSessionModel.blob_ref_id == blob_id)))
        else:
            candidates = []
        if not candidates and job.asset_id is not None:
            candidates = list(
                session.scalars(
                    statement.where(
                        UploadSessionModel.asset_id == job.asset_id,
                        UploadSessionModel.blob_kind == _kind(job),
                    )
                )
            )
        for upload in candidates:
            if upload.state in _FINISHED_SESSION_STATES:
                continue
            uploaded = sum(int(part.get("size_bytes") or 0) for part in upload.completed_parts or () if isinstance(part, dict))
            if upload.ciphertext_size <= 0:
                return 0
            return min(upload.plaintext_size, uploaded * upload.plaintext_size // upload.ciphertext_size)
        return 0

    def _failed_uploads(self, session: Session) -> tuple[FailedUpload, ...]:
        rows = session.execute(
            select(JobModel.id, JobModel.asset_id, JobModel.error, job_payload_value("blob_id"))
            .join(BlobRefModel, BlobRefModel.id == job_payload_value("blob_id"))
            .where(
                JobModel.type == JobType.REMOTE_UPLOAD.value,
                JobModel.status == JobStatus.FAILED.value,
                BlobRefModel.backend == StorageBackend.LOCAL.value,
            )
            .order_by(JobModel.updated_at.desc(), JobModel.id.desc())
        ).all()
        seen: set[str] = set()
        result: list[FailedUpload] = []
        for job_id, asset_id, error, blob_id in rows:
            if blob_id in seen:
                continue
            seen.add(blob_id)
            result.append(FailedUpload(job_id=job_id, asset_id=asset_id, error=error))
            if len(result) >= MAX_ATTENTION_PER_KIND:
                break
        return tuple(result)

    def _failed_backups(self, session: Session) -> tuple[FailedBackupSource, ...]:
        failed_counts = dict(
            session.execute(
                select(BackupFileModel.source_id, func.count())
                .where(BackupFileModel.state == BackupFileState.FAILED.value)
                .group_by(BackupFileModel.source_id)
            ).all()
        )
        if not failed_counts:
            return ()
        labels = dict(
            session.execute(
                select(BackupSourceModel.id, BackupSourceModel.label).where(BackupSourceModel.id.in_(failed_counts))
            ).all()
        )
        parked = session.execute(
            select(JobModel.id, job_payload_value("source_id"))
            .where(
                JobModel.type == JobType.BACKUP_SCAN.value,
                JobModel.status == JobStatus.FAILED.value,
                JobModel.attempts < JobModel.max_attempts,
            )
            .order_by(JobModel.updated_at.desc())
        ).all()
        jobs: dict[str, str] = {}
        for job_id, source_id in parked:
            jobs.setdefault(str(source_id), job_id)
        return tuple(
            FailedBackupSource(job_id=jobs[source_id], source_id=source_id, label=labels.get(source_id, ""), failed_files=int(count))
            for source_id, count in sorted(failed_counts.items())
            if source_id in jobs and source_id in labels
        )

    def _failed_inbox(self, session: Session) -> tuple[FailedInboxItem, ...]:
        rows = session.execute(
            select(InboxItemModel.message_id, InboxItemModel.error_code)
            .where(InboxItemModel.state.in_(_FAILED_INBOX_STATES))
            .order_by(InboxItemModel.updated_at.desc())
            .limit(MAX_ATTENTION_PER_KIND)
        ).all()
        return tuple(FailedInboxItem(message_id=int(message_id), error_code=error_code) for message_id, error_code in rows)


def _size(job: JobModel) -> int:
    return int((job.payload_json or {}).get("size_bytes") or 0)


def _kind(job: JobModel) -> str:
    return str((job.payload_json or {}).get("kind") or BlobKind.ORIGINAL.value)


def _flood_until(job: JobModel) -> datetime | None:
    return _parse_until((job.payload_json or {}).get("flood_wait_until"))


def _telegram_flood_until(session: Session, now: datetime) -> datetime | None:
    row = session.get(SyncStateModel, FLOOD_WAIT_UNTIL_KEY)
    until = _parse_until(row.value if row is not None else None)
    return until if until is not None and until > now else None


def _parse_until(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        return require_aware(datetime.fromisoformat(str(raw)))
    except ValueError:
        return None
