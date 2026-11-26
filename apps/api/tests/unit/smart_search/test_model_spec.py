from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import pytest

from bento.domain.smart_search import (
    InvalidEmbeddingSpaceError,
    InvalidModelSpecError,
    Modality,
    ModelFile,
    ModelFileRole,
    PeerVectorDecision,
    UnsupportedModalityError,
    best_chunk_scores,
    default_embedding_threads,
    legacy_space_id,
    migrate_embeddings_provider,
    parse_manifest,
    parse_space_id,
    peer_vector_decision,
    suggest_in_onboarding,
    truncate_and_renormalize,
)

MANIFEST: dict[str, Any] = json.loads((Path(__file__).parent / "manifest_v1.json").read_text(encoding="utf-8"))
EG2_SHA = "2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135"


def test_manifest_parses_default_and_fallback() -> None:
    specs, default_id = parse_manifest(MANIFEST)
    assert default_id == "embeddinggemma-2-q8_0"
    eg2, qwen = specs
    assert eg2.weights.sha256 == EG2_SHA and eg2.text_bytes == 309_855_456
    assert eg2.default_dims == 512  # D9
    assert eg2.space().id == "embeddinggemma-2-q8_0@6ea3e3a309d12a4779cfda98b8c19800d2d5da71/512"
    assert eg2.space(768).dims == 768
    assert qwen.space().dims == 1024
    assert eg2.weights.urls[0].startswith("https://huggingface.co/") and "/resolve/" + eg2.revision in eg2.weights.urls[0]


def test_prefixes_are_asymmetric() -> None:
    (eg2, qwen), _ = parse_manifest(MANIFEST)
    assert eg2.format_query("  facturas de luz ") == "task: search result | query: facturas de luz"
    assert eg2.format_document("Total 42 €", title="factura.pdf") == "title: factura.pdf | text: Total 42 €"
    assert eg2.format_document("Total", title=None) == "title: none | text: Total"
    assert qwen.format_query("recibo") == "Instruct: Given a search query, retrieve relevant files\nQuery:recibo"
    assert qwen.format_document("recibo", title="x.pdf") == "recibo"


def test_invalid_dims_and_image_space_rejected() -> None:
    (eg2, _), _ = parse_manifest(MANIFEST)
    with pytest.raises(InvalidModelSpecError):
        eg2.space(300)
    with pytest.raises(UnsupportedModalityError):
        eg2.space(with_images=True)


def _mutated(path: list[Any], value: Any) -> dict[str, Any]:
    data = copy.deepcopy(MANIFEST)
    target: Any = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return data


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (["schema_version"], 2),
        (["default_model_id"], "nope"),
        (["models"], []),
        (["models", 0, "files", 0, "sha256"], "ABC"),
        (["models", 0, "files", 0, "urls"], ["http://huggingface.co/x"]),
        (["models", 0, "files", 0, "urls"], []),
        (["models", 0, "files", 0, "name"], "../evil.gguf"),
        (["models", 0, "files", 0, "size_bytes"], 0),
        (["models", 0, "files", 0, "role"], "mmproj"),
        (["models", 0, "default_dims"], 300),
        (["models", 0, "matryoshka_dims"], [512, 256]),
        (["models", 0, "query_template"], "query: "),
        (["models", 0, "document_template"], "title: {title}"),
        (["models", 0, "revision"], "main"),
        (["models", 0, "model_id"], "Bad Id"),
        (["models", 0, "pooling"], "max"),
        (["models", 0, "chunk_tokens"], 4096),
        (["models", 0, "modalities"], ["image"]),
        (["models", 1, "model_id"], "embeddinggemma-2-q8_0"),
    ],
)
def test_manifest_validation_rejects(path: list[Any], value: Any) -> None:
    data = _mutated(path, value)
    if path == ["models", 1, "model_id"]:
        data["models"][1]["revision"] = data["models"][0]["revision"]
    with pytest.raises(InvalidModelSpecError):
        parse_manifest(data)


def test_missing_key_is_a_spec_error() -> None:
    data = copy.deepcopy(MANIFEST)
    del data["models"][0]["pooling"]
    with pytest.raises(InvalidModelSpecError):
        parse_manifest(data)


