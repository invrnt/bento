from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text

from bento.adapters.search.sqlite_vec import (
    CHUNKS_TABLE,
    SQLiteVecSearchIndex,
    embedding_row_id,
    pack_vector,
    similarity_from_distance,
    vec_table_name,
)
from bento.application.smart_search.reembed import EmbeddingSpaceState
from bento.infrastructure.db.engine import session_scope

from tests.integration.db.support import NOW, FixedClock, migrated_session_factory
from tests.integration.search.vector_support import MODES, add_assets, record, seeded_unit, space, unit, vector_index

SPACE_A = space("model-a", 3)
SPACE_B = space("model-b", 3)


def _table_exists(factory: object, name: str) -> bool:
    with session_scope(factory) as session:  # type: ignore[arg-type]
        return (
            session.execute(text("SELECT 1 FROM sqlite_master WHERE name = :name"), {"name": name}).scalar() is not None
        )


def _count(factory: object, statement: str, **params: object) -> int:
    with session_scope(factory) as session:  # type: ignore[arg-type]
        return int(session.execute(text(statement), params).scalar() or 0)


@pytest.mark.parametrize("use_sqlite_vec", MODES)
def test_vectors_of_space_a_are_never_returned_for_space_b(tmp_path: Path, use_sqlite_vec: bool) -> None:
    factory = migrated_session_factory(tmp_path)
    index = vector_index(factory, sqlite_vec=use_sqlite_vec)

    async def scenario() -> None:
        await add_assets(factory, "asset_a", "asset_b")
        await index.register_space(SPACE_A)
        await index.register_space(SPACE_B)
        same = unit(1.0, 0.0, 0.0)
        await index.index_embedding_vector(record("asset_a", 3), same, space_id=SPACE_A.id)
        await index.index_embedding_vector(record("asset_b", 3), same, space_id=SPACE_B.id)

        in_a = await index.search_vectors(same, limit=10, space_id=SPACE_A.id)
        in_b = await index.search_vectors(same, limit=10, space_id=SPACE_B.id)

        assert [hit.asset_id for hit in in_a] == ["asset_a"]
        assert [hit.asset_id for hit in in_b] == ["asset_b"]
        assert in_a[0].space_id == SPACE_A.id
        assert in_a[0].score == pytest.approx(1.0, abs=1e-6)

        # The active space is the default for callers that name none.
        await index.activate_space(SPACE_B.id)
        assert [hit.asset_id for hit in await index.search_vectors(same, limit=10)] == ["asset_b"]

    asyncio.run(scenario())


@pytest.mark.parametrize("use_sqlite_vec", MODES)
def test_an_assets_score_is_its_best_chunk(tmp_path: Path, use_sqlite_vec: bool) -> None:
    factory = migrated_session_factory(tmp_path)
    index = vector_index(factory, sqlite_vec=use_sqlite_vec)

    async def scenario() -> None:
        await add_assets(factory, "asset_long", "asset_short")
        await index.register_space(SPACE_A)
        query = unit(1.0, 0.0, 0.0)
        await index.index_chunks(
            record("asset_long", 3),
            [unit(0.0, 1.0, 0.0), unit(0.0, 0.0, 1.0), unit(0.95, 0.05, 0.0)],
            space_id=SPACE_A.id,
            pages=[1, 2, 3],
        )
        await index.index_chunks(record("asset_short", 3), [unit(0.7, 0.7, 0.0)], space_id=SPACE_A.id)

        hits = await index.search_vectors(query, limit=10, space_id=SPACE_A.id)

        assert [hit.asset_id for hit in hits] == ["asset_long", "asset_short"]
        assert hits[0].chunk_no == 2
        assert hits[0].score == pytest.approx(unit(0.95, 0.05, 0.0)[0], abs=1e-5)
        assert hits[0].score == pytest.approx(similarity_from_distance(hits[0].distance))
        assert hits[0].embedding_id == embedding_row_id(SPACE_A.id, "asset_long")
        assert hits[0].provider == "managed"
        # Re-indexing replaces the chunks of that space.
        await index.index_chunks(record("asset_long", 3), [unit(0.0, 1.0, 0.0)], space_id=SPACE_A.id)
        hits = await index.search_vectors(query, limit=10, space_id=SPACE_A.id)
        assert [hit.asset_id for hit in hits] == ["asset_short", "asset_long"]
        assert _count(factory, f"SELECT COUNT(*) FROM {CHUNKS_TABLE} WHERE asset_id = 'asset_long'") == 1

    asyncio.run(scenario())


