"""SQLite queries behind the local-first storage pipeline (blob swap, upload job bookkeeping)."""

from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.mappers import asset_from_model, blob_ref_from_model, blob_ref_to_model
from bento.application.storage_pipeline import UPLOADABLE_KINDS
from bento.domain.assets import AssetMetadata
from bento.domain.jobs import JobStatus, JobType
from bento.domain.storage import BlobKind, BlobRef, StorageBackend
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AssetModel, BlobRefModel, JobModel, ThumbnailModel

ACTIVE_JOB_STATUSES = (JobStatus.QUEUED.value, JobStatus.RUNNING.value, JobStatus.RETRYING.value)


def job_payload_value(key: str):  # type: ignore[no-untyped-def]
    return func.json_extract(JobModel.payload_json, f"$.{key}")


class SQLitePipelineCatalog:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def get(self, blob_id: str) -> BlobRef | None:
        with session_scope(self._session_factory) as session:
            model = session.get(BlobRefModel, blob_id)
            return blob_ref_from_model(model) if model is not None else None

    async def asset_metadata(self, asset_id: str) -> tuple[AssetMetadata, bool] | None:
        with session_scope(self._session_factory) as session:
            model = session.get(AssetModel, asset_id)
            if model is None:
                return None
            asset = asset_from_model(model)
            return asset.metadata, asset.is_deleted

    async def replace_with_remote(self, local_blob_id: str, remote: BlobRef) -> bool:
        with session_scope(self._session_factory) as session:
            local = session.get(BlobRefModel, local_blob_id)
            if local is None or local.backend != StorageBackend.LOCAL.value:
                return False
            session.merge(blob_ref_to_model(remote, created_at=local.created_at))
            if remote.id == local_blob_id:
                return True
            session.flush()
            for thumbnail in session.scalars(select(ThumbnailModel).where(ThumbnailModel.blob_ref_id == local_blob_id)):
                thumbnail.blob_ref_id = remote.id
            session.flush()
            session.delete(local)
            return True

    async def has_active_upload(self, blob_id: str) -> bool:
        with session_scope(self._session_factory) as session:
            count = session.scalar(
                select(func.count())
                .select_from(JobModel)
                .where(
                    JobModel.type == JobType.REMOTE_UPLOAD.value,
                    JobModel.status.in_(ACTIVE_JOB_STATUSES),
                    job_payload_value("blob_id") == blob_id,
                )
            )
            return bool(count)

    async def unscheduled_local_blobs(self, *, limit: int) -> tuple[BlobRef, ...]:
        scheduled = (
            select(job_payload_value("blob_id"))
            .where(
                JobModel.type == JobType.REMOTE_UPLOAD.value,
                JobModel.status.in_((*ACTIVE_JOB_STATUSES, JobStatus.FAILED.value)),
                job_payload_value("blob_id").is_not(None),
            )
        )
        statement = (
            select(BlobRefModel)
            .join(AssetModel, AssetModel.id == BlobRefModel.asset_id)
            .where(
                BlobRefModel.backend == StorageBackend.LOCAL.value,
                BlobRefModel.kind.in_([kind.value for kind in UPLOADABLE_KINDS]),
                AssetModel.deleted_at.is_(None),
                BlobRefModel.id.not_in(scheduled),
            )
            .order_by(
                case((BlobRefModel.kind == BlobKind.ORIGINAL.value, 0), else_=1),
                BlobRefModel.created_at.asc(),
                BlobRefModel.id.asc(),
            )
            .limit(max(limit, 1))
        )
        with session_scope(self._session_factory) as session:
            return tuple(blob_ref_from_model(model) for model in session.scalars(statement))
