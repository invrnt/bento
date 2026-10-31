from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.ids import new_id
from bento.adapters.repositories.mappers import album_from_model, album_to_model
from bento.domain.photos import Album
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AlbumAssetModel, AlbumModel


class SQLiteAlbumRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def next_id(self) -> str:
        return new_id("album")

    async def get(self, album_id: str) -> Album | None:
        with session_scope(self._session_factory) as session:
            model = session.scalar(select(AlbumModel).where(AlbumModel.id == album_id, AlbumModel.deleted_at.is_(None)))
            if model is None:
                return None
            return album_from_model(model, _album_asset_ids(session, album_id))

    async def add(self, album: Album) -> None:
        with session_scope(self._session_factory) as session:
            session.add(album_to_model(album))
            _replace_album_assets(session, album)

    async def save(self, album: Album) -> None:
        with session_scope(self._session_factory) as session:
            session.merge(album_to_model(album))
            _replace_album_assets(session, album)

    async def list(self, *, cursor: str | None = None, limit: int = 50) -> tuple[tuple[Album, ...], str | None]:
        offset = _decode_cursor(cursor)
        with session_scope(self._session_factory) as session:
            models = list(
                session.scalars(
                    select(AlbumModel)
                    .where(AlbumModel.deleted_at.is_(None))
                    .order_by(AlbumModel.updated_at.desc(), AlbumModel.id.desc())
                    .offset(offset)
                    .limit(limit + 1)
                )
            )
            albums = tuple(album_from_model(model, _album_asset_ids(session, model.id)) for model in models[:limit])
        next_cursor = str(offset + limit) if len(models) > limit else None
        return albums, next_cursor


def _album_asset_ids(session: Session, album_id: str) -> frozenset[str]:
    return frozenset(
        session.scalars(select(AlbumAssetModel.asset_id).where(AlbumAssetModel.album_id == album_id))
    )


def _replace_album_assets(session: Session, album: Album) -> None:
    # The session does not autoflush and the models have no relationship, so the unit of work would not order the
    # album row before its items: write the album first or the `album_assets` foreign key fails.
    session.flush()
    session.execute(delete(AlbumAssetModel).where(AlbumAssetModel.album_id == album.id))
    for asset_id in sorted(album.asset_ids):
        session.add(AlbumAssetModel(album_id=album.id, asset_id=asset_id, created_at=album.updated_at))


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(cursor)
    except ValueError:
        return 0
    return max(value, 0)
