"""Worker composition of the sync loop, the `asset_index` recorder, and the `sync_snapshot` job handler."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.devices import SQLiteDeviceRepository
from bento.adapters.sync import SQLiteHlcSource, SQLiteSyncAdapters, SQLiteSyncOutbox, SQLiteSyncStateStore
from bento.application.sync import AssetIndexRecorder, SyncEngine, SyncLoop
from bento.application.sync.state import SNAPSHOT_REQUESTED_AT, format_timestamp
from bento.domain.errors import DomainError
from bento.domain.jobs import Job
from bento.infrastructure.db.clock import SystemClock
from bento.infrastructure.db.engine import create_app_session_factory
from bento.infrastructure.runtime import get_telegram_runtime
from bento.infrastructure.settings import Settings

LOGGER = logging.getLogger("bento.worker.sync")


def create_sync_loop(settings: Settings) -> SyncLoop | None:
    """None for local storage, or when this build cannot reach Telegram yet."""
    if settings.storage_backend == "local":
        return None
    from bento.infrastructure import services

    try:
        key_store = services.get_key_store(settings)
        vault = services.get_vault_session(settings)
        crypto = services.get_vault_crypto()
        runtime = get_telegram_runtime(settings, key_store)
    except (NotImplementedError, DomainError) as exc:
        LOGGER.warning("Sync loop disabled: %s", exc)
        return None
    if runtime is None:
        return None
    clock = SystemClock()
    session_factory = create_app_session_factory(settings)
    adapters = SQLiteSyncAdapters.create(session_factory, clock, vector_dimensions=settings.embedding_dimensions)
    engine = SyncEngine(
        vault=vault,
        transport=runtime.transport,
        crypto=crypto,
        outbox=adapters.outbox,
        state=adapters.state,
        applier=adapters.applier,
        snapshots=adapters.snapshots,
        hlc=adapters.hlc,
        holds=adapters.holds,
        publisher=adapters.publisher,
        devices=SQLiteDeviceRepository(session_factory),
        clock=clock,
    )
    return SyncLoop(engine=engine, vault=vault, transport=runtime.transport, state=adapters.state, clock=clock)


def start_sync_loop(settings: Settings, stop_event: asyncio.Event) -> asyncio.Task[None] | None:
    sync_loop = create_sync_loop(settings)
    if sync_loop is None:
        return None
    LOGGER.info("Sync loop started")
    return asyncio.create_task(sync_loop.run(stop_event), name="bento-sync-loop")


async def stop_sync_loop(task: asyncio.Task[None] | None, *, timeout_seconds: float = 10.0) -> None:
    if task is None:
        return
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
    except TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_asset_index_recorder(settings: Settings, session_factory: sessionmaker[Session]) -> AssetIndexRecorder | None:
    if settings.storage_backend == "local":
        return None
    return AssetIndexRecorder(
        outbox=SQLiteSyncOutbox(session_factory),
        hlc=SQLiteHlcSource(session_factory),
        state=SQLiteSyncStateStore(session_factory),
    )


class SyncSnapshotJobHandler:
    """`sync_snapshot` jobs ask the sync loop for a snapshot on its next caught-up cycle."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._state = SQLiteSyncStateStore(session_factory)
        self._clock = SystemClock()

    async def __call__(self, job: Job) -> None:
        del job
        await self._state.set_value(SNAPSHOT_REQUESTED_AT, format_timestamp(self._clock.now()))