def test_sqlite_vec_and_the_fallback_return_the_same_top_k(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    native = vector_index(factory, sqlite_vec=True)
    fallback = vector_index(factory, sqlite_vec=False)
    target = space("model-a", 16)
    asset_ids = [f"asset_{number:02d}" for number in range(40)]

    async def scenario() -> None:
        await add_assets(factory, *asset_ids)
        await native.register_space(target)
        for number, asset_id in enumerate(asset_ids):
            chunks = [seeded_unit(f"{asset_id}:{chunk}", 16) for chunk in range(1 + number % 4)]
            await native.index_chunks(record(asset_id, 16), chunks, space_id=target.id)

        for query_seed in ("q1", "q2", "q3", "q4"):
            query = seeded_unit(query_seed, 16)
            fast = await native.search_vectors(query, limit=10, space_id=target.id)
            exact = await fallback.search_vectors(query, limit=10, space_id=target.id)
            assert [hit.asset_id for hit in fast] == [hit.asset_id for hit in exact]
            assert [hit.chunk_no for hit in fast] == [hit.chunk_no for hit in exact]
            for left, right in zip(fast, exact, strict=True):
                assert left.score == pytest.approx(right.score, abs=1e-4)

        assert _table_exists(factory, vec_table_name(target.id))

    asyncio.run(scenario())


def test_a_stale_vec_table_is_rebuilt_from_the_chunks(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    native = vector_index(factory, sqlite_vec=True)
    fallback = vector_index(factory, sqlite_vec=False)

    async def scenario() -> None:
        await add_assets(factory, "asset_1", "asset_2")
        await native.register_space(SPACE_A)
        await native.index_embedding_vector(record("asset_1", 3), unit(0.0, 1.0, 0.0), space_id=SPACE_A.id)
        # A write that bypassed the search table (another process, an older build): only the chunk rows changed.
        with session_scope(factory) as session:
            session.execute(text(f"DELETE FROM {CHUNKS_TABLE} WHERE asset_id = 'asset_1'"))
        await fallback.index_embedding_vector(record("asset_2", 3), unit(1.0, 0.0, 0.0), space_id=SPACE_A.id)

        restarted = SQLiteVecSearchIndex(factory, FixedClock())
        hits = await restarted.search_vectors(unit(1.0, 0.0, 0.0), limit=10, space_id=SPACE_A.id)

        assert [hit.asset_id for hit in hits] == ["asset_2"]

    asyncio.run(scenario())


@pytest.mark.parametrize("use_sqlite_vec", MODES)
def test_the_flip_retires_the_old_space_and_drops_its_rows(tmp_path: Path, use_sqlite_vec: bool) -> None:
    factory = migrated_session_factory(tmp_path)
    index = vector_index(factory, sqlite_vec=use_sqlite_vec)

    async def scenario() -> None:
        await add_assets(factory, "asset_1")
        await index.register_space(SPACE_A)
        assert await index.activate_space(SPACE_A.id) == ()
        await index.index_embedding_vector(record("asset_1", 3), unit(1.0, 0.0, 0.0), space_id=SPACE_A.id)
        await index.search_vectors(unit(1.0, 0.0, 0.0), limit=1, space_id=SPACE_A.id)
        await index.register_space(SPACE_B)
        await index.index_embedding_vector(record("asset_1", 3), unit(0.0, 1.0, 0.0), space_id=SPACE_B.id)
        assert await index.active_space_id() == SPACE_A.id

        dropped = await index.activate_space(SPACE_B.id)

        assert dropped == (SPACE_A.id,)
        assert await index.active_space_id() == SPACE_B.id
        assert await index.space_state(SPACE_A.id) is EmbeddingSpaceState.RETIRED
        assert await index.search_vectors(unit(1.0, 0.0, 0.0), limit=5, space_id=SPACE_A.id) == ()
        assert _count(factory, f"SELECT COUNT(*) FROM {CHUNKS_TABLE} WHERE space_id = :s", s=SPACE_A.id) == 0
        assert _count(factory, "SELECT COUNT(*) FROM asset_embeddings WHERE space_id = :s", s=SPACE_A.id) == 0
        assert _count(factory, "SELECT COUNT(*) FROM embedding_spaces WHERE state = 'active'") == 1
        assert not _table_exists(factory, vec_table_name(SPACE_A.id))
        assert [hit.asset_id for hit in await index.search_vectors(unit(0.0, 1.0, 0.0), limit=5)] == ["asset_1"]
        # Re-registering a retired space starts a new build; activating the active space is a no-op.
        await index.register_space(SPACE_A)
        assert await index.space_state(SPACE_A.id) is EmbeddingSpaceState.BUILDING
        assert await index.activate_space(SPACE_B.id) == ()

    asyncio.run(scenario())


def test_activating_a_managed_space_drops_legacy_vectors(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    index = SQLiteVecSearchIndex(factory, FixedClock(), dimensions=3, prefer_sqlite_vec=False)

    async def scenario() -> None:
        await add_assets(factory, "asset_1")
        await index.index_embedding_vector(record("asset_1", 3, provider="mock"), unit(1.0, 0.0, 0.0))
        assert [hit.asset_id for hit in await index.search_vectors(unit(1.0, 0.0, 0.0), limit=1, provider="mock")] == ["asset_1"]
        await index.register_space(SPACE_A)

        dropped = await index.activate_space(SPACE_A.id)

        assert dropped == ("legacy:mock/3",)
        assert await index.search_vectors(unit(1.0, 0.0, 0.0), limit=1, provider="mock") == ()

    asyncio.run(scenario())


def test_legacy_vectors_move_into_their_legacy_space(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)

    async def scenario() -> None:
        await add_assets(factory, "asset_old")
        legacy = unit(0.0, 0.0, 1.0)
        with session_scope(factory) as session:
            session.execute(
                text("CREATE TABLE asset_embedding_vectors_fallback (embedding_id TEXT PRIMARY KEY, vector BLOB NOT NULL)")
            )
            session.execute(
                text(
                    """
                    INSERT INTO asset_embeddings (id, asset_id, provider, vector_ref, dimensions, created_at, space_id)
                    VALUES ('emb_old', 'asset_old', 'mock', 'mock:old', 3, :created_at, 'legacy:mock/3')
                    """
                ),
                {"created_at": NOW.isoformat(sep=" ")},
            )
            session.execute(
                text("INSERT INTO asset_embedding_vectors_fallback (embedding_id, vector) VALUES ('emb_old', :vector)"),
                {"vector": pack_vector(legacy)},
            )

        index = SQLiteVecSearchIndex(factory, FixedClock(), dimensions=3, prefer_sqlite_vec=False)
        hits = await index.search_vectors(legacy, limit=5, provider="mock")

        assert [hit.asset_id for hit in hits] == ["asset_old"]
        assert hits[0].space_id == "legacy:mock/3"
        assert not _table_exists(factory, "asset_embedding_vectors_fallback")

    asyncio.run(scenario())


@pytest.mark.parametrize("use_sqlite_vec", MODES)
def test_remove_asset_clears_every_space(tmp_path: Path, use_sqlite_vec: bool) -> None:
    factory = migrated_session_factory(tmp_path)
    index = vector_index(factory, sqlite_vec=use_sqlite_vec)

    async def scenario() -> None:
        await add_assets(factory, "asset_1", "asset_2")
        for target in (SPACE_A, SPACE_B):
            await index.register_space(target)
            await index.index_embedding_vector(record("asset_1", 3), unit(1.0, 0.0, 0.0), space_id=target.id)
            await index.index_embedding_vector(record("asset_2", 3), unit(0.0, 1.0, 0.0), space_id=target.id)

        await index.remove_asset("asset_1", space_id=SPACE_B.id)
        assert [hit.asset_id for hit in await index.search_vectors(unit(1.0, 0.0, 0.0), limit=5, space_id=SPACE_B.id)] == ["asset_2"]
        assert await index.assets_with_vectors(SPACE_A.id, ["asset_1", "asset_2"]) == frozenset({"asset_1", "asset_2"})

        await index.remove_asset("asset_1")

        assert await index.assets_with_vectors(SPACE_A.id, ["asset_1", "asset_2"]) == frozenset({"asset_2"})
        assert await index.count_assets(SPACE_A.id) == 1
        assert _count(factory, "SELECT COUNT(*) FROM asset_embeddings WHERE asset_id = 'asset_1'") == 0
        await index.drop_space(SPACE_A.id)
        assert await index.count_assets(SPACE_A.id) == 0
        assert not _table_exists(factory, vec_table_name(SPACE_A.id))

    asyncio.run(scenario())


def test_vectors_must_match_the_space_dimensions(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    index = SQLiteVecSearchIndex(factory, FixedClock(), prefer_sqlite_vec=False)

    async def scenario() -> None:
        await add_assets(factory, "asset_1")
        with pytest.raises(ValueError):
            await index.index_embedding_vector(record("asset_1", 3), unit(1.0, 0.0), space_id=SPACE_A.id)
        with pytest.raises(ValueError):
            await index.index_embedding_vector(record("asset_1", 4), unit(1.0, 0.0, 0.0, 0.0), space_id=SPACE_A.id)
        with pytest.raises(ValueError):
            await index.search_vectors(unit(1.0, 0.0), limit=1, space_id=SPACE_A.id)

    asyncio.run(scenario())
