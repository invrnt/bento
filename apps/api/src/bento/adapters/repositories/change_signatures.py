"""SQLite `ChangeSignaturesPort`: one aggregate query per table (counts and latest timestamps)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from bento.application.events import ChangeTopic
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import (
    AlbumAssetModel,
    AlbumModel,
    AssetModel,
    ContentImportItemModel,
    ContentImportModel,
    DeviceModel,
    FolderModel,
    JobModel,
    SyncStateModel,
    ThumbnailModel,
)


class SQLiteChangeSignatures:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def signatures(self, topics: frozenset[ChangeTopic]) -> Mapping[ChangeTopic, str]:
        with session_scope(self._session_factory) as session:
            return {topic: _signature(session, topic) for topic in topics}


def _signature(session: Session, topic: ChangeTopic) -> str:
    if topic == ChangeTopic.LIBRARY:
        parts: list[Any] = [
            *_row(session, AssetModel.updated_at),
            *_row(session, FolderModel.updated_at),
            *_row(session, AlbumModel.updated_at),
            session.scalar(select(func.count()).select_from(AlbumAssetModel)),
            *_row(session, ThumbnailModel.created_at),
        ]
    elif topic == ChangeTopic.JOBS:
        parts = [*_row(session, JobModel.updated_at)]
    elif topic == ChangeTopic.IMPORTS:
        parts = [
            *_row(session, ContentImportModel.created_at),
            session.scalar(select(func.max(ContentImportModel.finished_at))),
            session.scalar(select(func.max(ContentImportModel.dismissed_at))),
            *session.execute(
                select(func.count(), func.count().filter(ContentImportItemModel.status.in_(("done", "duplicate", "failed"))))
            ).one(),
        ]
    else:
        parts = [
            *_row(session, SyncStateModel.updated_at),
            *_row(session, DeviceModel.added_at),
            session.scalar(select(func.max(DeviceModel.removed_at))),
            session.scalar(select(func.max(DeviceModel.reviewed_at))),
        ]
    return "|".join("" if part is None else str(part) for part in parts)


def _row(session: Session, column: Any) -> tuple[Any, Any]:
    count, latest = session.execute(select(func.count(), func.max(column)).select_from(column.class_)).one()
    return count, latest
