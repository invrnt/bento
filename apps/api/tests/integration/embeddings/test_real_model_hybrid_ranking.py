"""Opt-in: hybrid (FTS + vector) ranking on a small library with the pinned model (real `llama-server`).

Same environment as `test_real_model_calibration.py`. It builds the second real-model pass's kind of library in a
temporary SQLite database (OCR off: document text for PDFs with a text layer and text files, file names only for
scans and images), embeds it for real and runs `CompositeSearchIndex.search` for the pass's queries.
`BENTO_REAL_MODEL_RANKING_REPORT=<file>` writes the top-6 lists as JSON.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import statistics
import sys
from pathlib import Path

import pytest

from bento.adapters.embeddings import LlamaCppEmbeddingProvider
from bento.adapters.embeddings.sqlite_text import SQLiteEmbeddingTextCatalog
from bento.adapters.repositories import SQLiteAssetRepository
from bento.adapters.search.composite import CompositeSearchIndex
from bento.adapters.search.sqlite_fts import SQLiteFTSSearchIndex
from bento.adapters.search.sqlite_vec import SQLiteVecSearchIndex
from bento.application.indexing.embedding import ChunkVector
from bento.domain.assets import Asset, AssetKind, AssetMetadata, AssetMode, ProcessingState, infer_asset_kind
from bento.domain.indexing import EmbeddingRecord, ExtractedPage
from bento.domain.search import MatchReason, SearchQuery
from bento.domain.smart_search import chunk_text

from tests.integration.db.support import NOW, FixedClock, migrated_session_factory
from tests.integration.embeddings.real_model_support import model_spec, needs_real_model, real_provider
from tests.integration.embeddings.small_library import FILES, QUERIES, RELEVANT, ndcg_at

pytestmark = pytest.mark.real_model

# Off-topic queries and the most semantic hits each may keep. The floor cannot go higher without losing a real
# cross-language match (calibration doc), so a query whose best cosine is just above it keeps a couple.
OFF_TOPIC = {"zzzz quantum chromodynamics": 2, "partitura de violonchelo barroco": 0}
NDCG_AT_6_FLOOR = 0.95  # 0.923 before the floor and the lexical rules, 0.961 after (calibration doc)

# The file each query is about: it must lead the list.
EXPECTED_FIRST = {
    "vacuna del perro": "doc-2026-0417.pdf",
    "contraseña del wifi": "apuntes.txt",
    "mortgage interest rate": "notes-0312.txt",
    "car brakes repair": "nota-taller.txt",
    "speeding ticket": "doc-2026-0601.pdf",
    "endesa": "endesa-recibo-abril.png",
}
# Files that must not appear in a query's top 6 (pass 2's file-name substring matches).
NOT_IN_TOP = {
    "facturas de luz": {"ideas-regalos-navidad.txt"},
    "receta de pasta": {"ideas-regalos-navidad.txt"},
    "viaje a la playa": {"ideas-regalos-navidad.txt", "plan-mudanza.md"},
    "reunión de presupuesto": {"ideas-regalos-navidad.txt"},
    "car brakes repair": {"receta-pasta-carbonara.pdf"},
}


def _asset(index: int, name: str, mime: str) -> Asset:
    kind = infer_asset_kind(mime)
    return Asset(
        id=f"asset_{index:02d}",
        kind=kind,
        mode=AssetMode.DRIVE,
        folder_id=None,
        filename=name,
        metadata=AssetMetadata(
            original_filename=name,
            mime_type=mime,
            size_bytes=1024,
            sha256=hashlib.sha256(name.encode()).hexdigest(),
            exif=None,
        ),
        processing_state=ProcessingState.INDEXED,
        favorite=False,
        created_at=NOW,
        updated_at=NOW,
    )


async def build_search(tmp_path: Path, provider: LlamaCppEmbeddingProvider) -> CompositeSearchIndex:
    """The library in a fresh database, embedded with `provider`, behind the production search adapter."""
    spec = provider.spec
    factory = migrated_session_factory(tmp_path)
    clock = FixedClock()
    fts = SQLiteFTSSearchIndex(factory, clock)
    vectors = SQLiteVecSearchIndex(factory, clock, allow_fallback=True)
    catalog = SQLiteEmbeddingTextCatalog(factory)
    repository = SQLiteAssetRepository(factory)
    space = provider.space
    await vectors.register_space(space)
    await vectors.activate_space(space.id)
    for index, (name, mime, text) in enumerate(FILES):
        asset = _asset(index, name, mime)
        await repository.add(asset)
        if asset.kind is not AssetKind.IMAGE:  # text_extract runs for documents (an empty scan too)
            await fts.replace_document_text(asset.id, [ExtractedPage(text=text, page_number=1)] if text else [])
        # The embedding text of `EmbeddingIndexingService._chunks_for_asset` with OCR off.
        indexed = (await catalog.text_for_asset(asset.id) or "").strip()
        metadata = " ".join((name, name, mime))
        body = "\n".join(p for p in (indexed, metadata) if p) if asset.kind is AssetKind.IMAGE else indexed or metadata
        chunks = chunk_text(body, max_tokens=spec.chunk_tokens)
        embedded = await provider.embed_documents([chunk.text for chunk in chunks], title=name)
        record = EmbeddingRecord(
            id=f"emb_{asset.id}", asset_id=asset.id, provider="managed", vector_ref=space.id, dimensions=space.dims
        )
        await vectors.index_chunk_vectors(
            space.id,
            record,
            [ChunkVector(chunk_no=c.chunk_no, page=c.page, vector=v) for c, v in zip(chunks, embedded, strict=True)],
        )
    return CompositeSearchIndex(factory, clock, text_index=fts, vector_index=vectors, query_embedding_provider=provider)


async def run_queries(search: CompositeSearchIndex) -> dict[str, list[dict[str, object]]]:
    report = {}
    for query in QUERIES:
        results = await search.search(SearchQuery(text=query, limit=6))
        report[query] = [
            {"title": item.title, "score": item.score, "reasons": [reason.value for reason in item.match_reasons]}
            for item in results.items
        ]
    return report


def mean_ndcg(report: dict[str, list[dict[str, object]]]) -> float:
    return statistics.fmean(ndcg_at([str(item["title"]) for item in report[q]], RELEVANT[q]) for q in RELEVANT)


@needs_real_model
def test_hybrid_ranking_on_a_small_library(tmp_path: Path) -> None:
    spec = model_spec()

    async def scenario() -> dict[str, list[dict[str, object]]]:
        async with real_provider(tmp_path / "run", spec, spec.default_dims) as provider:
            return await run_queries(await build_search(tmp_path, provider))

    report = asyncio.run(scenario())
    ndcg = mean_ndcg(report)
    path = os.environ.get("BENTO_REAL_MODEL_RANKING_REPORT")
    if path:
        Path(path).expanduser().write_text(
            json.dumps({"ndcg6": ndcg, "queries": report}, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    for query, items in report.items():
        print(f"\n{query}", file=sys.stderr)
        for rank, item in enumerate(items, 1):
            print(f"  {rank} {item['title']} {item['score']} {','.join(item['reasons'])}", file=sys.stderr)
    print(f"\nmean nDCG@6 {ndcg:.3f}", file=sys.stderr)

    for query, allowed in OFF_TOPIC.items():
        semantic = [item for item in report[query] if MatchReason.SEMANTIC.value in item["reasons"]]
        assert len(semantic) <= allowed, (query, report[query])
    for query, title in EXPECTED_FIRST.items():
        assert report[query] and report[query][0]["title"] == title, (query, report[query])
    for query, banned in NOT_IN_TOP.items():
        assert not banned & {item["title"] for item in report[query]}, (query, report[query])
    assert ndcg >= NDCG_AT_6_FLOOR, ndcg
