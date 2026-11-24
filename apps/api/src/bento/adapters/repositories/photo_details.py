"""Batched per-item details for photo grids (`api/android-endpoints.md` §5): dimensions, remote state, and the
thumbnail chosen for a requested size. One query per kind of detail for a whole page, never per item."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.mappers import blob_ref_from_model
from bento.domain.backup import BackupFileState
from bento.domain.jobs import JobStatus, JobType
from bento.domain.storage import BlobKind, BlobRef, StorageBackend
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import (
    AssetModel,
    BackupFileModel,
    BlobRefModel,
    CacheEntryModel,
    JobModel,
    ThumbnailModel,
)

_ACTIVE = (JobStatus.QUEUED.value, JobStatus.RUNNING.value, JobStatus.RETRYING.value)


@dataclass(frozen=True, slots=True)
class PhotoItemDetails:
    width: int | None
    height: int | None
    remote_state: str  # local_only | uploading | remote | failed
    thumbnail_etag: str | None


@dataclass(frozen=True, slots=True)
class LocalOriginalState:
    offline_pinned: bool
    """The original is pinned in the cache ("Disponible sin conexión")."""
    locally_available: bool
    """The original can be opened without the network: never uploaded, cached, or still in its backup source
    (read from the catalog; the backup file is not stat'ed, so a moved source file still counts)."""


class SQLitePhotoDetails:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def details(self, asset_ids: list[str]) -> dict[str, PhotoItemDetails]:
        if not asset_ids:
            return {}
        with session_scope(self._session_factory) as session:
            thumbs = session.execute(
                select(ThumbnailModel.asset_id, ThumbnailModel.blob_ref_id, ThumbnailModel.width, ThumbnailModel.height)
                .where(ThumbnailModel.asset_id.in_(asset_ids))
            ).all()
            remote = set(
                session.scalars(
                    select(BlobRefModel.asset_id).where(
                        BlobRefModel.asset_id.in_(asset_ids),
                        BlobRefModel.kind == BlobKind.ORIGINAL.value,
                        BlobRefModel.backend == StorageBackend.TELEGRAM.value,
                    )
                )
            )
            uploads = session.execute(
                select(JobModel.asset_id, JobModel.status)
                .where(
                    JobModel.asset_id.in_(asset_ids),
                    JobModel.type == JobType.REMOTE_UPLOAD.value,
                    func.json_extract(JobModel.payload_json, "$.kind") == BlobKind.ORIGINAL.value,
                    JobModel.status.in_((*_ACTIVE, JobStatus.FAILED.value)),
                )
            ).all()
        largest: dict[str, tuple[int, int | None, int | None]] = {}
        thumb_ids: dict[str, list[str]] = {}
        for asset_id, blob_id, width, height in thumbs:
            side = max(width or 0, height or 0)
            if side >= largest.get(asset_id, (-1, None, None))[0]:
                largest[asset_id] = (side, width, height)
            if blob_id:
                thumb_ids.setdefault(asset_id, []).append(blob_id)
        states: dict[str, str] = {}
        for asset_id, status in uploads:
            if status in _ACTIVE:
                states[asset_id] = "uploading"
            else:
                states.setdefault(asset_id, "failed")
        result = {}
        for asset_id in asset_ids:
            _side, width, height = largest.get(asset_id, (0, None, None))
            ids = sorted(thumb_ids.get(asset_id, ()))
            result[asset_id] = PhotoItemDetails(
                width=width,
                height=height,
                remote_state="remote" if asset_id in remote else states.get(asset_id, "local_only"),
                thumbnail_etag=hashlib.sha1("|".join(ids).encode()).hexdigest()[:16] if ids else None,
            )
        return result

    def local_states(self, asset_ids: list[str]) -> dict[str, LocalOriginalState]:
        """Per asset, whether its original is on this device: three queries for the whole page."""
        if not asset_ids:
            return {}
        with session_scope(self._session_factory) as session:
            originals = session.execute(
                select(BlobRefModel.asset_id, BlobRefModel.id, BlobRefModel.backend).where(
                    BlobRefModel.asset_id.in_(asset_ids), BlobRefModel.kind == BlobKind.ORIGINAL.value
                )
            ).all()
            blob_ids = [blob_id for _asset, blob_id, _backend in originals]
            cached = (
                dict(
                    session.execute(
                        select(CacheEntryModel.blob_ref_id, CacheEntryModel.pinned).where(
                            CacheEntryModel.blob_ref_id.in_(blob_ids)
                        )
                    ).all()
                )
                if blob_ids
                else {}
            )
            in_sources = set(
                session.scalars(
                    select(BackupFileModel.asset_id).where(
                        BackupFileModel.asset_id.in_(asset_ids), BackupFileModel.state == BackupFileState.DONE.value
                    )
                )
            )
        pinned: set[str] = set()
        local: set[str] = set(in_sources)
        for asset_id, blob_id, backend in originals:
            if backend == StorageBackend.LOCAL.value or blob_id in cached:
                local.add(asset_id)
            if cached.get(blob_id):
                pinned.add(asset_id)
        return {
            asset_id: LocalOriginalState(offline_pinned=asset_id in pinned, locally_available=asset_id in local)
            for asset_id in asset_ids
        }

    def video_asset_ids(self, asset_ids: list[str]) -> set[str]:
        if not asset_ids:
            return set()
        with session_scope(self._session_factory) as session:
            return set(session.scalars(select(AssetModel.id).where(AssetModel.id.in_(asset_ids), AssetModel.kind == "video")))

    def thumbnail_bytes(self) -> int:
        """Bytes of thumbnails and previews stored on this device (they are kept, never evicted)."""
        with session_scope(self._session_factory) as session:
            return int(
                session.scalar(
                    select(func.coalesce(func.sum(BlobRefModel.size_bytes), 0)).where(
                        BlobRefModel.kind.in_((BlobKind.THUMBNAIL.value, BlobKind.PREVIEW.value)),
                        BlobRefModel.backend == StorageBackend.LOCAL.value,
                    )
                )
                or 0
            )

    def thumbnail_for_size(self, asset_id: str, size: int) -> BlobRef | None:
        """The smallest stored thumbnail whose longer side is at least `size`, else the largest one."""
        with session_scope(self._session_factory) as session:
            rows = session.execute(
                select(BlobRefModel, ThumbnailModel.width, ThumbnailModel.height, ThumbnailModel.created_at)
                .join(ThumbnailModel, ThumbnailModel.blob_ref_id == BlobRefModel.id)
                .where(ThumbnailModel.asset_id == asset_id)
            ).all()
            candidates = [
                (max(width or 0, height or 0), created_at, blob_ref_from_model(model)) for model, width, height, created_at in rows
            ]
        if not candidates:
            return None
        newest = max(created for _side, created, _ref in candidates)
        # Only the latest generation (thumbnails are regenerated together).
        current = [(side, ref) for side, created, ref in candidates if (newest - created).total_seconds() < 600] or [
            (side, ref) for side, _created, ref in candidates
        ]
        fitting = sorted((item for item in current if item[0] >= size), key=lambda item: item[0])
        if fitting:
            return fitting[0][1]
        return max(current, key=lambda item: item[0])[1]
