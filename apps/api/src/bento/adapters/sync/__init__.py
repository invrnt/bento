"""SQLite adapters of the sync engine (change capture, outbox, apply, snapshots)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.sync.apply import SQLiteSyncApplier
from bento.adapters.sync.capture import SYNC_APPLY, ChangeCapture, configure_change_capture, install_change_capture
from bento.adapters.sync.index_data import AssetIndexData
from bento.adapters.sync.records import Now, NowMs, system_now, system_now_ms
from bento.adapters.sync.snapshot_source import SQLiteFullStatePublisher, SQLiteSnapshotSource
from bento.adapters.sync.store import SQLiteHlcSource, SQLiteHoldState, SQLiteSyncOutbox, SQLiteSyncStateStore
from bento.ports.repositories import ClockPort


@dataclass(frozen=True, slots=True)
class SQLiteSyncAdapters:
    """Every SQLite-side sync adapter over one session factory."""

    state: SQLiteSyncStateStore
    outbox: SQLiteSyncOutbox
    hlc: SQLiteHlcSource
    holds: SQLiteHoldState
    applier: SQLiteSyncApplier
    snapshots: SQLiteSnapshotSource
    publisher: SQLiteFullStatePublisher
    index: AssetIndexData

    @classmethod
    def create(
        cls,
        session_factory: sessionmaker[Session],
        clock: ClockPort,
        *,
        vector_dimensions: int | None = None,
        now_ms: NowMs = system_now_ms,
        now: Now = system_now,
    ) -> SQLiteSyncAdapters:
        index = AssetIndexData(session_factory, clock, vector_dimensions=vector_dimensions)
        return cls(
            state=SQLiteSyncStateStore(session_factory, now=now),
            outbox=SQLiteSyncOutbox(session_factory, now_ms=now_ms, now=now),
            hlc=SQLiteHlcSource(session_factory, now_ms=now_ms, now=now),
            holds=SQLiteHoldState(session_factory),
            applier=SQLiteSyncApplier(session_factory, index=index, now_ms=now_ms, now=now),
            snapshots=SQLiteSnapshotSource(session_factory, index=index),
            publisher=SQLiteFullStatePublisher(session_factory, index=index, now_ms=now_ms, now=now),
            index=index,
        )


__all__ = [
    "SYNC_APPLY",
    "AssetIndexData",
    "ChangeCapture",
    "SQLiteFullStatePublisher",
    "SQLiteHlcSource",
    "SQLiteHoldState",
    "SQLiteSnapshotSource",
    "SQLiteSyncAdapters",
    "SQLiteSyncApplier",
    "SQLiteSyncOutbox",
    "SQLiteSyncStateStore",
    "configure_change_capture",
    "install_change_capture",
]