def test_model_file_role_enum() -> None:
    f = ModelFile("m.gguf", ModelFileRole.MMPROJ, ("https://h/m.gguf",), 1, "0" * 64)
    assert f.role is ModelFileRole.MMPROJ


# Embedding spaces -------------------------------------------------------------------


def test_space_ids_round_trip() -> None:
    assert parse_space_id("embeddinggemma-2-q8_0@6ea3e3a3/512") == ("embeddinggemma-2-q8_0", "6ea3e3a3", 512)
    assert legacy_space_id("jina", 768) == "legacy:jina/768"
    assert parse_space_id("legacy:jina/768") == ("jina", "", 768)
    assert legacy_space_id("", 3) == "legacy:unknown/3"


@pytest.mark.parametrize("bad", ["", "x", "m@abcdef1/0", "m@abcdef1/x", "m/512", "M@abcdef1/512", "m@main/512", "legacy:/5"])
def test_malformed_space_ids(bad: str) -> None:
    with pytest.raises(InvalidEmbeddingSpaceError):
        parse_space_id(bad)


def test_space_modalities_and_legacy_flag() -> None:
    (eg2, _), _ = parse_manifest(MANIFEST)
    space = eg2.space()
    assert space.supports(Modality.TEXT) and not space.supports(Modality.IMAGE)
    assert not space.is_legacy


def test_peer_vectors_index_only_in_the_same_space() -> None:
    active = "embeddinggemma-2-q8_0@6ea3e3a3/512"
    assert peer_vector_decision(active, active, 512) is PeerVectorDecision.INDEX
    assert peer_vector_decision(active, active, 768) is PeerVectorDecision.STORE_ONLY
    assert peer_vector_decision(active, "embeddinggemma-2-q8_0@6ea3e3a3/768", 768) is PeerVectorDecision.STORE_ONLY
    assert peer_vector_decision(active, None, 512) is PeerVectorDecision.STORE_ONLY  # old peer: unknown space
    assert peer_vector_decision(None, active, 512) is PeerVectorDecision.STORE_ONLY


# Matryoshka --------------------------------------------------------------------------


def test_truncate_and_renormalize() -> None:
    out = truncate_and_renormalize([3.0, 4.0, 12.0], 2)
    assert out == pytest.approx((0.6, 0.8))
    assert math.isclose(math.fsum(v * v for v in out), 1.0)
    full = truncate_and_renormalize([1.0, 1.0, 1.0, 1.0], 4)
    assert full == pytest.approx((0.5, 0.5, 0.5, 0.5))


def test_truncation_preserves_ranking_of_prefix_cosine() -> None:
    a = truncate_and_renormalize([1.0, 0.0, 5.0], 2)
    b = truncate_and_renormalize([0.9, 0.1, -5.0], 2)
    assert math.fsum(x * y for x, y in zip(a, b, strict=True)) > 0.99


@pytest.mark.parametrize(
    ("vector", "dims"),
    [([1.0, 2.0], 3), ([1.0], 0), ([0.0, 0.0], 2), ([float("nan"), 1.0], 2), ([float("inf"), 1.0], 1)],
)
def test_truncate_rejects_bad_input(vector: list[float], dims: int) -> None:
    with pytest.raises(InvalidEmbeddingSpaceError):
        truncate_and_renormalize(vector, dims)


def test_best_chunk_score_wins() -> None:
    assert best_chunk_scores([("a", 0.2), ("b", 0.5), ("a", 0.7), ("a", 0.1)]) == {"a": 0.7, "b": 0.5}


# Settings / onboarding contracts ------------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "exists", "expected"),
    [("jina", True, "custom"), ("jina", False, "disabled"), ("mock", False, "mock"), ("disabled", True, "disabled"), ("weird", True, "disabled")],
)
def test_embeddings_provider_migration(provider: str, exists: bool, expected: str) -> None:
    assert migrate_embeddings_provider(provider, exists) == expected


def test_onboarding_suggestion_and_threads() -> None:
    gib = 1024**3
    assert suggest_in_onboarding(4, 8 * gib)
    assert not suggest_in_onboarding(2, 16 * gib)
    assert not suggest_in_onboarding(8, 4 * gib)
    assert [default_embedding_threads(c) for c in (1, 2, 4, 8, 16)] == [1, 1, 2, 4, 4]
