from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .parser import QueryIntent


@dataclass(frozen=True, slots=True)
class ScoreWeights:
    text: float
    vector: float
    metadata: float
    recency: float


@dataclass(frozen=True, slots=True)
class ScoreParts:
    text: float = 0.0
    vector: float = 0.0
    metadata: float = 0.0
    recency: float = 0.0


WEIGHTS_BY_INTENT = {
    QueryIntent.GENERAL: ScoreWeights(text=0.55, vector=0.20, metadata=0.15, recency=0.10),
    QueryIntent.DOCUMENT: ScoreWeights(text=0.50, vector=0.05, metadata=0.35, recency=0.10),
    QueryIntent.SCENE: ScoreWeights(text=0.25, vector=0.55, metadata=0.10, recency=0.10),
    QueryIntent.DATE: ScoreWeights(text=0.30, vector=0.05, metadata=0.20, recency=0.45),
}
"""Text-only search uses these without `vector`, renormalised (`weights_for_intent`)."""

HYBRID_WEIGHTS_BY_INTENT = {
    QueryIntent.GENERAL: ScoreWeights(text=0.35, vector=0.45, metadata=0.10, recency=0.10),
    QueryIntent.DOCUMENT: ScoreWeights(text=0.40, vector=0.20, metadata=0.30, recency=0.10),
    QueryIntent.SCENE: ScoreWeights(text=0.30, vector=0.50, metadata=0.10, recency=0.10),
    QueryIntent.DATE: ScoreWeights(text=0.25, vector=0.20, metadata=0.15, recency=0.40),
}
"""With smart search: vector evidence is already floored and spread to [0, 1] (`semantic_strength`), so it can
weigh as much as text. Tuned with `tests/integration/embeddings/test_real_model_hybrid_ranking.py`
(`execution/evidence/smart-search-relevance-calibration-2026-11-27.md`)."""

NAME_ONLY_TEXT_WEIGHT = 0.5
"""With smart search, text evidence found only in a file, folder or album name counts this much of the same
evidence in the file's own text (a name is a few words; a body match is the content)."""


def weights_for_intent(intent: QueryIntent, *, vector_available: bool) -> ScoreWeights:
    if vector_available:
        return HYBRID_WEIGHTS_BY_INTENT[intent]
    weights = WEIGHTS_BY_INTENT[intent]
    total = weights.text + weights.metadata + weights.recency
    if total <= 0:
        return ScoreWeights(text=1.0, vector=0.0, metadata=0.0, recency=0.0)
    return ScoreWeights(
        text=weights.text / total,
        vector=0.0,
        metadata=weights.metadata / total,
        recency=weights.recency / total,
    )


def hybrid_text_score(*, text: float, name: float, body_matched: bool) -> float:
    """Text evidence with smart search on: `text` is the FTS score normalised to the best FTS hit, `name` the share
    of the query found in a name; both count `NAME_ONLY_TEXT_WEIGHT` unless the file's own text matched."""
    weight = 1.0 if body_matched else NAME_ONLY_TEXT_WEIGHT
    return max(text, name) * weight


def fuse_scores(parts: ScoreParts, weights: ScoreWeights) -> float:
    return (
        _clamp(parts.text) * weights.text
        + _clamp(parts.vector) * weights.vector
        + _clamp(parts.metadata) * weights.metadata
        + _clamp(parts.recency) * weights.recency
    )


def recency_score(now: datetime, item_date: datetime | None) -> float:
    if item_date is None:
        return 0.0
    now, item_date = _compatible_datetimes(now, item_date)
    days = max((now - item_date).days, 0)
    return 1.0 / (1.0 + (days / 365.0))


def _clamp(value: float) -> float:
    return max(min(value, 1.0), 0.0)


def _compatible_datetimes(now: datetime, item_date: datetime) -> tuple[datetime, datetime]:
    if now.tzinfo is None and item_date.tzinfo is None:
        return now, item_date
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    if item_date.tzinfo is None:
        item_date = item_date.replace(tzinfo=now.tzinfo)
    return now, item_date
