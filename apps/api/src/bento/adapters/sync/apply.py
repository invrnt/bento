"""`SyncApplyPort`: remote ops and snapshot states applied to local tables with field-level LWW.

Every batch is applied in one `sync_apply` transaction (never captured). Foreign keys are off for that
connection so ops referencing entities this device does not have yet are applied as-is (readers treat
unknown parents as root); purges therefore mirror the schema's `ON DELETE` actions explicitly. Search index
writes for `asset_index` ops run after the commit and are journaled in `sync_state` for crash recovery.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.sync.capture import SYNC_APPLY
from bento.adapters.sync.index_data import AssetIndexData
from bento.adapters.sync.mapping import (
    ALBUM_ITEM,
    BY_ENTITY,
    PARTS_FIELD,
    REMOTE_OBJECT_KEY_PREFIX,
    REMOVED_FIELD,
    TELEGRAM_BACKEND,
    from_wire,
    parts_from_wire,
    split_album_item_key,
)
from bento.adapters.sync.records import HlcCursor, Now, NowMs, load_capture_config, put_state, system_now, system_now_ms
from bento.application.sync.merge import cycle_breaker, find_folder_cycle
from bento.application.sync.state import LAST_NOTICE, PENDING_INDEX_PREFIX
from bento.domain.assets import AssetKind, AssetMode, ProcessingState
from bento.domain.devices import DevicePlatform
from bento.domain.sync import SyncEntity, SyncOperation, SyncOpKind
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import (
    AlbumAssetModel,
    AlbumModel,
    AssetEmbeddingModel,
    AssetModel,
    AssetTextModel,
    BlobPartModel,
    BlobRefModel,
    DeviceModel,
    FolderModel,
    JobModel,
    OCRBlockModel,
    PDFPageModel,
    SyncAppliedBatchModel,
    SyncFieldClockModel,
    SyncPurgedModel,
    SyncStateModel,
    ThumbnailModel,
)
from bento.ports.sync import EntityState

LOGGER = logging.getLogger("bento.sync.apply")

UNNAMED = "Sin nombre"
_SNAPSHOT_CHUNK = 500
_ASSET_SCOPED = frozenset({SyncEntity.ASSET_INDEX, SyncEntity.THUMBNAIL, SyncEntity.ALBUM_ITEM})


class SQLiteSyncApplier:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        index: AssetIndexData | None = None,
        now_ms: NowMs = system_now_ms,
        now: Now = system_now,
    ) -> None:
        self._session_factory = session_factory
        self._index = index
        self._now_ms = now_ms
        self._now = now

    async def apply_batch(
        self,
        batch_id: str,
        message_id: int,
        operations: tuple[SyncOperation, ...],
        *,
        sender: str | None = None,
        sent_at: datetime | None = None,
    ) -> int:
        await self.recover_pending_index()
        with self._apply_session() as session:
            if session.get(SyncAppliedBatchModel, batch_id) is not None:
                return 0
            context = _ApplyContext(session, now_ms=self._now_ms, now=self._now)
            applied = 0
            for operation in sorted(operations, key=lambda item: item.hlc):
                applied += context.apply_op(operation)
            if sender is not None:
                context.mark_seen(sender, sent_at or context.now)
            context.finish(journal_key=f"{PENDING_INDEX_PREFIX}{batch_id}")
            session.add(SyncAppliedBatchModel(batch_id=batch_id, message_id=message_id, applied_at=self._now()))
        await self._write_index(f"{PENDING_INDEX_PREFIX}{batch_id}", context.index_work, context.purged_assets)
        return applied

    async def apply_snapshot(self, states: AsyncIterator[EntityState], purged: tuple[tuple[str, str, str], ...]) -> int:
        await self.recover_pending_index()
        with self._apply_session() as session:
            context = _ApplyContext(session, now_ms=self._now_ms, now=self._now)
            for entity, entity_id, hlc in purged:
                context.purge(SyncEntity(entity), entity_id, hlc)
            context.finish(journal_key=f"{PENDING_INDEX_PREFIX}snapshot-purged")
        await self._write_index(f"{PENDING_INDEX_PREFIX}snapshot-purged", context.index_work, context.purged_assets)

        applied = 0
        chunk: list[EntityState] = []
        async for state in states:
            chunk.append(state)
            if len(chunk) >= _SNAPSHOT_CHUNK:
                applied += await self._apply_states(chunk)
                chunk = []
        if chunk:
            applied += await self._apply_states(chunk)
        return applied

    async def _apply_states(self, states: list[EntityState]) -> int:
        journal = f"{PENDING_INDEX_PREFIX}snapshot"
        with self._apply_session() as session:
            context = _ApplyContext(session, now_ms=self._now_ms, now=self._now)
            applied = sum(context.apply_state(state) for state in states)
            context.finish(journal_key=journal)
        await self._write_index(journal, context.index_work, context.purged_assets)
        return applied

    async def recover_pending_index(self) -> None:
        """Finish search index writes journaled by a batch whose process stopped right after committing."""
        with session_scope(self._session_factory) as session:
            rows = list(session.scalars(select(SyncStateModel).where(SyncStateModel.key.startswith(PENDING_INDEX_PREFIX))))
            journals = [(row.key, row.value) for row in rows]
        for key, value in journals:
            try:
                data = json.loads(value)
                work = {str(asset_id): dict(fields) for asset_id, fields in data.get("index", {}).items()}
                purged = [str(asset_id) for asset_id in data.get("purged", [])]
            except (ValueError, AttributeError, TypeError):
                work, purged = {}, []
            await self._write_index(key, work, purged)

    async def _write_index(self, journal_key: str, work: Mapping[str, Mapping[str, Any]], purged: list[str]) -> None:
        if self._index is not None:
            for asset_id, fields in work.items():
                await self._index.write(asset_id, fields)
            for asset_id in purged:
                await self._index.remove(asset_id)
        with session_scope(self._session_factory) as session:
            session.execute(delete(SyncStateModel).where(SyncStateModel.key == journal_key))

    @contextmanager
    def _apply_session(self) -> Iterator[Session]:
        engine = self._session_factory.kw["bind"]
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            try:
                session = self._session_factory(bind=connection, info={SYNC_APPLY: True})
                try:
                    yield session
                    session.commit()
                except BaseException:
                    session.rollback()
                    raise
                finally:
                    session.close()
            finally:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()


class _ApplyContext:
    """State of one apply transaction."""

    def __init__(self, session: Session, *, now_ms: NowMs, now: Now) -> None:
        self.session = session
        self.now: datetime = now()
        self._now = now
        self._now_ms = now_ms
        config = load_capture_config(session)
        self._hlc = HlcCursor(session, config.device_id, now_ms=now_ms, now=now) if config is not None else None
        self._clocks: dict[tuple[str, str], dict[str, SyncFieldClockModel]] = {}
        self._purged: dict[tuple[str, str], bool] = {}
        self._max_hlc = ""
        self.touched_folders: set[str] = set()
        self.index_work: dict[str, dict[str, Any]] = {}
        self.purged_assets: list[str] = []
        self.notices: list[dict[str, Any]] = []

    # Ops

    def apply_op(self, operation: SyncOperation) -> int:
        self._observe(operation.hlc)
        if self.is_purged(operation.entity, operation.entity_id):
            return 0
        if operation.kind == SyncOpKind.PURGE:
            return self.purge(operation.entity, operation.entity_id, operation.hlc)
        clocks = self._clock_rows(operation.entity, operation.entity_id)
        accepted = {
            name: value
            for name, value in operation.fields.items()
            if (clocks[name].hlc if name in clocks else "") < operation.hlc
        }
        if not accepted:
            return 0
        written = self._write(operation.entity, operation.entity_id, accepted)
        for name in written:
            self._set_clock(operation.entity, operation.entity_id, name, operation.hlc)
        return len(written)

    def apply_state(self, state: EntityState) -> int:
        for clock in state.clocks.values():
            self._observe(clock)
        if self.is_purged(state.entity, state.entity_id):
            return 0
        clocks = self._clock_rows(state.entity, state.entity_id)
        fresh = not clocks and not self._exists(state.entity, state.entity_id)
        accepted: dict[str, Any] = {}
        for name, value in state.fields.items():
            snapshot_clock = state.clocks.get(name)
            local_clock = clocks[name].hlc if name in clocks else None
            if snapshot_clock is not None and snapshot_clock > (local_clock or ""):
                accepted[name] = value
            elif snapshot_clock is None and fresh:
                accepted[name] = value
        if not accepted:
            return 0
        written = self._write(state.entity, state.entity_id, accepted)
        for name in written:
            if name in state.clocks:
                self._set_clock(state.entity, state.entity_id, name, state.clocks[name])
        return len(written)

    def mark_seen(self, device_id: str, at: datetime) -> None:
        """`last_seen_at` is device-local: only the time this device last received a batch from that peer."""
        row = self.session.get(DeviceModel, device_id)
        if row is None:
            return
        current = row.last_seen_at
        if current is not None and current.tzinfo is None:
            current = current.replace(tzinfo=at.tzinfo)
        if current is None or at > current:
            row.last_seen_at = at

    def finish(self, *, journal_key: str) -> None:
        self._repair_folders()
        if self._hlc is not None and self._max_hlc:
            self._hlc.observe(self._max_hlc)
        if self.notices:
            put_state(self.session, LAST_NOTICE, json.dumps(self.notices[-1], sort_keys=True), self.now)
        if self.index_work or self.purged_assets:
            journal = {"index": self.index_work, "purged": self.purged_assets}
            put_state(self.session, journal_key, json.dumps(journal, sort_keys=True), self.now)

    # Purges

    def is_purged(self, entity: SyncEntity, entity_id: str) -> bool:
        key = (entity.value, entity_id)
        if key not in self._purged:
            self._purged[key] = self.session.get(SyncPurgedModel, key) is not None
        if self._purged[key]:
            return True
        if entity == SyncEntity.ASSET_INDEX:
            return self.is_purged(SyncEntity.ASSET, entity_id)
        return False

    def purge(self, entity: SyncEntity, entity_id: str, hlc: str) -> int:
        key = (entity.value, entity_id)
        if self.is_purged(entity, entity_id) and self._purged.get(key):
            return 0
        self._observe(hlc)
        self.session.add(SyncPurgedModel(entity=entity.value, entity_id=entity_id, hlc=hlc, purged_at=self.now))
        self._purged[key] = True
        self.session.execute(
            delete(SyncFieldClockModel).where(
                SyncFieldClockModel.entity == entity.value, SyncFieldClockModel.entity_id == entity_id
            )
        )
        self._clocks.pop(key, None)
        self.session.flush()
        _CASCADES[entity](self, entity_id)
        return 1

    def _purge_folder(self, folder_id: str) -> None:
        self.session.execute(update(FolderModel).where(FolderModel.parent_id == folder_id).values(parent_id=None))
        self.session.execute(update(AssetModel).where(AssetModel.folder_id == folder_id).values(folder_id=None))
        self.session.execute(delete(FolderModel).where(FolderModel.id == folder_id))

    def _purge_asset(self, asset_id: str) -> None:
        for model in (ThumbnailModel, AlbumAssetModel, AssetTextModel, OCRBlockModel, PDFPageModel, AssetEmbeddingModel):
            self.session.execute(delete(model).where(model.asset_id == asset_id))
        self.session.execute(update(BlobRefModel).where(BlobRefModel.asset_id == asset_id).values(asset_id=None))
        self.session.execute(update(JobModel).where(JobModel.asset_id == asset_id).values(asset_id=None))
        self.session.execute(delete(AssetModel).where(AssetModel.id == asset_id))
        self.purged_assets.append(asset_id)
        self.index_work.pop(asset_id, None)

    def _purge_album(self, album_id: str) -> None:
        self.session.execute(delete(AlbumAssetModel).where(AlbumAssetModel.album_id == album_id))
        self.session.execute(delete(AlbumModel).where(AlbumModel.id == album_id))

    def _purge_album_item(self, key: str) -> None:
        try:
            album_id, asset_id = split_album_item_key(key)
        except ValueError:
            return
        self.session.execute(
            delete(AlbumAssetModel).where(AlbumAssetModel.album_id == album_id, AlbumAssetModel.asset_id == asset_id)
        )

    def _purge_blob(self, blob_id: str) -> None:
        self.session.execute(delete(BlobPartModel).where(BlobPartModel.blob_ref_id == blob_id))
        self.session.execute(update(ThumbnailModel).where(ThumbnailModel.blob_ref_id == blob_id).values(blob_ref_id=None))
        self.session.execute(delete(BlobRefModel).where(BlobRefModel.id == blob_id))

    def _purge_thumbnail(self, thumbnail_id: str) -> None:
        self.session.execute(delete(ThumbnailModel).where(ThumbnailModel.id == thumbnail_id))

    def _purge_asset_index(self, asset_id: str) -> None:
        self.index_work.pop(asset_id, None)
        self.purged_assets.append(asset_id)

    def _purge_device(self, device_id: str) -> None:
        self.session.execute(delete(DeviceModel).where(DeviceModel.id == device_id))

    # Field writes

    def _write(self, entity: SyncEntity, entity_id: str, fields: dict[str, Any]) -> set[str]:
        if entity == SyncEntity.ASSET_INDEX:
            self.index_work.setdefault(entity_id, {}).update(fields)
            return set(fields)
        if entity == SyncEntity.ALBUM_ITEM:
            return self._write_album_item(entity_id, fields)
        tracked = BY_ENTITY[entity]
        values: dict[str, Any] = {}
        for name, value in fields.items():
            if name == PARTS_FIELD:
                continue
            try:
                converted = from_wire(tracked, name, value)
            except (TypeError, ValueError):
                LOGGER.warning("Skipped a malformed %s.%s value", entity.value, name)
                continue
            if converted is None and name in _REQUIRED.get(entity, ()):
                continue
            values[name] = converted
        parts = None
        if entity == SyncEntity.BLOB and PARTS_FIELD in fields:
            try:
                parts = parts_from_wire(entity_id, fields[PARTS_FIELD])
            except (KeyError, TypeError, ValueError):
                LOGGER.warning("Skipped malformed blob parts")
        if not values and parts is None:
            return set()
        if entity in _ASSET_SCOPED and self.is_purged(SyncEntity.ASSET, str(values.get("asset_id") or "")):
            return set(values)
        row = self.session.get(tracked.model, entity_id)
        created = row is None
        if row is None:
            row = _CREATORS[entity](entity_id, self.now)
            self.session.add(row)
        for name, value in values.items():
            setattr(row, tracked.columns[name], value)
        if hasattr(row, "updated_at"):
            row.updated_at = self.now
        if parts is not None:
            _replace_parts(row, parts)
        if created:
            self.session.flush()  # later ops of this batch find the row through `Session.get`
        if entity == SyncEntity.FOLDER and "parent_id" in values:
            self.touched_folders.add(entity_id)
        return set(values) | ({PARTS_FIELD} if parts is not None else set())

    def _write_album_item(self, key: str, fields: dict[str, Any]) -> set[str]:
        try:
            album_id, asset_id = split_album_item_key(key)
        except ValueError:
            return set()
        written = {name for name in fields if name in {"album_id", "asset_id"}}
        removed = fields.get(REMOVED_FIELD)
        if REMOVED_FIELD in fields and not isinstance(removed, bool):
            removed = None
        created_at = None
        if "created_at" in fields:
            try:
                created_at = from_wire(ALBUM_ITEM, "created_at", fields["created_at"])
                written.add("created_at")
            except (TypeError, ValueError):
                created_at = None
        row = self.session.get(AlbumAssetModel, (album_id, asset_id))
        if removed is None:
            removed = row is None and REMOVED_FIELD in self._clock_rows(SyncEntity.ALBUM_ITEM, key)
        else:
            written.add(REMOVED_FIELD)
        if removed or self.is_purged(SyncEntity.ASSET, asset_id) or self.is_purged(SyncEntity.ALBUM, album_id):
            if row is not None:
                self.session.delete(row)
            return written
        if row is None:
            row = AlbumAssetModel(album_id=album_id, asset_id=asset_id, created_at=created_at or self.now)
            self.session.add(row)
            self.session.flush()
        elif created_at is not None:
            row.created_at = created_at
        return written

    def _exists(self, entity: SyncEntity, entity_id: str) -> bool:
        if entity == SyncEntity.ASSET_INDEX:
            return False
        if entity == SyncEntity.ALBUM_ITEM:
            try:
                return self.session.get(AlbumAssetModel, split_album_item_key(entity_id)) is not None
            except ValueError:
                return False
        return self.session.get(BY_ENTITY[entity].model, entity_id) is not None

    # Clocks and HLC

    def _clock_rows(self, entity: SyncEntity, entity_id: str) -> dict[str, SyncFieldClockModel]:
        key = (entity.value, entity_id)
        cached = self._clocks.get(key)
        if cached is None:
            cached = {
                row.field: row
                for row in self.session.scalars(
                    select(SyncFieldClockModel).where(
                        SyncFieldClockModel.entity == entity.value, SyncFieldClockModel.entity_id == entity_id
                    )
                )
            }
            self._clocks[key] = cached
        return cached

    def _set_clock(self, entity: SyncEntity, entity_id: str, name: str, hlc: str) -> None:
        clocks = self._clock_rows(entity, entity_id)
        row = clocks.get(name)
        if row is None:
            row = SyncFieldClockModel(entity=entity.value, entity_id=entity_id, field=name, hlc=hlc)
            self.session.add(row)
            clocks[name] = row
        elif row.hlc < hlc:
            row.hlc = hlc

    def _observe(self, hlc: str) -> None:
        if hlc > self._max_hlc:
            self._max_hlc = hlc

    # Folder cycles

    def _repair_folders(self) -> None:
        if not self.touched_folders:
            return
        self.session.flush()

        def parent_of(folder_id: str) -> str | None:
            row = self.session.get(FolderModel, folder_id)
            return row.parent_id if row is not None else None

        for folder_id in sorted(self.touched_folders):
            row = self.session.get(FolderModel, folder_id)
            if row is None or row.parent_id is None:
                continue
            if self.is_purged(SyncEntity.FOLDER, row.parent_id):
                self._move_to_root(row, "purged_parent")
                continue
            while (cycle := find_folder_cycle(folder_id, parent_of)) is not None:
                clocks = {
                    member: (self._clock_rows(SyncEntity.FOLDER, member).get("parent_id") or _NO_CLOCK).hlc
                    for member in cycle
                }
                breaker = self.session.get(FolderModel, cycle_breaker(cycle, clocks))
                if breaker is None:
                    break
                self._move_to_root(breaker, "cycle")

    def _move_to_root(self, row: FolderModel, reason: str) -> None:
        row.parent_id = None
        row.updated_at = self.now
        self.notices.append({"kind": "folder_moved_to_root", "folder_id": row.id, "reason": reason, "at": self.now.isoformat()})
        LOGGER.info("Moved a synced folder to the root (%s)", reason)
        self.session.flush()


class _NoClock:
    hlc = ""


_NO_CLOCK = _NoClock()

_REQUIRED: Mapping[SyncEntity, frozenset[str]] = {
    SyncEntity.FOLDER: frozenset({"name", "created_at"}),
    SyncEntity.ASSET: frozenset(
        {"kind", "mode", "filename", "original_filename", "mime_type", "size_bytes", "sha256", "favorite", "created_at"}
    ),
    SyncEntity.ALBUM: frozenset({"title", "created_at"}),
    SyncEntity.BLOB: frozenset({"kind", "size_bytes", "encryption_mode", "format_version"}),
    SyncEntity.THUMBNAIL: frozenset({"asset_id"}),
    SyncEntity.DEVICE: frozenset({"name", "platform", "public_key", "added_at"}),
}
"""Non-nullable columns: a null wire value is ignored instead of breaking the transaction."""


def _replace_parts(row: BlobRefModel, parts: list[BlobPartModel]) -> None:
    existing = {part.part_index: part for part in row.parts}
    wanted = {part.part_index: part for part in parts}
    for index, part in existing.items():
        if index not in wanted:
            row.parts.remove(part)
    for index, part in sorted(wanted.items()):
        current = existing.get(index)
        if current is None:
            row.parts.append(part)
        else:
            current.channel_id = part.channel_id
            current.message_id = part.message_id
            current.size_bytes = part.size_bytes


def _new_folder(entity_id: str, now: datetime) -> FolderModel:
    return FolderModel(id=entity_id, name=UNNAMED, parent_id=None, created_at=now, updated_at=now)


def _new_asset(entity_id: str, now: datetime) -> AssetModel:
    return AssetModel(
        id=entity_id,
        kind=AssetKind.OTHER.value,
        mode=AssetMode.DRIVE.value,
        folder_id=None,
        filename=UNNAMED,
        original_filename=UNNAMED,
        mime_type="application/octet-stream",
        size_bytes=0,
        sha256="0" * 64,
        processing_state=ProcessingState.INDEXED.value,
        favorite=False,
        created_at=now,
        updated_at=now,
    )


def _new_album(entity_id: str, now: datetime) -> AlbumModel:
    return AlbumModel(id=entity_id, title=UNNAMED, created_at=now, updated_at=now)


def _new_blob(entity_id: str, now: datetime) -> BlobRefModel:
    return BlobRefModel(
        id=entity_id,
        asset_id=None,
        backend=TELEGRAM_BACKEND,
        kind="original",
        object_key=f"{REMOTE_OBJECT_KEY_PREFIX}{entity_id}",
        size_bytes=0,
        encryption_mode="none",
        format_version=1,
        created_at=now,
    )


def _new_thumbnail(entity_id: str, now: datetime) -> ThumbnailModel:
    return ThumbnailModel(id=entity_id, asset_id="", blob_ref_id=None, created_at=now)


def _new_device(entity_id: str, now: datetime) -> DeviceModel:
    return DeviceModel(
        id=entity_id, name=UNNAMED, platform=DevicePlatform.OTHER.value, public_key="", added_at=now, is_current=False
    )


_CREATORS = {
    SyncEntity.FOLDER: _new_folder,
    SyncEntity.ASSET: _new_asset,
    SyncEntity.ALBUM: _new_album,
    SyncEntity.BLOB: _new_blob,
    SyncEntity.THUMBNAIL: _new_thumbnail,
    SyncEntity.DEVICE: _new_device,
}

_CASCADES = {
    SyncEntity.FOLDER: _ApplyContext._purge_folder,
    SyncEntity.ASSET: _ApplyContext._purge_asset,
    SyncEntity.ALBUM: _ApplyContext._purge_album,
    SyncEntity.ALBUM_ITEM: _ApplyContext._purge_album_item,
    SyncEntity.BLOB: _ApplyContext._purge_blob,
    SyncEntity.THUMBNAIL: _ApplyContext._purge_thumbnail,
    SyncEntity.ASSET_INDEX: _ApplyContext._purge_asset_index,
    SyncEntity.DEVICE: _ApplyContext._purge_device,
}
