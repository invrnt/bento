"""Shared helpers for the embedding space tests (no network, no models)."""

from __future__ import annotations

import asyncio
import hashlib
import math

import pytest
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories import SQLiteAssetRepository
from bento.adapters.search.sqlite_vec import SQLiteVecSearchIndex
from bento.domain.assets import AssetKind
from bento.domain.indexing import EmbeddingRecord
from bento.domain.smart_search import EmbeddingSpace, space_id_for

from tests.integration.db.support import FixedClock, make_asset


def space(model_id: str, dims: int, revision: str = "a" * 40) -> EmbeddingSpace:
    return EmbeddingSpace(id=space_id_for(model_id, revision, dims), model_id=model_id, revision=revision, dims=dims)


def unit(*values: float) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in values))
    return tuple(value / norm for value in values)


def seeded_unit(seed: str, dims: int) -> tuple[float, ...]:
    values: list[float] = []
    counter = 0
    while len(values) < dims:
        digest = hashlib.sha256(f"{seed}:{counter}".encode()).digest()
        for index in range(0, len(digest), 4):
            values.append(int.from_bytes(digest[index : index + 4], "big") / 0xFFFFFFFF * 2.0 - 1.0)
            if len(values) == dims:
                break
        counter += 1
    return unit(*values)


def record(asset_id: str, dims: int, provider: str = "managed") -> EmbeddingRecord:
    return EmbeddingRecord(
        id=f"emb_{asset_id}", asset_id=asset_id, provider=provider, vector_ref=f"{provider}:{asset_id}", dimensions=dims
    )


async def add_assets(factory: sessionmaker[Session], *asset_ids: str, kind: AssetKind = AssetKind.PDF) -> None:
    repository = SQLiteAssetRepository(factory)
    for asset_id in asset_ids:
        sha = hashlib.sha256(asset_id.encode()).hexdigest()
        await repository.add(make_asset(asset_id, filename=f"{asset_id}.pdf", sha256=sha, kind=kind))


def vector_index(factory: sessionmaker[Session], *, sqlite_vec: bool) -> SQLiteVecSearchIndex:
    """A vector index in the requested mode; skips the test when sqlite-vec cannot be imported or loaded."""
    if not sqlite_vec:
        return SQLiteVecSearchIndex(factory, FixedClock(), prefer_sqlite_vec=False)
    pytest.importorskip("sqlite_vec")
    index = SQLiteVecSearchIndex(factory, FixedClock(), allow_fallback=True)
    asyncio.run(index.initialize())
    if not index.using_sqlite_vec:
        pytest.skip("the sqlite-vec extension does not load on this Python build")
    return index


MODES = [pytest.param(False, id="fallback"), pytest.param(True, id="sqlite-vec")]

__all__ = ["MODES", "add_assets", "record", "seeded_unit", "space", "unit", "vector_index"]
