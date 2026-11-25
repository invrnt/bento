from __future__ import annotations

import base64
import json
from collections import OrderedDict
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.batching import chunks, parent_conditions
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

    async def get_many(self, asset_ids: Sequence[str]) -> dict[str, Asset]:
        found: dict[str, Asset] = {}
        with session_scope(self._session_factory) as session:
            for chunk in chunks(asset_ids):
                models = session.scalars(
                    select(AssetModel).where(AssetModel.id.in_(chunk), AssetModel.deleted_at.is_(None))
                )
                found.update((model.id, asset_from_model(model)) for model in models)
        return found

    async def get_many_by_sha256(self, sha256s: Sequence[str]) -> dict[str, Asset]:
        found: dict[str, Asset] = {}
        with session_scope(self._session_factory) as session:
            for chunk in chunks(sha256s):
                models = session.scalars(
                    select(AssetModel)
                    .where(AssetModel.sha256.in_(chunk), AssetModel.deleted_at.is_(None))
                    .order_by(AssetModel.created_at.desc(), AssetModel.id.desc())
                )
                for model in models:
                    if model.sha256 not in found:
                        found[model.sha256] = asset_from_model(model)
        return found

    async def list_in_folders(self, folder_ids: Sequence[str | None], *, limit: int | None = None) -> tuple[Asset, ...]:
        found: list[Asset] = []
        with session_scope(self._session_factory) as session:
            for condition in parent_conditions(AssetModel.folder_id, folder_ids):
                remaining = None if limit is None else limit - len(found)
                if remaining is not None and remaining <= 0:
                    break
                statement = (
                    select(AssetModel)
                    .where(condition, AssetModel.deleted_at.is_(None))
                    .order_by(AssetModel.folder_id, AssetModel.filename, AssetModel.id)
                )
                if remaining is not None:
                    statement = statement.limit(remaining)
                found.extend(asset_from_model(model) for model in session.scalars(statement))
        return tuple(found)

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
        """Newest first. Cursors are keyset positions (`k.<token>`); legacy numeric offsets still work."""
        keyset = _decode_keyset(cursor)
        offset = 0 if keyset is not None else _decode_cursor(cursor)
        with session_scope(self._session_factory) as session:
            sort_date = func.coalesce(AssetModel.taken_at, AssetModel.created_at)
            statement: Select[tuple[AssetModel]] = (
                select(AssetModel)
                .where(AssetModel.mode == AssetMode.PHOTOS.value, AssetModel.deleted_at.is_(None))
                .order_by(sort_date.desc(), AssetModel.id.desc())
            )
            if keyset is not None:
                before, before_id = keyset
                statement = statement.where(or_(sort_date < before, and_(sort_date == before, AssetModel.id < before_id)))
            elif offset:
                statement = statement.offset(offset)
            models = list(session.scalars(statement.limit(limit + 1)))

        visible = models[:limit]
        groups: OrderedDict[object, list[str]] = OrderedDict()
        for asset in (asset_from_model(model) for model in visible):
            group_date = (asset.metadata.taken_at or asset.created_at).date()
            groups.setdefault(group_date, []).append(asset.id)

        next_cursor = None
        if len(models) > limit and visible:
            last = visible[-1]
            next_cursor = encode_timeline_cursor(last.taken_at or last.created_at, last.id)
        return tuple(TimelineGroup(day=day, asset_ids=tuple(asset_ids)) for day, asset_ids in groups.items()), next_cursor

    async def photos_month_index(self) -> tuple[tuple[str, int, str], ...]:
        """`(YYYY-MM, count, cursor of the month's first item)` newest first, in one grouped query."""
        with session_scope(self._session_factory) as session:
            sort_date = func.coalesce(AssetModel.taken_at, AssetModel.created_at)
            month = func.strftime("%Y-%m", sort_date)
            rows = session.execute(
                select(month, func.count())
                .where(AssetModel.mode == AssetMode.PHOTOS.value, AssetModel.deleted_at.is_(None))
                .group_by(month)
                .order_by(month.desc())
            ).all()
        index = []
        for value, count in rows:
            if not value:
                continue
            year, number = (int(part) for part in str(value).split("-"))
            following = datetime(year + (number == 12), number % 12 + 1, 1, tzinfo=UTC)
            # Everything strictly before the next month's first instant: the month's newest item comes first.
            index.append((str(value), int(count), encode_timeline_cursor(following, "")))
        return tuple(index)


def encode_timeline_cursor(sort_date: datetime, asset_id: str) -> str:
    raw = json.dumps([sort_date.isoformat(), asset_id], separators=(",", ":")).encode()
    return "k." + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_keyset(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor or not cursor.startswith("k."):
        return None
    token = cursor[2:]
    try:
        values = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        moment = datetime.fromisoformat(values[0])
        asset_id = str(values[1])
    except (ValueError, TypeError, IndexError, json.JSONDecodeError):
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)), asset_id


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(cursor)
    except ValueError:
        return 0
    return max(value, 0)
