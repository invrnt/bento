"""Opt-in: calibrates the semantic similarity floor on the pinned model (real `llama-server`, no download).

    BENTO_REAL_LLAMA_SERVER=dist/llama-server/linux-x64/llama-server \\
    BENTO_REAL_EMBEDDING_MODEL=~/.cache/bento-calib/embeddinggemma-2-Q8_0.gguf \\
    BENTO_REAL_MODEL_CALIBRATION_REPORT=/tmp/calibration.json \\
    uv run --project apps/api pytest apps/api/tests/integration/embeddings/test_real_model_calibration.py -m real_model -s

For every query of the 200-document spike fixture it records the cosine scores of the relevant documents and of
the rest, adds off-topic and nonsense queries (es and en) that should match nothing, and sweeps an absolute floor
and a margin under the best hit. The report is the data behind `min_similarity` in the model manifest
(`orchestration/execution/evidence/smart-search-relevance-calibration-2026-11-27.md`).
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
from pathlib import Path
from typing import Any

import pytest

from bento.domain.smart_search import best_chunk_scores, chunk_text, semantic_cutoff, truncate_and_renormalize

from tests.integration.embeddings.real_model_support import dataset, dot, model_spec, needs_real_model, real_provider
from tests.integration.embeddings.test_real_model_recall import CROSS_LANGUAGE_QUERIES

pytestmark = pytest.mark.real_model

# Queries about nothing in the fixture: a good floor leaves them without a single semantic hit.
OFF_TOPIC_QUERIES: list[tuple[str, str]] = [
    ("en", "zzzz quantum chromodynamics"),
    ("en", "lorem ipsum dolor sit amet"),
    ("en", "baroque cello sheet music"),
    ("en", "rocket engine combustion chamber"),
    ("en", "jurassic dinosaur fossils"),
    ("en", "chess opening theory"),
    ("en", "growing orchids indoors"),
    ("en", "volcano eruption on mars"),
    ("en", "asdf qwerty uiop"),
    ("es", "zzzz cromodinámica cuántica"),
    ("es", "partitura de violonchelo barroco"),
    ("es", "fósiles de dinosaurios del jurásico"),
    ("es", "apertura de ajedrez siciliana"),
    ("es", "cultivo de orquídeas en casa"),
    ("es", "erupción de un volcán en marte"),
    ("es", "xkcd blorp fnord"),
]

RECALL_AT_5_WITH_FLOOR = 0.983
FLOORS = [round(0.30 + 0.01 * step, 2) for step in range(51)]  # 0.30 .. 0.80 (128 dims sits higher)
MARGINS: list[float | None] = [None, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30]


def _percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    index = min(int(round(p / 100 * (len(ordered) - 1))), len(ordered) - 1)
    return round(ordered[index], 4)


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "n": len(values),
        "min": round(min(values), 4),
        "p5": _percentile(values, 5),
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
        "max": round(max(values), 4),
    }


def _kept(scores: dict[str, float], floor: float, margin: float | None) -> list[str]:
    """Documents above the cut, best first (the same rule as search, `semantic_cutoff`)."""
    cut = semantic_cutoff(max(scores.values(), default=0.0), floor=floor, margin=margin)
    return [doc for doc, score in sorted(scores.items(), key=lambda item: (-item[1], item[0])) if score >= cut]


def _sweep(
    labelled: list[tuple[str, list[str], dict[str, float]]],
    cross: set[str],
    off_topic: list[dict[str, float]],
) -> list[dict[str, Any]]:
    rows = []
    for floor in FLOORS:
        for margin in MARGINS:
            recalls_x, recalls_all, extra, kept_relevant, total_relevant = [], [], [], 0, 0
            for query, relevant, scores in labelled:
                kept = _kept(scores, floor, margin)
                recall = len(set(relevant) & set(kept[:5])) / min(len(relevant), 5)
                recalls_all.append(recall)
                if query in cross:
                    recalls_x.append(recall)
                kept_relevant += len(set(relevant) & set(kept))
                total_relevant += len(relevant)
                extra.append(len([doc for doc in kept if doc not in relevant]))
            off_hits = [len(_kept(scores, floor, margin)) for scores in off_topic]
            rows.append(
                {
                    "floor": floor,
                    "margin": margin,
                    "recall5_cross": round(statistics.fmean(recalls_x), 4),
                    "recall5_all": round(statistics.fmean(recalls_all), 4),
                    "relevant_kept": round(kept_relevant / total_relevant, 4),
                    "irrelevant_kept_mean": round(statistics.fmean(extra), 2),
                    "irrelevant_kept_p90": _percentile([float(x) for x in extra], 90),
                    "off_topic_queries_with_hits": sum(1 for hits in off_hits if hits),
                    "off_topic_hits": sum(off_hits),
                }
            )
    return rows


@needs_real_model
def test_similarity_calibration_on_the_pinned_model(tmp_path: Path) -> None:
    data = dataset()
    documents: list[dict[str, str]] = data.documents()
    spec = model_spec()
    labelled_queries: dict[str, list[str]] = {query: relevant for _, query, relevant in CROSS_LANGUAGE_QUERIES}
    for entry in data.queries():
        labelled_queries.setdefault(str(entry["q"]), list(entry["relevant"]))
    cross = {query for _, query, _ in CROSS_LANGUAGE_QUERIES}

    async def scenario() -> tuple[list[tuple[str, tuple[float, ...]]], dict[str, tuple[float, ...]]]:
        async with real_provider(tmp_path / "run", spec) as provider:
            chunks: list[tuple[str, tuple[float, ...]]] = []
            for doc in documents:
                texts = [chunk.text for chunk in chunk_text(doc["text"], max_tokens=spec.chunk_tokens)]
                vectors = await provider.embed_documents(texts, title=doc["title"])
                chunks.extend((doc["id"], vector) for vector in vectors)
            queries = {}
            for query in [*labelled_queries, *(q for _, q in OFF_TOPIC_QUERIES)]:
                queries[query] = await provider.embed_query(query)
        return chunks, queries

    chunk_vectors, query_vectors = asyncio.run(scenario())

    report: dict[str, Any] = {
        "model": spec.model_id,
        "documents": len(documents),
        "labelled_queries": len(labelled_queries),
        "cross_language_queries": len(cross),
        "off_topic_queries": len(OFF_TOPIC_QUERIES),
        "dims": {},
    }
    for dims in spec.matryoshka_dims:
        docs_at = [(doc_id, truncate_and_renormalize(vector, dims)) for doc_id, vector in chunk_vectors]

        def scores_for(query: str) -> dict[str, float]:
            q = truncate_and_renormalize(query_vectors[query], dims)
            return best_chunk_scores((doc_id, dot(q, vector)) for doc_id, vector in docs_at)

        labelled = [(query, relevant, scores_for(query)) for query, relevant in labelled_queries.items()]
        off_topic = [scores_for(query) for _, query in OFF_TOPIC_QUERIES]
        relevant_scores = [s[d] for _, relevant, s in labelled for d in relevant]
        irrelevant_scores = [v for _, relevant, s in labelled for d, v in s.items() if d not in relevant]
        best_irrelevant = [max(v for d, v in s.items() if d not in relevant) for _, relevant, s in labelled]
        top_gap = [max(s.values()) - min(s[d] for d in relevant) for _, relevant, s in labelled]
        per_query = [
            {
                "query": query,
                "cross_language": query in cross,
                "relevant": {d: round(s[d], 4) for d in relevant},
                "best_irrelevant": round(max(v for d, v in s.items() if d not in relevant), 4),
                "top": round(max(s.values()), 4),
                "irrelevant_p95": _percentile([v for d, v in s.items() if d not in relevant], 95),
            }
            for query, relevant, s in labelled
        ]
        off_topic_rows = [
            {"lang": lang, "query": query, "top": round(max(s.values()), 4), "top5": sorted(s.values(), reverse=True)[4]}
            for (lang, query), s in zip(OFF_TOPIC_QUERIES, off_topic, strict=True)
        ]
        report["dims"][str(dims)] = {
            "relevant": _summary(relevant_scores),
            "irrelevant": _summary(irrelevant_scores),
            "best_irrelevant_per_query": _summary(best_irrelevant),
            "top_minus_relevant": _summary(top_gap),
            "off_topic_top": _summary([row["top"] for row in off_topic_rows]),
            "per_query": per_query,
            "off_topic": off_topic_rows,
            "sweep": _sweep(labelled, cross, off_topic),
        }

    path = os.environ.get("BENTO_REAL_MODEL_CALIBRATION_REPORT")
    if path:
        Path(path).expanduser().write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    brief = {dims: {k: v for k, v in entry.items() if k not in {"per_query", "off_topic", "sweep"}} for dims, entry in report["dims"].items()}
    print(json.dumps(brief, indent=2), file=sys.stderr)

    default = report["dims"][str(spec.default_dims)]
    floor = spec.min_similarity_for(spec.default_dims)
    chosen = next(row for row in default["sweep"] if row["floor"] == round(floor, 2) and row["margin"] == spec.similarity_margin)
    print(json.dumps({"chosen": chosen}, indent=2), file=sys.stderr)
    unfiltered = next(row for row in default["sweep"] if row["floor"] == FLOORS[0] and row["margin"] is None)
    assert chosen["recall5_cross"] >= RECALL_AT_5_WITH_FLOOR, chosen
    assert chosen["recall5_cross"] >= unfiltered["recall5_cross"], (chosen, unfiltered)
    # The floor removes nearly every off-topic hit; it cannot remove them all without losing real matches.
    assert chosen["off_topic_hits"] <= 0.05 * len(OFF_TOPIC_QUERIES) * len(documents), chosen
    assert chosen["irrelevant_kept_mean"] <= 0.15 * len(documents), chosen
