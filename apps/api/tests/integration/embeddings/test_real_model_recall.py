"""Opt-in: cross-language (es↔en) recall of the pinned model on a real llama-server.

Skipped unless both paths are set; never runs in local CI and never downloads anything:

    BENTO_REAL_LLAMA_SERVER=~/.cache/bento-spike/llama/llama-b12777/llama-server \\
    BENTO_REAL_EMBEDDING_MODEL=~/.cache/bento-spike/models/embeddinggemma-2-Q8_0.gguf \\
    uv run --project apps/api pytest apps/api/tests/integration/embeddings/test_real_model_recall.py -m real_model -s

`BENTO_REAL_MODEL_ID` picks another manifest model (for example `qwen3-embedding-0.6b-q8_0`), and
`BENTO_REAL_MODEL_REPORT=<file>` writes the measurements as JSON. The documents are the Stage 23 spike's
synthetic fixture (`scripts/spikes/smart-search/dataset.py`); D9 asks for this check before release.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from bento.adapters.embeddings import LlamaCppEmbeddingProvider
from bento.adapters.runtime.llama_server_process import LlamaServerProcess
from bento.domain.smart_search import (
    best_chunk_scores,
    chunk_text,
    default_embedding_threads,
    parse_manifest,
    truncate_and_renormalize,
)

pytestmark = pytest.mark.real_model

SERVER = os.environ.get("BENTO_REAL_LLAMA_SERVER", "")
MODEL = os.environ.get("BENTO_REAL_EMBEDDING_MODEL", "")
REPO_ROOT = Path(__file__).resolve().parents[5]
DATASET = REPO_ROOT / "scripts" / "spikes" / "smart-search" / "dataset.py"
MANIFEST = Path(__file__).resolve().parents[2] / "unit" / "smart_search" / "manifest_v1.json"
RECALL_AT_5_FLOOR = 0.75

# (query, relevant document ids): Spanish queries for English documents and English queries for Spanish ones.
CROSS_LANGUAGE_QUERIES: list[tuple[str, str, list[str]]] = [
    ("en->es", "electricity bill for March", ["luz-2026-03"]),
    ("en->es", "passport expiration date", ["pasaporte"]),
    ("en->es", "potato omelette recipe", ["receta-tortilla"]),
    ("en->es", "flight ticket to Bogota", ["tarjeta-embarque-bogota"]),
    ("en->es", "employment contract salary", ["contrato-laboral"]),
    ("en->es", "dog vaccination record", ["vacuna-perro"]),
    ("en->es", "cold tomato soup", ["receta-gazpacho"]),
    ("en->es", "high speed train ticket to Barcelona", ["tren-renfe"]),
    ("en->es", "home rental agreement monthly rent", ["contrato-alquiler"]),
    ("en->es", "car insurance policy", ["seguro-coche"]),
    ("en->es", "blood test cholesterol results", ["analitica"]),
    ("en->es", "speeding ticket fine", ["multa"]),
    ("en->es", "school report card grades", ["boletin-notas"]),
    ("en->es", "mortgage deed", ["hipoteca"]),
    ("en->es", "hotel booking in Lisbon", ["hotel-lisboa"]),
    ("en->es", "skiing photo in the snow", ["foto-nieve"]),
    ("en->es", "income tax return", ["renta-2025"]),
    ("es->en", "informe trimestral de ingresos", ["informe-trimestral"]),
    ("es->en", "acuerdo de confidencialidad", ["nda", "nda-cliente"]),
    ("es->en", "receta de pan de plátano", ["receta-banana-bread"]),
    ("es->en", "hotel en Tokio", ["hotel-tokio"]),
    ("es->en", "receta de tortitas esponjosas", ["receta-pancakes"]),
    ("es->en", "postre de chocolate", ["receta-brownies"]),
    ("es->en", "guía rápida del televisor", ["manual-tv"]),
    ("es->en", "manual del empleado y teletrabajo", ["onboarding-guide"]),
    ("es->en", "gastos de la conferencia en Berlín", ["expense-report"]),
    ("es->en", "curry de garbanzos", ["receta-curry"]),
    ("es->en", "certificado de inglés avanzado", ["cursos-ingles"]),
    ("es->en", "foto del cruce de Shibuya", ["foto-tokio"]),
    ("es->en", "informe anual de ingresos", ["annual-report", "informe-trimestral"]),
]


def _dataset() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bento_spike_dataset", DATASET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _score(rankings: dict[str, list[str]]) -> dict[str, float]:
    recalls, reciprocal = [], []
    for _, query, relevant in CROSS_LANGUAGE_QUERIES:
        ranked = rankings[query]
        hits = len(set(relevant) & set(ranked[:5]))
        recalls.append(hits / min(len(relevant), 5))
        first = next((i for i, doc in enumerate(ranked) if doc in relevant), None)
        reciprocal.append(0.0 if first is None else 1.0 / (first + 1))
    return {"recall5": statistics.fmean(recalls), "mrr": statistics.fmean(reciprocal)}


def _dot(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return math.fsum(a * b for a, b in zip(left, right, strict=True))


@pytest.mark.skipif(not (SERVER and MODEL), reason="set BENTO_REAL_LLAMA_SERVER and BENTO_REAL_EMBEDDING_MODEL")
def test_cross_language_recall_on_the_pinned_model(tmp_path: Path) -> None:
    dataset = _dataset()
    documents: list[dict[str, str]] = dataset.documents()
    ids = {doc["id"] for doc in documents}
    assert len(CROSS_LANGUAGE_QUERIES) >= 20
    for _, _, relevant in CROSS_LANGUAGE_QUERIES:
        assert set(relevant) <= ids, relevant

    specs, default_id = parse_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))
    model_id = os.environ.get("BENTO_REAL_MODEL_ID", default_id)
    spec = next(s for s in specs if s.model_id == model_id)
    native = spec.space(spec.native_dims)

    async def scenario() -> dict[str, Any]:
        runtime = LlamaServerProcess(
            run_dir=tmp_path / "run",
            binary=Path(SERVER).expanduser(),
            threads=default_embedding_threads(os.cpu_count() or 1),
        )
        started = time.perf_counter()
        info = await runtime.ensure(spec, native, Path(MODEL).expanduser())
        ready_seconds = time.perf_counter() - started
        provider = LlamaCppEmbeddingProvider(spec=spec, space=native, endpoint=lambda: info)
        try:
            chunk_vectors: list[tuple[str, tuple[float, ...]]] = []
            started = time.perf_counter()
            for doc in documents:
                chunks = [chunk.text for chunk in chunk_text(doc["text"], max_tokens=spec.chunk_tokens)]
                vectors = await provider.embed_documents(chunks, title=doc["title"])
                chunk_vectors.extend((doc["id"], vector) for vector in vectors)
            index_seconds = time.perf_counter() - started
            query_vectors = {}
            query_ms = []
            for _, query, _ in CROSS_LANGUAGE_QUERIES:
                started = time.perf_counter()
                query_vectors[query] = await provider.embed_query(query)
                query_ms.append((time.perf_counter() - started) * 1000)
        finally:
            await runtime.stop()

        results: dict[str, Any] = {
            "model": spec.model_id,
            "queries": len(CROSS_LANGUAGE_QUERIES),
            "server_ready_s": round(ready_seconds, 2),
            "index_s": round(index_seconds, 2),
            "query_ms_p50": round(statistics.median(query_ms), 1),
            "dims": {},
        }
        for dims in spec.matryoshka_dims:
            docs_at = [(doc_id, truncate_and_renormalize(vector, dims)) for doc_id, vector in chunk_vectors]
            rankings = {}
            for query, vector in query_vectors.items():
                q = truncate_and_renormalize(vector, dims)
                best = best_chunk_scores((doc_id, _dot(q, doc_vector)) for doc_id, doc_vector in docs_at)
                rankings[query] = [doc for doc, _ in sorted(best.items(), key=lambda item: item[1], reverse=True)]
            results["dims"][str(dims)] = _score(rankings)
        return results

    results = asyncio.run(scenario())
    print(json.dumps(results, indent=2), file=sys.stderr)
    report = os.environ.get("BENTO_REAL_MODEL_REPORT")
    if report:
        Path(report).expanduser().write_text(json.dumps(results, indent=2), encoding="utf-8")

    default = results["dims"][str(spec.default_dims)]
    assert default["recall5"] >= RECALL_AT_5_FLOOR, results
