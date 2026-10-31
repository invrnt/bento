"""`SQLiteSyncStateStore` is the one `sync_state` key-value adapter (sync engine and `VaultStatePort`)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from bento.adapters.sync.store import SQLiteSyncStateStore
from bento.application.vault import VaultStatePort
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import SyncStateModel
from tests.integration.db.support import NOW, FixedClock, migrated_session_factory


def test_values_round_trip_with_the_injected_clock(tmp_path: Path) -> None:
    async def scenario() -> None:
        factory = migrated_session_factory(tmp_path)
        clock = FixedClock()
        state: VaultStatePort = SQLiteSyncStateStore(factory, now=clock.now)

        assert await state.get_value("vault.layout") is None
        await state.set_value("vault.layout", "first")
        await state.set_value("vault.layout", "second")
        assert await state.get_value("vault.layout") == "second"
        with session_scope(factory) as session:
            row = session.get(SyncStateModel, "vault.layout")
            assert row is not None and row.updated_at.replace(tzinfo=NOW.tzinfo) == NOW

        await state.delete_value("vault.layout")
        await state.delete_value("vault.layout")  # deleting a missing key is a no-op
        assert await state.get_value("vault.layout") is None

    asyncio.run(scenario())
