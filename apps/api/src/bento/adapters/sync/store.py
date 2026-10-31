"""SQLite adapters for sync state, the HLC source, the outbox, and the hold-rule asset lookup."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.sync.mapping import TELEGRAM_BACKEND
from bento.adapters.sync.records import (
    HlcCursor,
    Now,
    NowMs,
    OpWriter,
    load_capture_config,
    put_state,
    system_now,
    system_now_ms,
)
from bento.application.sync.ports import AssetHoldState, OutboxBacklog
from bento.domain.errors import ValidationFailedError
from bento.domain.storage import BlobKind
from bento.domain.sync import Hlc, SyncEntity, SyncOperation, SyncOpKind
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import (
    AssetModel,
    BlobRefModel,
    SyncAppliedBatchModel,
    SyncOutboxModel,
    SyncStateModel,
)
from bento.ports.sync import OutboxEntry

_CHUNK = 500


class SQLiteSyncStateStore:
    """`SyncStateStorePort` over `sync_state` and `sync_applied_batches`."""

    def __init__(self, session_factory: sessionmaker[Session], *, now: Now = system_now) -> None:
        self._session_factory = session_factory
        self._now = now

    async def get_value(self, key: str) -> str | None:
        with session_scope(self._session_factory) as session:
            row = session.get(SyncStateModel, key)
            return row.value if row is not None else None

    async def set_value(self, key: str, value: str) -> None:
        with session_scope(self._session_factory) as session:
            put_state(session, key, value, self._now())

    async def delete_value(self, key: str) -> None:
        with session_scope(self._session_factory) as session:
            session.execute(delete(SyncStateModel).where(SyncStateModel.key == key))

    async def is_batch_applied(self, batch_id: str) -> bool:
        with session_scope(self._session_factory) as session:
            return session.get(SyncAppliedBatchModel, batch_id) is not None


class SQLiteHlcSource:
    """`HlcSourcePort`: the device HLC persisted in `sync_state["last_hlc"]`, shared by API and worker."""

    def __init__(
        self, session_factory: sessionmaker[Session], *, now_ms: NowMs = system_now_ms, now: Now = system_now
    ) -> None:
        self._session_factory = session_factory
        self._now_ms = now_ms
        self._now = now

    async def next(self) -> str:
        with session_scope(self._session_factory) as session:
            return self._cursor(session).tick()

    async def observe(self, remote_hlc: str) -> None:
        Hlc.parse(remote_hlc)
        with session_scope(self._session_factory) as session:
            self._cursor(session).observe(remote_hlc)

    def _cursor(self, session: Session) -> HlcCursor:
        config = load_capture_config(session)
        if config is None:
            raise ValidationFailedError("Sync is not attached to a vault on this device")
        return HlcCursor(session, config.device_id, now_ms=self._now_ms, now=self._now)


class SQLiteSyncOutbox:
    """`SyncOutboxStorePort` over `sync_outbox`."""

    def __init__(
        self, session_factory: sessionmaker[Session], *, now_ms: NowMs = system_now_ms, now: Now = system_now
    ) -> None:
        self._session_factory = session_factory
        self._now_ms = now_ms
        self._now = now

    async def pending(self, *, limit: int = 256) -> tuple[OutboxEntry, ...]:
        return await self.page(after_seq=0, limit=limit)

    async def page(self, *, after_seq: int = 0, limit: int = 500) -> tuple[OutboxEntry, ...]:
        statement = (
            select(SyncOutboxModel)
            .where(SyncOutboxModel.seq > after_seq)
            .order_by(SyncOutboxModel.seq)
            .limit(max(1, limit))
        )
        with session_scope(self._session_factory) as session:
            return tuple(_entry(row) for row in session.scalars(statement))

    async def remove(self, seqs: tuple[int, ...]) -> None:
        if not seqs:
            return
        with session_scope(self._session_factory) as session:
            for start in range(0, len(seqs), _CHUNK):
                session.execute(delete(SyncOutboxModel).where(SyncOutboxModel.seq.in_(seqs[start : start + _CHUNK])))

    async def stats(self) -> tuple[int, int]:
        backlog = await self.backlog()
        return backlog.count, backlog.oldest_age_ms

    async def backlog(self, *, after_seq: int = 0) -> OutboxBacklog:
        statement = select(
            func.count(SyncOutboxModel.seq),
            func.min(SyncOutboxModel.created_at),
            func.coalesce(func.sum(SyncOutboxModel.size_bytes), 0),
            func.coalesce(func.max(SyncOutboxModel.seq), 0),
        ).where(SyncOutboxModel.seq > after_seq)
        with session_scope(self._session_factory) as session:
            count, oldest, total, max_seq = session.execute(statement).one()
        age = 0
        if oldest is not None:
            oldest = oldest if oldest.tzinfo is not None else oldest.replace(tzinfo=UTC)
            age = max(0, int((self._now() - oldest).total_seconds() * 1000))
        return OutboxBacklog(count=int(count), oldest_age_ms=age, total_bytes=int(total), max_seq=int(max_seq))

    async def record(self, operation: SyncOperation) -> None:
        with session_scope(self._session_factory) as session:
            config = load_capture_config(session)
            if config is None:
                return
            if session.scalar(select(SyncOutboxModel.seq).where(SyncOutboxModel.op_id == operation.op_id)) is not None:
                return
            writer = OpWriter(session, config, now_ms=self._now_ms, now=self._now)
            writer.hlc.observe(operation.hlc)
            writer.write(operation)

    async def clear(self) -> None:
        with session_scope(self._session_factory) as session:
            session.execute(delete(SyncOutboxModel))


class SQLiteHoldState:
    """`HoldStatePort`: whether each asset exists and has an original stored in Telegram."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def asset_states(self, asset_ids: frozenset[str]) -> Mapping[str, AssetHoldState]:
        wanted = sorted(asset_ids)
        states = {asset_id: AssetHoldState.MISSING for asset_id in wanted}
        with session_scope(self._session_factory) as session:
            for start in range(0, len(wanted), _CHUNK):
                chunk = wanted[start : start + _CHUNK]
                for asset_id in session.scalars(select(AssetModel.id).where(AssetModel.id.in_(chunk))):
                    states[asset_id] = AssetHoldState.LOCAL
                remote = select(BlobRefModel.asset_id).where(
                    BlobRefModel.asset_id.in_(chunk),
                    BlobRefModel.kind == BlobKind.ORIGINAL.value,
                    BlobRefModel.backend == TELEGRAM_BACKEND,
                )
                for asset_id in session.scalars(remote):
                    if states.get(asset_id) == AssetHoldState.LOCAL:
                        states[asset_id] = AssetHoldState.REMOTE
        return states


def _entry(row: SyncOutboxModel) -> OutboxEntry:
    operation = SyncOperation(
        op_id=row.op_id,
        hlc=row.hlc,
        device_id=Hlc.parse(row.hlc).device_id,
        entity=SyncEntity(row.entity),
        entity_id=row.entity_id,
        kind=SyncOpKind(row.kind),
        fields=dict(row.fields_json or {}),
    )
    return OutboxEntry(seq=row.seq, operation=operation, size_bytes=row.size_bytes)
