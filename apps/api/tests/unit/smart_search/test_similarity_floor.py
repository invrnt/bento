from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from bento.domain.smart_search import (
    DEFAULT_MIN_SIMILARITY,
    SEMANTIC_FULL_STRENGTH_SPAN,
    InvalidModelSpecError,
    legacy_space_id,
    parse_manifest,
    relevant_semantic_scores,
    semantic_cutoff,
    semantic_strength,
    similarity_rule,
    space_id_for,
)

CANONICAL = Path(__file__).parent / "manifest_v1.json"


def _manifest() -> dict[str, object]:
    return json.loads(CANONICAL.read_text(encoding="utf-8"))


def _default_spec():  # type: ignore[no-untyped-def]
    specs, default_id = parse_manifest(_manifest())
    return next(spec for spec in specs if spec.model_id == default_id)


def test_the_default_model_carries_its_calibrated_floor_per_dims() -> None:
    spec = _default_spec()
    assert spec.min_similarity_for(768) == 0.60
    assert spec.min_similarity_for(512) == 0.61
    assert spec.min_similarity_for(128) == 0.70
    assert spec.similarity_margin == 0.15


def test_a_model_without_a_calibrated_floor_uses_the_domain_default() -> None:
    specs, _ = parse_manifest(_manifest())
    qwen = next(spec for spec in specs if spec.model_id.startswith("qwen3"))
    assert qwen.min_similarity_for(1024) == DEFAULT_MIN_SIMILARITY
    assert qwen.similarity_margin is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_similarity", {"999": 0.5}),  # not a matryoshka dim
        ("min_similarity", {"768": 1.2}),
        ("min_similarity", {"768": -0.1}),
        ("min_similarity", ["768", 0.5]),
        ("similarity_margin", 0.0),
        ("similarity_margin", 1.5),
    ],
)
def test_the_manifest_rejects_bad_floors(field: str, value: object) -> None:
    data = _manifest()
    data["models"][0][field] = value  # type: ignore[index]
    with pytest.raises(InvalidModelSpecError):
        parse_manifest(data)


def test_the_rule_applies_to_the_spec_space_only() -> None:
    spec = _default_spec()
    own = spec.space(512).id
    assert similarity_rule(spec, own) == (0.61, 0.15)
    other_revision = space_id_for(spec.model_id, "b" * 40, 768)
    assert similarity_rule(spec, other_revision) == (DEFAULT_MIN_SIMILARITY, None)
    assert similarity_rule(None, own) == (DEFAULT_MIN_SIMILARITY, None)  # mock and legacy providers have no spec
    assert similarity_rule(spec, legacy_space_id("mock", 768)) == (DEFAULT_MIN_SIMILARITY, None)
    assert similarity_rule(spec, "not a space") == (DEFAULT_MIN_SIMILARITY, None)


def test_hits_below_the_floor_or_far_below_the_best_are_dropped() -> None:
    scores = {"beach": 0.78, "hotel": 0.66, "noise": 0.62, "below": 0.59}
    assert relevant_semantic_scores(scores, floor=0.60) == {"beach": 0.78, "hotel": 0.66, "noise": 0.62}
    assert relevant_semantic_scores(scores, floor=0.60, margin=0.15) == {"beach": 0.78, "hotel": 0.66}
    assert relevant_semantic_scores({"a": 0.55, "b": 0.41}, floor=0.60, margin=0.15) == {}
    assert relevant_semantic_scores({}, floor=0.60) == {}


def test_the_cutoff_is_the_floor_raised_by_the_margin() -> None:
    assert semantic_cutoff(0.80, floor=0.60) == 0.60
    assert semantic_cutoff(0.80, floor=0.60, margin=0.15) == pytest.approx(0.65)
    assert semantic_cutoff(0.70, floor=0.60, margin=0.15) == 0.60


def test_strength_spreads_kept_scores_from_the_floor_to_the_best_hit() -> None:
    assert SEMANTIC_FULL_STRENGTH_SPAN == 0.20
    assert semantic_strength(0.80, top_score=0.80, floor=0.60) == 1.0
    assert semantic_strength(0.70, top_score=0.80, floor=0.60) == pytest.approx(0.5)
    assert semantic_strength(0.60, top_score=0.80, floor=0.60) == 0.0
    assert semantic_strength(0.90, top_score=0.90, floor=0.60) == 1.0
    assert semantic_strength(0.75, top_score=0.90, floor=0.60) == pytest.approx(0.5)


def test_a_weak_best_hit_stays_weak() -> None:
    assert semantic_strength(0.65, top_score=0.65, floor=0.60) == pytest.approx(0.25)
    assert semantic_strength(0.60, top_score=0.60, floor=0.60) == 0.0


def test_a_spec_can_be_built_with_its_own_values() -> None:
    spec = replace(_default_spec(), min_similarity=((256, 0.5),), similarity_margin=None)
    assert spec.min_similarity_for(256) == 0.5
    assert spec.min_similarity_for(768) == DEFAULT_MIN_SIMILARITY
