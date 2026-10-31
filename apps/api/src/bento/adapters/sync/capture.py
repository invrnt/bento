"""SQLAlchemy change capture for synced models (architecture § Change capture).

`before_flush` diffs inserts/updates/deletes of tracked models and adds outbox rows, field clocks, and the
advanced HLC to the same transaction. ORM bulk `update()`/`delete()` statements on tracked models are
recorded in `do_orm_execute` and emitted at the next flush (or before commit when nothing else flushes).
Raw SQL text statements are not captured. Sessions with `info["sync_apply"]` (remote ops) are skipped, and
nothing is captured until the vault is ready on this device (`sync_state["capture"]`).
"""

from __future__ import annotations

import logging
import weakref
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import event, inspect, select, tuple_
from sqlalchemy.orm import ORMExecuteState, Session, sessionmaker

from bento.adapters.sync.mapping import (
    ALBUM_ITEM,
    BLOB,
    BLOB_PARTS_TABLE,
    BY_MODEL,
    BY_TABLE,
    ORDER,
    PARTS_FIELD,
    REMOVED_FIELD,
    TELEGRAM_BACKEND,
    TRACKED_MODELS,
    TrackedModel,
    album_item_key,
    entity_key,
    model_fields,
    parts_to_wire,
    same_value,
    to_wire,
)
from bento.adapters.sync.records import (
    CaptureConfig,
    Now,
    NowMs,
    OpWriter,
    load_capture_config,
    system_now,
    system_now_ms,
)
from bento.domain.sync import SyncOpKind
from bento.infrastructure.db.engine import add_session_factory_hook, remove_session_factory_hook
from bento.infrastructure.db.models import AlbumAssetModel, BlobPartModel, BlobRefModel

LOGGER = logging.getLogger("bento.sync.capture")

SYNC_APPLY = "sync_apply"
"""`Session.info` flag of sessions applying remote ops; they are never captured."""

_INSTALLED: weakref.WeakSet[sessionmaker[Session]] = weakref.WeakSet()
_PENDING = "_sync_capture_pending"
_CONFIG = "_sync_capture_config"
_UNSET = object()


@dataclass(slots=True)
class _Planned:
    tracked: TrackedModel
    key: str
    kind: SyncOpKind
    fields: dict[str, Any]


