"""SQLite `ContentImportStorePort`: Android fd imports kept across process restarts (device-local)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from bento.domain.imports import ContentImport, ImportItemState
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import ContentImportItemModel, ContentImportModel


class SQLiteContentImportStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def create(self, job: ContentImport, *, owner: str, at: datetime) -> None:
        with session_scope(self._session_factory) as session:
            session.add(
                ContentImportModel(id=job.id, owner=owner, folder_id=job.folder_id, album_id=job.album_id, created_at=at)
            )
            session.flush()
            session.add_all(_item_model(job.id, item) for item in job.items)

    async def save_item(self, import_id: str, item: ImportItemState) -> None:
        with session_scope(self._session_factory) as session:
            session.merge(_item_model(import_id, item))

    async def finish(self, import_id: str, *, at: datetime) -> None:
        with session_scope(self._session_factory) as session:
            session.execute(
                update(ContentImportModel)
                .where(ContentImportModel.id == import_id, ContentImportModel.finished_at.is_(None))
                .values(finished_at=at)
            )

    async def get(self, import_id: str) -> ContentImport | None:
        with session_scope(self._session_factory) as session:
            model = session.get(ContentImportModel, import_id)
            return _job(session, model) if model is not None else None

    async def unfinished(self, *, other_than_owner: str) -> list[ContentImport]:
        with session_scope(self._session_factory) as session:
            models = session.scalars(
                select(ContentImportModel).where(
                    ContentImportModel.finished_at.is_(None), ContentImportModel.owner != other_than_owner
                )
            )
            return [_job(session, model) for model in models]

    async def replace_items(self, job: ContentImport, *, finished_at: datetime) -> None:
        with session_scope(self._session_factory) as session:
            for item in job.items:
                session.merge(_item_model(job.id, item))
            session.execute(
                update(ContentImportModel)
                .where(ContentImportModel.id == job.id, ContentImportModel.finished_at.is_(None))
                .values(finished_at=finished_at)
            )

    async def dismiss(self, import_id: str, *, at: datetime) -> bool:
        with session_scope(self._session_factory) as session:
            result = session.execute(
                update(ContentImportModel)
                .where(ContentImportModel.id == import_id, ContentImportModel.finished_at.is_not(None))
                .values(dismissed_at=at)
            )
            return bool(result.rowcount)

    async def prune(self, *, keep: int) -> None:
        with session_scope(self._session_factory) as session:
            stale = list(
                session.scalars(
                    select(ContentImportModel.id)
                    .where(ContentImportModel.finished_at.is_not(None))
                    .order_by(ContentImportModel.finished_at.desc(), ContentImportModel.id.desc())
                    .offset(keep)
                )
            )
            if stale:
                session.execute(delete(ContentImportItemModel).where(ContentImportItemModel.import_id.in_(stale)))
                session.execute(delete(ContentImportModel).where(ContentImportModel.id.in_(stale)))


def _item_model(import_id: str, item: ImportItemState) -> ContentImportItemModel:
    return ContentImportItemModel(
        import_id=import_id,
        client_index=item.client_index,
        status=item.status,
        asset_id=item.asset_id,
        error_code=item.error,
    )


def _job(session: Session, model: ContentImportModel) -> ContentImport:
    items = session.scalars(
        select(ContentImportItemModel)
        .where(ContentImportItemModel.import_id == model.id)
        .order_by(ContentImportItemModel.client_index)
    )
    return ContentImport(
        id=model.id,
        items=[
            ImportItemState(client_index=row.client_index, status=row.status, asset_id=row.asset_id, error=row.error_code)
            for row in items
        ],
        folder_id=model.folder_id,
        album_id=model.album_id,
        done=model.finished_at is not None,
        dismissed=model.dismissed_at is not None,
    )
