from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text

from bento.adapters.search.sqlite_vec import CHUNKS_TABLE, unknown_peer_space_id, vec_table_name
from bento.adapters.sync.index_data import AssetIndexData
from bento.application.sync.asset_index import embedding_fields
from bento.application.sync.codec import encode_vector
from bento.infrastructure.db.engine import session_scope

from tests.integration.db.support import FixedClock, migrated_session_factory
from tests.integration.search.vector_support import MODES, add_assets, space, unit, vector_index

ACTIVE = space("model-a", 3)
FOREIGN = space("model-b", 3)


def _chunk_spaces(factory: object, asset_id: str) -> list[str]:
    with session_scope(factory) as session:  # type: ignore[arg-type]
        return sorted(
            str(value)
            for value in session.execute(
                text(f"SELECT DISTINCT space_id FROM {CHUNKS_TABLE} WHERE asset_id = :asset_id"), {"asset_id": asset_id}
            ).scalars()
        )


def _table_exists(factory: object, name: str) -> bool:
    with session_scope(factory) as session:  # type: ignore[arg-type]
        return session.execute(text("SELECT 1 FROM sqlite_master WHERE name = :name"), {"name": name}).scalar() is not None


@pytest.mark.parametrize("use_sqlite_vec", MODES)
def test_peer_vectors_of_the_active_space_are_indexed_and_others_only_stored(tmp_path: Path, use_sqlite_vec: bool) -> None:
    factory = migrated_session_factory(tmp_path)
    vectors = vector_index(factory, sqlite_vec=use_sqlite_vec)
    data = AssetIndexData(factory, FixedClock(), vector_dimensions=3)
    query = unit(1.0, 0.0, 0.0)

    async def scenario() -> None:
        await add_assets(factory, "asset_same", "asset_foreign")
        await vectors.register_space(ACTIVE)
        await vectors.activate_space(ACTIVE.id)

        await data.write("asset_same", embedding_fields(provider="managed", dimensions=3, vector=query, space=ACTIVE.id))
        await data.write(
            "asset_foreign", embedding_fields(provider="managed", dimensions=3, vector=query, space=FOREIGN.id)
        )

        hits = await vectors.search_vectors(query, limit=10)
        assert [hit.asset_id for hit in hits] == ["asset_same"]
        assert _chunk_spaces(factory, "asset_foreign") == [FOREIGN.id]  # stored, not searched
        if use_sqlite_vec:
            assert _table_exists(factory, vec_table_name(ACTIVE.id))
            assert not _table_exists(factory, vec_table_name(FOREIGN.id))

        # Switching to the peer's space later makes its stored vectors searchable.
        await vectors.register_space(FOREIGN)
        await vectors.activate_space(FOREIGN.id)
        assert [hit.asset_id for hit in await vectors.search_vectors(query, limit=10)] == ["asset_foreign"]

    asyncio.run(scenario())


def test_old_peers_without_space_are_stored_as_an_unknown_space(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    vectors = vector_index(factory, sqlite_vec=False)
    data = AssetIndexData(factory, FixedClock(), vector_dimensions=3, legacy_provider="mock")
    query = unit(1.0, 0.0, 0.0)

    async def scenario() -> None:
        await add_assets(factory, "asset_old_peer")
        old_op = {"embedding": {"provider": "mock", "dimensions": 3, "vector_b64_f32": encode_vector(query)}}

        await data.write("asset_old_peer", old_op)

        assert _chunk_spaces(factory, "asset_old_peer") == [unknown_peer_space_id("mock", 3)]
        assert await vectors.search_vectors(query, limit=10, provider="mock") == ()
        assert await vectors.search_vectors(query, limit=10) == ()
        # The read-back does not invent a space for it.
        with session_scope(factory) as session:
            embedding = data.read(session, ["asset_old_peer"])["asset_old_peer"]["embedding"]
        assert "space" not in embedding

    asyncio.run(scenario())


def test_without_a_managed_space_the_legacy_provider_space_is_the_active_one(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    vectors = vector_index(factory, sqlite_vec=False)
    data = AssetIndexData(factory, FixedClock(), vector_dimensions=3, legacy_provider="mock")
    query = unit(0.0, 1.0, 0.0)

    async def scenario() -> None:
        await add_assets(factory, "asset_mock", "asset_other")
        assert await data.local_active_space_id() == "legacy:mock/3"

        await data.write("asset_mock", embedding_fields(provider="mock", dimensions=3, vector=query))
        await data.write("asset_other", embedding_fields(provider="other", dimensions=3, vector=query))

        hits = await vectors.search_vectors(query, limit=10, provider="mock")
        assert [hit.asset_id for hit in hits] == ["asset_mock"]
        assert _chunk_spaces(factory, "asset_other") == ["legacy:other/3"]

        # No legacy provider and no managed space: nothing is the active space, everything is stored only.
        bare = AssetIndexData(factory, FixedClock())
        assert await bare.local_active_space_id() is None

    asyncio.run(scenario())


def test_read_back_publishes_the_active_space_with_every_chunk(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    vectors = vector_index(factory, sqlite_vec=False)
    data = AssetIndexData(factory, FixedClock(), vector_dimensions=3)
    chunks = [unit(1.0, 0.0, 0.0), unit(0.0, 1.0, 0.0)]

    async def scenario() -> None:
        await add_assets(factory, "asset_1")
        await vectors.register_space(ACTIVE)
        await vectors.activate_space(ACTIVE.id)
        await data.write(
            "asset_1",
            embedding_fields(provider="managed", dimensions=3, vector=chunks[0], space=FOREIGN.id),
        )
        await data.write(
            "asset_1",
            embedding_fields(
                provider="managed", dimensions=3, vector=chunks[0], space=ACTIVE.id, chunks=chunks, pages=[1, 2]
            ),
        )

        with session_scope(factory) as session:
            assert data.indexed_asset_ids(session) == ["asset_1"]
            embedding = data.read(session, ["asset_1"])["asset_1"]["embedding"]

        assert embedding["space"] == ACTIVE.id
        assert embedding["vector_b64_f32"] == encode_vector(chunks[0])
        assert [(item["chunk_no"], item["page"], item["vector_b64_f32"]) for item in embedding["chunks"]] == [
            (0, 1, encode_vector(chunks[0])),
            (1, 2, encode_vector(chunks[1])),
        ]

        # A cleared embedding removes the asset's vectors from every space.
        await data.write("asset_1", {"embedding": None})
        assert _chunk_spaces(factory, "asset_1") == []

    asyncio.run(scenario())


def test_malformed_synced_vectors_are_skipped(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    data = AssetIndexData(factory, FixedClock(), vector_dimensions=3)

    async def scenario() -> None:
        await add_assets(factory, "asset_1")
        await data.write("asset_1", {"embedding": {"provider": "mock", "dimensions": 3, "vector_b64_f32": "AAAA"}})
        await data.write("asset_1", {"embedding": {"provider": "mock"}})
        assert _chunk_spaces(factory, "asset_1") == []

    asyncio.run(scenario())
