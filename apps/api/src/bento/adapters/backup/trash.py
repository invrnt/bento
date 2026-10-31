"""SQLite trash catalog: trashed assets/folders, restore, and catalog purge through the ORM (so sync sees it)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, func, literal, select, union_all, update
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.mappers import blob_ref_from_model, require_aware
from bento.application.trash import PurgeBlob, PurgeScope
from bento.domain.backup import BackupFileState
from bento.domain.jobs import JobStatus
from bento.domain.storage import BlobKind
from bento.domain.trash import DEFAULT_TRASH_RETENTION_DAYS, TrashItem, TrashItemType, purge_at
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import (
    AlbumAssetModel,
    AssetModel,
    BackupFileModel,
    BlobRefModel,
    FolderModel,
    JobModel,
    ThumbnailModel,
)
from bento.ports.repositories import ClockPort


class SQLiteTrashRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        clock: ClockPort,
        *,
        retention_days: int = DEFAULT_TRASH_RETENTION_DAYS,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._retention_days = retention_days

    async def list(self, *, cursor: str | None = None, limit: int = 50) -> tuple[tuple[TrashItem, ...], str | None]:
        offset = _decode_cursor(cursor)
        limit = max(1, min(limit, 200))
        with session_scope(self._session_factory) as session:
            rows = list(session.execute(self._listing().offset(offset).limit(limit + 1)))
            items = tuple(self._item(session, row) for row in rows[:limit])
        next_cursor = str(offset + limit) if len(rows) > limit else None
        return items, next_cursor

    async def trashed_ids(self, *, limit: int = 500) -> tuple[str, ...]:
        with session_scope(self._session_factory) as session:
            return tuple(row.id for row in session.execute(self._listing().limit(max(limit, 1))))

    async def expired(self, *, now: datetime, limit: int = 100) -> tuple[TrashItem, ...]:
        cutoff = now - timedelta(days=self._retention_days)
        listing = self._listing().subquery()
        with session_scope(self._session_factory) as session:
            rows = list(
                session.execute(
                    select(listing)
                    .where(listing.c.deleted_at <= cutoff)
                    .order_by(listing.c.deleted_at.asc(), listing.c.id.asc())
                    .limit(max(limit, 1))
                )
            )
            return tuple(self._item(session, row) for row in rows)

    async def restore(self, ids: tuple[str, ...]) -> int:
        """Restore trashed items; an item whose parent folder is still trashed moves to the root."""
        if not ids:
            return 0
        now = self._clock.now()
        with session_scope(self._session_factory) as session:
            folders = list(
                session.scalars(select(FolderModel).where(FolderModel.id.in_(ids), FolderModel.deleted_at.is_not(None)))
            )
            assets = list(
                session.scalars(select(AssetModel).where(AssetModel.id.in_(ids), AssetModel.deleted_at.is_not(None)))
            )
            for model in (*folders, *assets):
                model.deleted_at = None
                model.updated_at = now
            session.flush()
            for folder in folders:
                if folder.parent_id is not None and not _folder_visible(session, folder.parent_id):
                    folder.parent_id = None
            for asset in assets:
                if asset.folder_id is not None and not _folder_visible(session, asset.folder_id):
                    asset.folder_id = None
            return len(folders) + len(assets)

    async def expand(self, ids: tuple[str, ...]) -> PurgeScope:
        with session_scope(self._session_factory) as session:
            return _expand(session, ids)

    async def purge_blobs(self, asset_ids: tuple[str, ...]) -> tuple[PurgeBlob, ...]:
        if not asset_ids:
            return ()
        with session_scope(self._session_factory) as session:
            models = session.scalars(select(BlobRefModel).where(BlobRefModel.asset_id.in_(asset_ids)))
            return tuple(
                PurgeBlob(blob_ref=blob_ref_from_model(model), remote_deleted=model.remote_deleted_at is not None)
                for model in models
            )

    async def mark_remote_deleted(self, blob_ids: tuple[str, ...]) -> None:
        if not blob_ids:
            return
        with session_scope(self._session_factory) as session:
            session.execute(
                update(BlobRefModel).where(BlobRefModel.id.in_(blob_ids)).values(remote_deleted_at=self._clock.now())
            )

    async def thumbnail_asset_ids(self, asset_ids: tuple[str, ...]) -> set[str]:
        if not asset_ids:
            return set()
        with session_scope(self._session_factory) as session:
            return {
                asset_id
                for asset_id in session.scalars(
                    select(BlobRefModel.asset_id).where(
                        BlobRefModel.asset_id.in_(asset_ids), BlobRefModel.kind == BlobKind.THUMBNAIL.value
                    )
                )
                if asset_id is not None
            }

    async def purge(self, ids: tuple[str, ...]) -> int:
        with session_scope(self._session_factory) as session:
            scope = _expand(session, ids)
            if not scope.top_level_ids:
                return 0
            asset_ids = scope.asset_ids
            if asset_ids:
                for model in session.scalars(select(ThumbnailModel).where(ThumbnailModel.asset_id.in_(asset_ids))):
                    session.delete(model)
                for model in session.scalars(select(AlbumAssetModel).where(AlbumAssetModel.asset_id.in_(asset_ids))):
                    session.delete(model)
                for model in session.scalars(select(BlobRefModel).where(BlobRefModel.asset_id.in_(asset_ids))):
                    session.delete(model)
                session.flush()
                for model in session.scalars(select(AssetModel).where(AssetModel.id.in_(asset_ids))):
                    session.delete(model)
                session.execute(
                    update(BackupFileModel)
                    .where(BackupFileModel.asset_id.in_(asset_ids))
                    .values(state=BackupFileState.SKIPPED.value, asset_id=None)
                )
                session.execute(
                    delete(JobModel).where(
                        JobModel.asset_id.in_(asset_ids),
                        JobModel.status.in_((JobStatus.QUEUED.value, JobStatus.RETRYING.value)),
                    )
                )
                session.flush()
            if scope.folder_ids:
                # Children first so no row is left pointing at a deleted parent.
                for folder_id in reversed(scope.folder_ids):
                    model = session.get(FolderModel, folder_id)
                    if model is not None:
                        session.delete(model)
                        session.flush()
            return len(scope.top_level_ids)

    def _listing(self):  # type: ignore[no-untyped-def]
        assets = select(
            literal(TrashItemType.ASSET.value).label("type"),
            AssetModel.id.label("id"),
            AssetModel.filename.label("name"),
            AssetModel.size_bytes.label("size_bytes"),
            AssetModel.deleted_at.label("deleted_at"),
        ).where(AssetModel.deleted_at.is_not(None))
        folders = select(
            literal(TrashItemType.FOLDER.value).label("type"),
            FolderModel.id.label("id"),
            FolderModel.name.label("name"),
            literal(0).label("size_bytes"),
            FolderModel.deleted_at.label("deleted_at"),
        ).where(FolderModel.deleted_at.is_not(None))
        combined = union_all(assets, folders).subquery()
        return select(combined).order_by(combined.c.deleted_at.desc(), combined.c.id.desc())

    def _item(self, session: Session, row) -> TrashItem:  # type: ignore[no-untyped-def]
        deleted_at = require_aware(_as_datetime(row.deleted_at))
        item_type = TrashItemType(row.type)
        size = int(row.size_bytes or 0)
        if item_type == TrashItemType.FOLDER:
            folder_ids = (row.id, *_descendants(session, (row.id,)))
            size = int(
                session.scalar(
                    select(func.coalesce(func.sum(AssetModel.size_bytes), 0)).where(AssetModel.folder_id.in_(folder_ids))
                )
                or 0
            )
        return TrashItem(
            id=row.id,
            type=item_type,
            name=row.name,
            size_bytes=size,
            deleted_at=deleted_at,
            purge_at=purge_at(deleted_at, self._retention_days),
        )


def _expand(session: Session, ids: tuple[str, ...]) -> PurgeScope:
    if not ids:
        return PurgeScope((), (), ())
    top_assets = list(session.scalars(select(AssetModel.id).where(AssetModel.id.in_(ids), AssetModel.deleted_at.is_not(None))))
    top_folders = list(
        session.scalars(select(FolderModel.id).where(FolderModel.id.in_(ids), FolderModel.deleted_at.is_not(None)))
    )
    folder_ids = [*top_folders, *_descendants(session, tuple(top_folders))]
    nested_assets = (
        list(session.scalars(select(AssetModel.id).where(AssetModel.folder_id.in_(folder_ids)))) if folder_ids else []
    )
    asset_ids = tuple(dict.fromkeys([*top_assets, *nested_assets]))
    top_level = tuple(item for item in ids if item in set(top_assets) | set(top_folders))
    return PurgeScope(top_level_ids=tuple(dict.fromkeys(top_level)), asset_ids=asset_ids, folder_ids=tuple(folder_ids))


def _descendants(session: Session, roots: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    seen = set(roots)
    frontier = list(roots)
    while frontier:
        children = [
            child for child in session.scalars(select(FolderModel.id).where(FolderModel.parent_id.in_(frontier))) if child not in seen
        ]
        seen.update(children)
        found.extend(children)
        frontier = children
    return found


def _folder_visible(session: Session, folder_id: str) -> bool:
    seen: set[str] = set()
    current: str | None = folder_id
    while current is not None and current not in seen:
        seen.add(current)
        model = session.get(FolderModel, current)
        if model is None or model.deleted_at is not None:
            return False
        current = model.parent_id
    return True


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _decode_cursor(cursor: str | None) -> int:
    try:
        return max(int(cursor), 0) if cursor is not None else 0
    except ValueError:
        return 0
