"""Full local state for snapshots (`SnapshotSourcePort`) and for the initial publish (`FullStatePublisherPort`)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.sync.index_data import AssetIndexData
from bento.adapters.sync.mapping import (
    ALBUM_ITEM,
    ASSET,
    BLOB,
    FOLDER,
    REMOVED_FIELD,
    TELEGRAM_BACKEND,
    THUMBNAIL,
    TRACKED_MODELS,
    TrackedModel,
    entity_key,
    row_fields,
    split_album_item_key,
)
from bento.adapters.sync.records import Now, NowMs, OpWriter, load_capture_config, system_now, system_now_ms
from bento.domain.storage import BlobKind
from bento.domain.sync import SyncEntity, SyncOpKind
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import (
    AlbumAssetModel,
    AssetModel,
    BlobRefModel,
    FolderModel,
    SyncFieldClockModel,
    SyncPurgedModel,
)
from bento.ports.sync import EntityState

_CHUNK = 500


class SQLiteSnapshotSource:
    """Snapshot states honour the hold rule: asset-scoped entities only for assets with a remote original."""

    def __init__(self, session_factory: sessionmaker[Session], *, index: AssetIndexData) -> None:
        self._session_factory = session_factory
        self._index = index

    async def iter_states(self) -> AsyncIterator[EntityState]:
        with session_scope(self._session_factory) as session:
            remote = _remote_assets(session)
        for tracked in TRACKED_MODELS:
            for rows in _row_chunks(self._session_factory, tracked):
                with session_scope(self._session_factory) as session:
                    keyed = [(entity_key(tracked, row), row) for row in rows if _publishable(tracked, row, remote)]
                    clocks = _clocks(session, tracked.entity, [key for key, _ in keyed])
                    states = [
                        EntityState(tracked.entity, key, row_fields(tracked, row), clocks.get(key, {}))
                        for key, row in keyed
                    ]
                for state in states:
                    yield state
        for state in self._album_item_tombstones(remote):
            yield state
        for state in self._index_states(remote):
            yield state

    async def purged(self) -> tuple[tuple[str, str, str], ...]:
        with session_scope(self._session_factory) as session:
            return tuple(
                (row.entity, row.entity_id, row.hlc)
                for row in session.scalars(select(SyncPurgedModel).order_by(SyncPurgedModel.entity, SyncPurgedModel.entity_id))
            )

    def _album_item_tombstones(self, remote: set[str]) -> list[EntityState]:
        """Removed album items keep only their clocks; snapshots carry them so stale re-adds stay removed."""
        with session_scope(self._session_factory) as session:
            keys = sorted(
                set(
                    session.scalars(
                        select(SyncFieldClockModel.entity_id).where(
                            SyncFieldClockModel.entity == SyncEntity.ALBUM_ITEM.value,
                            SyncFieldClockModel.field == REMOVED_FIELD,
                        )
                    )
                )
            )
            states: list[EntityState] = []
            for start in range(0, len(keys), _CHUNK):
                chunk = keys[start : start + _CHUNK]
                clocks = _clocks(session, SyncEntity.ALBUM_ITEM, chunk)
                for key in chunk:
                    try:
                        album_id, asset_id = split_album_item_key(key)
                    except ValueError:
                        continue
                    if asset_id not in remote or session.get(AlbumAssetModel, (album_id, asset_id)) is not None:
                        continue
                    fields = {REMOVED_FIELD: True, "album_id": album_id, "asset_id": asset_id}
                    states.append(EntityState(SyncEntity.ALBUM_ITEM, key, fields, clocks.get(key, {})))
            return states

    def _index_states(self, remote: set[str]) -> list[EntityState]:
        with session_scope(self._session_factory) as session:
            asset_ids = [asset_id for asset_id in self._index.indexed_asset_ids(session) if asset_id in remote]
            data = self._index.read(session, asset_ids)
            clocks = _clocks(session, SyncEntity.ASSET_INDEX, list(data))
        return [
            EntityState(SyncEntity.ASSET_INDEX, asset_id, fields, clocks.get(asset_id, {}))
            for asset_id, fields in sorted(data.items())
        ]


class SQLiteFullStatePublisher:
    """Initial publish: upserts with every synced field of every local entity, in chunked transactions."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        index: AssetIndexData,
        now_ms: NowMs = system_now_ms,
        now: Now = system_now,
    ) -> None:
        self._session_factory = session_factory
        self._index = index
        self._now_ms = now_ms
        self._now = now

    async def publish_full_state(self) -> int:
        with session_scope(self._session_factory) as session:
            config = load_capture_config(session)
        if config is None:
            return 0
        count = 0
        for tracked in TRACKED_MODELS:
            for rows in _row_chunks(self._session_factory, tracked):
                with session_scope(self._session_factory) as session:
                    writer = OpWriter(session, config, now_ms=self._now_ms, now=self._now)
                    for row in rows:
                        if tracked is BLOB and row.backend != TELEGRAM_BACKEND:
                            continue
                        writer.emit(tracked.entity, entity_key(tracked, row), SyncOpKind.UPSERT, row_fields(tracked, row))
                    count += writer.count
        with session_scope(self._session_factory) as session:
            existing = set(session.scalars(select(AssetModel.id)))
            asset_ids = [asset_id for asset_id in self._index.indexed_asset_ids(session) if asset_id in existing]
        for start in range(0, len(asset_ids), _CHUNK):
            with session_scope(self._session_factory) as session:
                writer = OpWriter(session, config, now_ms=self._now_ms, now=self._now)
                for asset_id, fields in sorted(self._index.read(session, asset_ids[start : start + _CHUNK]).items()):
                    writer.emit(SyncEntity.ASSET_INDEX, asset_id, SyncOpKind.UPSERT, fields)
                count += writer.count
        return count


