"""`SQLiteSmartSearchStatusRepository` against the real `0009_smart_search` tables."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from bento.adapters.models.sqlite_status import SQLiteSmartSearchStatusRepository
from bento.application.smart_search.activation import InstallState, ModelInstallRecord
from bento.domain.smart_search import (
    SmartSearchErrorCode,
    SmartSearchEvent,
    SmartSearchEventKind,
    SmartSearchState,
    SmartSearchStatus,
    transition,
)
from tests.integration.db.support import FixedClock, migrated_session_factory

SPACE = "embeddinggemma-2-q8_0@6ea3e3a309d12a4779cfda98b8c19800d2d5da71/512"


def repository(tmp_path: Path) -> SQLiteSmartSearchStatusRepository:
    return SQLiteSmartSearchStatusRepository(migrated_session_factory(tmp_path), FixedClock())


def test_status_round_trips_and_writes_are_compare_and_set(tmp_path: Path) -> None:
    repo = repository(tmp_path)

    async def scenario() -> None:
        off = await repo.load()
        assert off == SmartSearchStatus()

        downloading = transition(
            off, SmartSearchEvent(SmartSearchEventKind.ACTIVATE, space_id=SPACE, bytes_total=1000)
        )
        assert await repo.replace(off, downloading) is True
        assert await repo.load() == downloading

        # A second writer still holding `off` loses.
        assert await repo.replace(off, downloading) is False

        assert await repo.set_download_progress(SPACE, 400) is True
        assert await repo.set_download_progress("other@abc1234/512", 900) is False
        assert (await repo.load()).bytes_done == 400

        # Progress does not change what compare-and-set looks at.
        paused = transition(downloading, SmartSearchEvent(SmartSearchEventKind.PAUSE))
        assert await repo.replace(downloading, paused) is True
        assert await repo.set_download_progress(SPACE, 500) is True
        loaded = await repo.load()
        assert loaded.state is SmartSearchState.PAUSED
        assert loaded.bytes_done == 500

        resumed = transition(loaded, SmartSearchEvent(SmartSearchEventKind.RESUME))
        await repo.replace(loaded, resumed)
        lost = transition(resumed, SmartSearchEvent(SmartSearchEventKind.NETWORK_LOST))
        assert await repo.replace(resumed, lost) is True
        assert (await repo.load()).waiting_network is True

        failed = transition(lost, SmartSearchEvent(SmartSearchEventKind.FAIL, error_code=SmartSearchErrorCode.SPACE))
        assert await repo.replace(lost, failed) is True
        stored = await repo.load()
        assert stored.state is SmartSearchState.ERROR
        assert stored.error_code is SmartSearchErrorCode.SPACE
        assert stored.failed_step is SmartSearchState.DOWNLOADING
        assert stored.waiting_network is False
        assert await repo.set_download_progress(SPACE, 600) is False

    asyncio.run(scenario())


def test_index_progress_only_while_indexing(tmp_path: Path) -> None:
    repo = repository(tmp_path)

    async def scenario() -> None:
        off = await repo.load()
        indexing = replace(SmartSearchStatus(), state=SmartSearchState.INDEXING, space_id=SPACE)
        assert await repo.replace(off, indexing)

        assert await repo.set_index_progress(SPACE, 30, 20) is True
        loaded = await repo.load()
        assert (loaded.indexed_done, loaded.indexed_total) == (20, 20)
        assert await repo.set_index_progress("other@abc1234/512", 1, 2) is False

    asyncio.run(scenario())


def test_model_installs_upsert_list_and_delete(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    record = ModelInstallRecord(
        model_id="embeddinggemma-2-q8_0",
        revision="6ea3e3a309d12a4779cfda98b8c19800d2d5da71",
        file="embeddinggemma-2-Q8_0.gguf",
        bytes_total=309_855_456,
        bytes_done=0,
        sha256="2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135",
        state=InstallState.DOWNLOADING,
    )

    async def scenario() -> None:
        await repo.save_install(record)
        await repo.save_install(replace(record, bytes_done=1024, state=InstallState.UPDATE_DOWNLOADING))
        await repo.save_install(replace(record, revision="0123456789abcdef", state=InstallState.ERROR, error_code="checksum"))

        installs = await repo.installs()
        assert [(item.revision, item.state, item.bytes_done) for item in installs] == [
            ("0123456789abcdef", InstallState.ERROR, 0),
            ("6ea3e3a309d12a4779cfda98b8c19800d2d5da71", InstallState.UPDATE_DOWNLOADING, 1024),
        ]
        assert installs[0].error_code == "checksum"

        await repo.delete_installs("embeddinggemma-2-q8_0", "0123456789abcdef")
        assert len(await repo.installs()) == 1
        await repo.delete_installs("embeddinggemma-2-q8_0")
        assert await repo.installs() == ()

    asyncio.run(scenario())
