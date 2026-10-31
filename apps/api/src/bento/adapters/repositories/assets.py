from __future__ import annotations

from collections import OrderedDict

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.ids import new_id
from bento.adapters.repositories.mappers import asset_from_model, asset_to_model
from bento.domain.assets import Asset, AssetMode
from bento.domain.photos import TimelineGroup
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AssetModel


class SQLiteAssetRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def next_id(self) -> str:
        return new_id("asset")

    async def get(self, asset_id: str) -> Asset | None:
        with session_scope(self._session_factory) as session:
            model = session.scalar(
                select(AssetModel).where(AssetModel.id == asset_id, AssetModel.deleted_at.is_(None))
            )
            return asset_from_model(model) if model is not None else None

    async def get_by_sha256(self, sha256: str) -> Asset | None:
        with session_scope(self._session_factory) as session:
            model = session.scalar(
                select(AssetModel)
                .where(AssetModel.sha256 == sha256, AssetModel.deleted_at.is_(None))
                .order_by(AssetModel.created_at.desc(), AssetModel.id.desc())
                .limit(1)
            )
            return asset_from_model(model) if model is not None else None

    async def add(self, asset: Asset) -> None:
        with session_scope(self._session_factory) as session:
            session.add(asset_to_model(asset))

    async def save(self, asset: Asset) -> None:
        with session_scope(self._session_factory) as session:
            session.merge(asset_to_model(asset))

    async def list_live(self, *, after_id: str | None = None, limit: int = 200) -> tuple[Asset, ...]:
        """Non-trashed assets in id order, after `after_id` (keyset pages for whole-library jobs)."""
        statement = select(AssetModel).where(AssetModel.deleted_at.is_(None))
        if after_id is not None:
            statement = statement.where(AssetModel.id > after_id)
        with session_scope(self._session_factory) as session:
            models = session.scalars(statement.order_by(AssetModel.id.asc()).limit(max(limit, 1)))
            return tuple(asset_from_model(model) for model in models)

    async def list_photos_timeline(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[tuple[TimelineGroup, ...], str | None]:
        offset = _decode_cursor(cursor)
        with session_scope(self._session_factory) as session:
            sort_date = func.coalesce(AssetModel.taken_at, AssetModel.created_at)
            statement: Select[tuple[AssetModel]] = (
                select(AssetModel)
                .where(AssetModel.mode == AssetMode.PHOTOS.value, AssetModel.deleted_at.is_(None))
                .order_by(sort_date.desc(), AssetModel.id.desc())
                .offset(offset)
                .limit(limit + 1)
            )
            models = list(session.scalars(statement))

        visible = models[:limit]
        groups: OrderedDict[object, list[str]] = OrderedDict()
        for asset in (asset_from_model(model) for model in visible):
            group_date = (asset.metadata.taken_at or asset.created_at).date()
            groups.setdefault(group_date, []).append(asset.id)

        next_cursor = str(offset + limit) if len(models) > limit else None
        return tuple(TimelineGroup(day=day, asset_ids=tuple(asset_ids)) for day, asset_ids in groups.items()), next_cursor


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(cursor)
    except ValueError:
        return 0
    return max(value, 0)
