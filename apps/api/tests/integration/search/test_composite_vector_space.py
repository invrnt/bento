from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from bento.adapters.repositories import SQLiteAssetRepository
from bento.adapters.search.composite import CompositeSearchIndex
from bento.adapters.search.sqlite_fts import SQLiteFTSSearchIndex
from bento.adapters.search.sqlite_vec import SQLiteVecSearchIndex
from bento.domain.assets import AssetKind
from bento.domain.search import MatchReason, SearchQuery
from bento.domain.smart_search import EmbeddingSpace, truncate_and_renormalize

from tests.integration.db.support import FixedClock, make_asset, migrated_session_factory
from tests.integration.search.vector_support import record, space, unit

QUERY_VECTOR = unit(1.0, 0.0, 0.0, 0.0)


@dataclass
class QueryProvider:
    """`EmbeddingProviderPort`'s query side, serving one space; `failure` simulates a missing runtime."""

    space: EmbeddingSpace
    vector: tuple[float, ...] = QUERY_VECTOR
    enabled: bool = True
    failure: Exception | None = None
    queries: list[str] = field(default_factory=list)

    async def is_enabled(self) -> bool:
        return self.enabled

    async def embed_query(self, text: str) -> tuple[float, ...]:
        self.queries.append(text)
        if self.failure is not None:
            raise self.failure
        return self.vector


def _search(factory: object, provider: object) -> tuple[CompositeSearchIndex, SQLiteVecSearchIndex]:
    clock = FixedClock()
    vectors = SQLiteVecSearchIndex(factory, clock, prefer_sqlite_vec=False)  # type: ignore[arg-type]
    search = CompositeSearchIndex(
        factory,  # type: ignore[arg-type]
        clock,
        text_index=SQLiteFTSSearchIndex(factory, clock),  # type: ignore[arg-type]
        vector_index=vectors,
        query_embedding_provider=provider,  # type: ignore[arg-type]
    )
    return search, vectors


async def _library(factory: object, search: CompositeSearchIndex) -> None:
    assets = SQLiteAssetRepository(factory)  # type: ignore[arg-type]
    playa = make_asset("asset_beach", filename="playa-atardecer.jpg", kind=AssetKind.IMAGE, sha256="1" * 64)
    receipt = make_asset("asset_receipt", filename="recibo-cafe.pdf", sha256="2" * 64)
    for asset in (playa, receipt):
        await assets.add(asset)
        await search.index_asset(asset)


def test_vector_hits_come_from_the_active_space_through_embed_query(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    active = space("model-a", 4)
    provider = QueryProvider(active)
    search, vectors = _search(factory, provider)

    async def scenario() -> None:
        await _library(factory, search)
        await vectors.register_space(active)
        await vectors.activate_space(active.id)
        await vectors.index_embedding_vector(record("asset_beach", 4), QUERY_VECTOR, space_id=active.id)

        results = await search.search(SearchQuery(text="olas oceano"))

        assert provider.queries == ["olas oceano"]
        assert [item.asset_id for item in results.items][:1] == ["asset_beach"]
        assert MatchReason.SEMANTIC in results.items[0].match_reasons

    asyncio.run(scenario())


def test_search_falls_back_to_text_when_the_runtime_is_missing(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    active = space("model-a", 4)
    provider = QueryProvider(active, failure=ConnectionRefusedError("embedder.json missing"))
    search, vectors = _search(factory, provider)

    async def scenario() -> None:
        await _library(factory, search)
        await vectors.register_space(active)
        await vectors.activate_space(active.id)
        await vectors.index_embedding_vector(record("asset_beach", 4), QUERY_VECTOR, space_id=active.id)

        results = await search.search(SearchQuery(text="recibo"))

        assert [item.asset_id for item in results.items] == ["asset_receipt"]
        assert all(MatchReason.SEMANTIC not in item.match_reasons for item in results.items)

        provider.failure = None
        provider.enabled = False
        disabled = await search.search(SearchQuery(text="recibo"))
        assert [item.asset_id for item in disabled.items] == ["asset_receipt"]

    asyncio.run(scenario())


def test_a_provider_serving_another_model_does_not_query_the_active_space(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    active = space("model-a", 4)
    building = space("model-b", 4, revision="b" * 40)
    provider = QueryProvider(building)
    search, vectors = _search(factory, provider)

    async def scenario() -> None:
        await _library(factory, search)
        await vectors.register_space(active)
        await vectors.activate_space(active.id)
        await vectors.register_space(building)
        await vectors.index_embedding_vector(record("asset_beach", 4), QUERY_VECTOR, space_id=active.id)
        await vectors.index_embedding_vector(record("asset_receipt", 4), QUERY_VECTOR, space_id=building.id)

        results = await search.search(SearchQuery(text="olas oceano"))

        # Neither the old space (other model) nor the space still being built answers: text search only.
        assert all(MatchReason.SEMANTIC not in item.match_reasons for item in results.items)

    asyncio.run(scenario())


def test_a_larger_space_of_the_same_model_answers_the_active_space_by_truncation(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    active = space("model-a", 2)
    building = space("model-a", 4)
    provider = QueryProvider(building, vector=unit(0.6, 0.0, 0.8, 0.0))
    search, vectors = _search(factory, provider)

    async def scenario() -> None:
        await _library(factory, search)
        await vectors.register_space(active)
        await vectors.activate_space(active.id)
        await vectors.register_space(building)
        truncated = truncate_and_renormalize(provider.vector, 2)
        assert truncated == (1.0, 0.0)
        await vectors.index_embedding_vector(record("asset_beach", 2), truncated, space_id=active.id)

        results = await search.search(SearchQuery(text="olas oceano"))

        assert [item.asset_id for item in results.items][:1] == ["asset_beach"]
        assert MatchReason.SEMANTIC in results.items[0].match_reasons

    asyncio.run(scenario())