def _remote_assets(session: Session) -> set[str]:
    return {
        asset_id
        for asset_id in session.scalars(
            select(BlobRefModel.asset_id).where(
                BlobRefModel.kind == BlobKind.ORIGINAL.value,
                BlobRefModel.backend == TELEGRAM_BACKEND,
                BlobRefModel.asset_id.is_not(None),
            )
        )
        if asset_id
    }


def _publishable(tracked: TrackedModel, row: Any, remote: set[str]) -> bool:
    if tracked is ASSET:
        return bool(row.id in remote)
    if tracked in (THUMBNAIL, ALBUM_ITEM):
        return bool(row.asset_id in remote)
    if tracked is BLOB:
        return bool(row.backend == TELEGRAM_BACKEND)
    return True


def _row_chunks(session_factory: sessionmaker[Session], tracked: TrackedModel) -> Iterator[list[Any]]:
    """Rows of one tracked table in chunks of detached instances (folders parents-first)."""
    if tracked is FOLDER:
        yield from _folder_chunks(session_factory)
        return
    model = tracked.model
    last: tuple[Any, ...] | None = None
    while True:
        with session_scope(session_factory) as session:
            if tracked is ALBUM_ITEM:
                statement = select(model).order_by(model.album_id, model.asset_id)
                if last is not None:
                    statement = statement.where(tuple_(model.album_id, model.asset_id) > tuple_(*last))
            else:
                statement = select(model).order_by(model.id)
                if last is not None:
                    statement = statement.where(model.id > last[0])
            rows = list(session.scalars(statement.limit(_CHUNK)))
            if tracked is BLOB:
                for row in rows:
                    _ = row.parts
        if not rows:
            return
        yield rows
        tail = rows[-1]
        last = (tail.album_id, tail.asset_id) if tracked is ALBUM_ITEM else (tail.id,)


def _folder_chunks(session_factory: sessionmaker[Session]) -> Iterator[list[Any]]:
    with session_scope(session_factory) as session:
        parents = dict(session.execute(select(FolderModel.id, FolderModel.parent_id)).tuples().all())
    depth: dict[str, int] = {}

    def depth_of(folder_id: str) -> int:
        seen: list[str] = []
        current: str | None = folder_id
        while current is not None and current in parents and current not in depth and current not in seen:
            seen.append(current)
            current = parents[current]
        base = depth.get(current, 0) if current is not None else 0
        for offset, item in enumerate(reversed(seen), start=1):
            depth[item] = base + offset
        return depth.get(folder_id, 0)

    ordered = sorted(parents, key=lambda folder_id: (depth_of(folder_id), folder_id))
    for start in range(0, len(ordered), _CHUNK):
        chunk = ordered[start : start + _CHUNK]
        with session_scope(session_factory) as session:
            rows = {row.id: row for row in session.scalars(select(FolderModel).where(FolderModel.id.in_(chunk)))}
        yield [rows[folder_id] for folder_id in chunk if folder_id in rows]


def _clocks(session: Session, entity: SyncEntity, keys: list[str]) -> dict[str, dict[str, str]]:
    clocks: dict[str, dict[str, str]] = {}
    for start in range(0, len(keys), _CHUNK):
        chunk = keys[start : start + _CHUNK]
        for row in session.scalars(
            select(SyncFieldClockModel).where(
                SyncFieldClockModel.entity == entity.value, SyncFieldClockModel.entity_id.in_(chunk)
            )
        ):
            clocks.setdefault(row.entity_id, {})[row.field] = row.hlc
    return clocks
