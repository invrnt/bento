"""The indexing service and the SQLite vector store agree on one contract (`ChunkVectorIndexPort`), and removed
spaces are retired with their vectors."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

import pytest
from sqlalchemy import text

from bento.adapters.manifest import SQLiteManifestJournal
from bento.adapters.media import SQLiteBlobRefCatalog
from bento.adapters.repositories import SQLiteAssetRepository
from bento.adapters.search.sqlite_vec import CHUNKS_TABLE
from bento.application.indexing.embedding import ChunkVector, ChunkVectorIndexPort, EmbeddingIndexingService
from bento.application.smart_search.reembed import EmbeddingSpaceState
from bento.domain.smart_search import EmbeddingSpace
from bento.infrastructure.db.engine import session_scope
from tests.integration.db.support import FixedClock, migrated_session_factory
from tests.integration.search.vector_support import MODES, add_assets, record, space, unit, vector_index

SPACE = space("model-a", 3)
OTHER = space("model-b", 3)


class ThreeDimProvider:
    """A smart search provider in `SPACE`: chunk `n` gets a distinct unit vector."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def space(self) -> EmbeddingSpace:
        return SPACE

    async def is_enabled(self) -> bool:
        return True

    async def embed_documents(self, texts: Sequence[str], *, title: str | None = None) -> tuple[tuple[float, ...], ...]:
        del title
        start = self.calls
        self.calls += len(texts)
        return tuple(unit(*(1.0 if axis == (start + offset) % 3 else 0.1 for axis in range(3))) for offset in range(len(texts)))


class OneText:
    def __init__(self, value: str) -> None:
        self._value = value

    async def text_for_asset(self, asset_id: str) -> str | None:
        del asset_id
        return self._value


class NoResolver:
    def resolve(self, blob_ref: object) -> Path:
        raise AssertionError("smart search providers read indexed text, not originals")


def _rows(factory: object, space_id: str) -> list[tuple[str, int, int | None]]:
    with session_scope(factory) as session:  # type: ignore[arg-type]
        return [
            (str(asset_id), int(chunk_no), page)
            for asset_id, chunk_no, page in session.execute(
                text(f"SELECT asset_id, chunk_no, page FROM {CHUNKS_TABLE} WHERE space_id = :space ORDER BY asset_id, chunk_no"),
                {"space": space_id},
            )
        ]


@pytest.mark.parametrize("use_sqlite_vec", MODES)
def test_indexing_service_writes_chunks_through_the_sqlite_store(tmp_path: Path, use_sqlite_vec: bool) -> None:
    factory = migrated_session_factory(tmp_path)
    index = vector_index(factory, sqlite_vec=use_sqlite_vec)
    clock = FixedClock()

    async def scenario() -> None:
        await add_assets(factory, "asset_long")
        assert isinstance(index, ChunkVectorIndexPort)
        service = EmbeddingIndexingService(
            assets=SQLiteAssetRepository(factory),
            blob_refs=SQLiteBlobRefCatalog(factory, clock),
            resolver=NoResolver(),  # type: ignore[arg-type]
            provider=ThreeDimProvider(),
            index=index,
            manifest=SQLiteManifestJournal(factory, clock, tmp_path / "journal"),
            clock=clock,
            text_catalog=OneText(" ".join(f"Frase número {n} sobre la factura de la luz." for n in range(400))),
            chunk_tokens=128,
        )

        indexed = await service.process_asset_embedding("asset_long")

        assert indexed is not None and indexed.dimensions == 3
        rows = _rows(factory, SPACE.id)
        assert len(rows) > 1
        assert [chunk_no for _, chunk_no, _ in rows] == list(range(len(rows)))
        hits = await index.search_vectors(unit(1.0, 0.1, 0.1), limit=5, space_id=SPACE.id)
        assert [hit.asset_id for hit in hits] == ["asset_long"]

    asyncio.run(scenario())


def test_chunk_vectors_keep_their_pages_and_are_stored_in_chunk_order(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    index = vector_index(factory, sqlite_vec=False)

    async def scenario() -> None:
        await add_assets(factory, "asset_pages")
        chunks = [
            ChunkVector(chunk_no=1, page=2, vector=unit(0.0, 1.0, 0.0)),
            ChunkVector(chunk_no=0, page=1, vector=unit(1.0, 0.0, 0.0)),
        ]

        await index.index_chunk_vectors(SPACE.id, record("asset_pages", 3), chunks)

        assert _rows(factory, SPACE.id) == [("asset_pages", 0, 1), ("asset_pages", 1, 2)]
        best = await index.search_vectors(unit(0.0, 1.0, 0.0), limit=1, space_id=SPACE.id)
        assert best[0].chunk_no == 1

    asyncio.run(scenario())


def test_retire_space_drops_its_vectors_and_keeps_other_spaces(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    index = vector_index(factory, sqlite_vec=False)

    async def scenario() -> None:
        await add_assets(factory, "asset_1")
        await index.register_space(SPACE)
        await index.register_space(OTHER)
        await index.activate_space(SPACE.id)
        vector = unit(1.0, 0.0, 0.0)
        await index.index_embedding_vector(record("asset_1", 3), vector, space_id=SPACE.id)
        await index.index_embedding_vector(record("asset_1", 3), vector, space_id=OTHER.id)
        assert await index.registered_space_ids() == (SPACE.id, OTHER.id)

        await index.retire_space(SPACE.id)

        assert _rows(factory, SPACE.id) == []
        assert _rows(factory, OTHER.id) == [("asset_1", 0, None)]
        assert await index.space_state(SPACE.id) is EmbeddingSpaceState.RETIRED
        assert await index.active_space_id() is None
        assert await index.registered_space_ids() == (OTHER.id,)
        assert await index.registered_space_ids(include_retired=True) == (SPACE.id, OTHER.id)
        # A later activation brings it back as `building`.
        await index.register_space(SPACE)
        assert await index.space_state(SPACE.id) is EmbeddingSpaceState.BUILDING

    asyncio.run(scenario())