@dataclass(slots=True)
class _Pending:
    """Bulk DML seen earlier in the transaction, not yet turned into ops."""

    deleted: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Table → entity key → committed blob backend (blob refs) or None."""
    updates: list[_Planned] = field(default_factory=list)
    full_blobs: set[str] = field(default_factory=set)
    parts_touched: set[str] = field(default_factory=set)

    def __bool__(self) -> bool:
        return bool(self.deleted or self.updates or self.full_blobs or self.parts_touched)


class ChangeCapture:
    def __init__(self, *, now_ms: NowMs = system_now_ms, now: Now = system_now) -> None:
        self._now_ms = now_ms
        self._now = now

    def install(self, factory: sessionmaker[Session]) -> None:
        if factory in _INSTALLED:
            return
        _INSTALLED.add(factory)
        event.listen(factory, "before_flush", self.before_flush)
        event.listen(factory, "before_commit", self.before_commit)
        event.listen(factory, "do_orm_execute", self.do_orm_execute)
        event.listen(factory, "after_commit", self.reset)
        event.listen(factory, "after_rollback", self.reset)

    # Events

    def before_flush(self, session: Session, flush_context: Any, instances: Any) -> None:
        del flush_context, instances
        if session.info.get(SYNC_APPLY):
            return
        tracked_changes = _has_tracked_changes(session)
        pending: _Pending | None = session.info.get(_PENDING)
        if not tracked_changes and not pending:
            return
        config = self._config(session)
        session.info.pop(_PENDING, None)
        if config is None:
            return
        self._emit(session, config, pending or _Pending(), orm=True)

    def before_commit(self, session: Session) -> None:
        if session.info.get(SYNC_APPLY) or not session.info.get(_PENDING):
            return
        if session.new or session.dirty or session.deleted:
            return  # the commit's flush runs `before_flush`, which emits the pending ops
        config = self._config(session)
        pending: _Pending = session.info.pop(_PENDING)
        if config is not None:
            self._emit(session, config, pending, orm=False)

    def do_orm_execute(self, state: ORMExecuteState) -> Any:
        session = state.session
        if session.info.get(SYNC_APPLY) or not (state.is_delete or state.is_update):
            return None
        table = getattr(getattr(state.statement, "table", None), "name", None)
        if table not in BY_TABLE and table != BLOB_PARTS_TABLE:
            return None
        if self._config(session) is None:
            return None
        pending: _Pending = session.info.setdefault(_PENDING, _Pending())
        where = getattr(state.statement, "whereclause", None)
        if table == BLOB_PARTS_TABLE:
            pending.parts_touched.update(_select_values(session, BlobPartModel.blob_ref_id, where))
            return None
        tracked = BY_TABLE[table]
        if state.is_delete:
            pending.deleted.setdefault(tracked.table, {}).update(_bulk_delete_keys(session, tracked, where))
            return None
        before = _bulk_rows(session, tracked, where)
        result = state.invoke_statement()
        if before:
            after = _rows_by_key(session, tracked, before.keys())
            for key, old in before.items():
                new = after.get(key)
                if new is not None:
                    self._record_bulk_update(tracked, key, old, new, pending)
        return result

    def reset(self, session: Session) -> None:
        session.info.pop(_PENDING, None)
        session.info.pop(_CONFIG, None)

    # Emission

    def _config(self, session: Session) -> CaptureConfig | None:
        cached = session.info.get(_CONFIG, _UNSET)
        if cached is _UNSET:
            cached = load_capture_config(session)
            session.info[_CONFIG] = cached
        return cached  # type: ignore[return-value]

    def _emit(self, session: Session, config: CaptureConfig, pending: _Pending, *, orm: bool) -> None:
        planned = list(pending.updates)
        with session.no_autoflush:
            if orm:
                planned.extend(_orm_changes(session, pending))
            planned.extend(_pending_deletes(session, pending, planned))
            planned.extend(_pending_blob_updates(session, pending, planned))
        if not planned:
            return
        writer = OpWriter(session, config, now_ms=self._now_ms, now=self._now)
        for item in sorted(planned, key=lambda entry: ORDER[entry.tracked.entity]):
            writer.emit(item.tracked.entity, item.key, item.kind, item.fields)

    def _record_bulk_update(
        self, tracked: TrackedModel, key: str, old: dict[str, Any], new: dict[str, Any], pending: _Pending
    ) -> None:
        if tracked is BLOB:
            if new["_backend"] != TELEGRAM_BACKEND:
                return
            if old["_backend"] != TELEGRAM_BACKEND:
                pending.full_blobs.add(key)
                return
        changed = {
            name: to_wire(tracked, name, new[name]) for name in tracked.columns if not same_value(old[name], new[name])
        }
        if changed:
            for name in tracked.identity_fields:
                changed.setdefault(name, to_wire(tracked, name, new[name]))
            pending.updates.append(_Planned(tracked, key, SyncOpKind.UPSERT, changed))


_capture = ChangeCapture()


def install_change_capture(factory: sessionmaker[Session], *, now_ms: NowMs | None = None, now: Now | None = None) -> None:
    """Install capture on one session factory (idempotent per factory)."""
    if now_ms is None and now is None:
        _capture.install(factory)
        return
    ChangeCapture(now_ms=now_ms or system_now_ms, now=now or system_now).install(factory)


def configure_change_capture(enabled: bool) -> None:
    """Process-wide switch used by the API and worker composition: every session factory created afterwards
    gets change capture when the storage backend can sync (`telegram`/`fake`)."""
    if enabled:
        add_session_factory_hook(install_change_capture)
    else:
        remove_session_factory_hook(install_change_capture)


# ORM change collection


def _has_tracked_changes(session: Session) -> bool:
    return any(_is_tracked(obj) for obj in (*session.new, *session.dirty, *session.deleted))


def _is_tracked(obj: object) -> bool:
    return type(obj) in BY_MODEL or isinstance(obj, BlobPartModel)


def _orm_changes(session: Session, pending: _Pending) -> list[_Planned]:
    planned: list[_Planned] = []
    bulk_deleted_items = pending.deleted.get(ALBUM_ITEM.table, {})
    parts_parents: set[str] = set()
    handled_blobs: set[str] = set()

    for obj in list(session.new):
        if isinstance(obj, BlobPartModel):
            if obj.blob_ref_id:
                parts_parents.add(obj.blob_ref_id)
            continue
        tracked = BY_MODEL.get(type(obj))
        if tracked is None:
            continue
        key = entity_key(tracked, obj)
        if tracked is ALBUM_ITEM and bulk_deleted_items.pop(key, _UNSET) is not _UNSET:
            continue  # deleted and re-added in one transaction: unchanged
        if tracked is BLOB:
            handled_blobs.add(key)
            if obj.backend != TELEGRAM_BACKEND:
                continue
        planned.append(_Planned(tracked, key, SyncOpKind.UPSERT, _full_fields(session, tracked, obj)))

    for obj in list(session.dirty):
        if isinstance(obj, BlobPartModel):
            if obj.blob_ref_id and session.is_modified(obj):
                parts_parents.add(obj.blob_ref_id)
            continue
        tracked = BY_MODEL.get(type(obj))
        if tracked is None or not session.is_modified(obj, include_collections=True):
            continue
        key = entity_key(tracked, obj)
        if tracked is BLOB:
            handled_blobs.add(key)
        fields = _update_fields(session, tracked, obj)
        if fields:
            planned.append(_Planned(tracked, key, SyncOpKind.UPSERT, fields))

    for obj in list(session.deleted):
        if isinstance(obj, BlobPartModel):
            parent = _committed(obj, "blob_ref_id")
            if parent:
                parts_parents.add(parent)
            continue
        tracked = BY_MODEL.get(type(obj))
        if tracked is None:
            continue
        key = entity_key(tracked, obj)
        if tracked is BLOB:
            handled_blobs.add(key)
            if _committed(obj, "backend") != TELEGRAM_BACKEND:
                continue
        planned.append(_deletion(tracked, key))

    pending.parts_touched.update(parts_parents - handled_blobs)
    return planned


def _full_fields(session: Session, tracked: TrackedModel, obj: Any, *, parts_from_db: bool = False) -> dict[str, Any]:
    fields = model_fields(tracked, obj)
    if tracked is ALBUM_ITEM:
        fields[REMOVED_FIELD] = False
    if tracked is BLOB:
        fields[PARTS_FIELD] = parts_to_wire(_current_parts(session, obj, from_db=parts_from_db))
    return fields


def _update_fields(session: Session, tracked: TrackedModel, obj: Any) -> dict[str, Any] | None:
    state = inspect(obj)
    if tracked is BLOB:
        if obj.backend != TELEGRAM_BACKEND:
            return None
        if _committed(obj, "backend") != TELEGRAM_BACKEND:
            return _full_fields(session, tracked, obj)  # became remote: peers have never seen it
    changed: dict[str, Any] = {}
    for name, attribute in tracked.columns.items():
        history = state.attrs[attribute].history
        if not history.has_changes():
            continue
        current = getattr(obj, attribute)
        if history.deleted and same_value(history.deleted[0], current):
            continue
        changed[name] = to_wire(tracked, name, current)
    if tracked is BLOB and state.attrs.parts.history.has_changes():
        changed[PARTS_FIELD] = parts_to_wire(_current_parts(session, obj))
    if not changed:
        return None
    for name in tracked.identity_fields:
        changed.setdefault(name, to_wire(tracked, name, getattr(obj, tracked.columns[name])))
    return changed


def _deletion(tracked: TrackedModel, key: str) -> _Planned:
    if tracked is ALBUM_ITEM:
        album_id, _, asset_id = key.partition(":")
        return _Planned(tracked, key, SyncOpKind.UPSERT, {REMOVED_FIELD: True, "album_id": album_id, "asset_id": asset_id})
    return _Planned(tracked, key, SyncOpKind.PURGE, {})


def _pending_deletes(session: Session, pending: _Pending, planned: list[_Planned]) -> list[_Planned]:
    del session, planned
    deletions: list[_Planned] = []
    for table, keys in pending.deleted.items():
        tracked = BY_TABLE[table]
        for key, backend in sorted(keys.items()):
            if tracked is BLOB and backend != TELEGRAM_BACKEND:
                continue
            deletions.append(_deletion(tracked, key))
            if tracked is BLOB:
                pending.parts_touched.discard(key)
                pending.full_blobs.discard(key)
    return deletions


def _pending_blob_updates(session: Session, pending: _Pending, planned: list[_Planned]) -> list[_Planned]:
    """Blob refs that became remote through bulk updates, and parents whose parts changed on their own."""
    already = {item.key for item in planned if item.tracked is BLOB}
    updates: list[_Planned] = []
    for blob_id in sorted((pending.full_blobs | pending.parts_touched) - already):
        blob = session.get(BlobRefModel, blob_id)
        if blob is None or blob.backend != TELEGRAM_BACKEND:
            continue
        if blob_id in pending.full_blobs:
            fields = _full_fields(session, BLOB, blob, parts_from_db=True)
        else:
            fields = {
                PARTS_FIELD: parts_to_wire(_current_parts(session, blob, from_db=True)),
                "asset_id": blob.asset_id,
                "kind": blob.kind,
            }
        updates.append(_Planned(BLOB, blob_id, SyncOpKind.UPSERT, fields))
    return updates


def _current_parts(session: Session, blob: BlobRefModel, *, from_db: bool = False) -> list[BlobPartModel]:
    state = inspect(blob)
    if not from_db and "parts" in state.dict:
        parts = list(blob.parts)
    else:
        parts = list(session.scalars(select(BlobPartModel).where(BlobPartModel.blob_ref_id == blob.id)))
    parts.extend(
        obj
        for obj in session.new
        if isinstance(obj, BlobPartModel) and obj.blob_ref_id == blob.id and all(obj is not part for part in parts)
    )
    by_index: dict[int, BlobPartModel] = {}
    for part in parts:
        if part not in session.deleted:
            by_index[part.part_index] = part
    return [by_index[index] for index in sorted(by_index)]


def _committed(obj: Any, attribute: str) -> Any:
    history = inspect(obj).attrs[attribute].history
    if history.deleted:
        return history.deleted[0]
    return getattr(obj, attribute)


# Bulk DML helpers


def _key_columns(tracked: TrackedModel) -> tuple[Any, ...]:
    if tracked is ALBUM_ITEM:
        return (AlbumAssetModel.album_id, AlbumAssetModel.asset_id)
    return (tracked.model.id,)


def _row_key(tracked: TrackedModel, row: Any) -> str:
    if tracked is ALBUM_ITEM:
        return album_item_key(row[0], row[1])
    return str(row[0])


def _select_values(session: Session, column: Any, where: Any) -> set[str]:
    statement = select(column)
    if where is not None:
        statement = statement.where(where)
    return {str(value) for value in session.scalars(statement) if value is not None}


def _bulk_delete_keys(session: Session, tracked: TrackedModel, where: Any) -> dict[str, Any]:
    columns = (*_key_columns(tracked), *((BlobRefModel.backend,) if tracked is BLOB else ()))
    statement = select(*columns)
    if where is not None:
        statement = statement.where(where)
    with session.no_autoflush:
        rows = session.execute(statement).all()
    return {_row_key(tracked, row): (row[-1] if tracked is BLOB else None) for row in rows}


def _synced_columns(tracked: TrackedModel) -> tuple[Any, ...]:
    columns = tuple(getattr(tracked.model, attribute) for attribute in tracked.columns.values())
    return (*columns, BlobRefModel.backend) if tracked is BLOB else columns


def _as_dict(tracked: TrackedModel, row: Any, offset: int) -> dict[str, Any]:
    values = dict(zip(tracked.columns, row[offset : offset + len(tracked.columns)], strict=True))
    if tracked is BLOB:
        values["_backend"] = row[-1]
    return values


def _bulk_rows(session: Session, tracked: TrackedModel, where: Any) -> dict[str, dict[str, Any]]:
    keys = _key_columns(tracked)
    statement = select(*keys, *_synced_columns(tracked))
    if where is not None:
        statement = statement.where(where)
    with session.no_autoflush:
        rows = session.execute(statement).all()
    return {_row_key(tracked, row): _as_dict(tracked, row, len(keys)) for row in rows}


def _rows_by_key(session: Session, tracked: TrackedModel, keys: Iterable[str]) -> dict[str, dict[str, Any]]:
    key_columns = _key_columns(tracked)
    wanted = list(keys)
    found: dict[str, dict[str, Any]] = {}
    for start in range(0, len(wanted), 500):
        chunk = wanted[start : start + 500]
        if tracked is ALBUM_ITEM:
            condition = tuple_(*key_columns).in_([tuple(key.split(":", 1)) for key in chunk])
        else:
            condition = key_columns[0].in_(chunk)
        statement = select(*key_columns, *_synced_columns(tracked)).where(condition)
        with session.no_autoflush:
            for row in session.execute(statement).all():
                found[_row_key(tracked, row)] = _as_dict(tracked, row, len(key_columns))
    return found


__all__ = [
    "SYNC_APPLY",
    "TRACKED_MODELS",
    "ChangeCapture",
    "configure_change_capture",
    "install_change_capture",
]
