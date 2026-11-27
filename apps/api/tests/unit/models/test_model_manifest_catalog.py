from __future__ import annotations

import json
from pathlib import Path

import pytest

from bento.adapters.models.manifest_catalog import ManifestModelCatalog
from bento.domain.smart_search import InvalidModelSpecError, Pooling
from bento.infrastructure.models import (
    download_user_agent,
    license_text,
    load_model_catalog,
    model_notice_text,
    models_root,
    packaged_manifest_data,
)
from tests.unit.models.model_fakes import canonical_manifest

PACKAGED = Path(__file__).parents[3] / "src" / "bento" / "infrastructure" / "models" / "manifest.json"


def test_packaged_manifest_matches_the_canonical_fixture_except_the_mirror_url() -> None:
    packaged = packaged_manifest_data()
    canonical = canonical_manifest()

    def without_mirrors(data: dict) -> dict:
        copy = json.loads(json.dumps(data))
        for model in copy["models"]:
            for file in model["files"]:
                file["urls"] = [url for url in file["urls"] if "huggingface.co" in url]
        return copy

    assert without_mirrors(packaged) == without_mirrors(canonical)
    weights = packaged["models"][0]["files"][0]
    assert weights["urls"][0].startswith("https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/resolve/")
    assert weights["urls"][1].startswith("https://github.com/")
    assert weights["urls"][1].endswith("/embeddinggemma-2-Q8_0.gguf")


def test_packaged_catalog_default_is_embeddinggemma_2_at_768_dims_with_qwen3_fallback() -> None:
    catalog = load_model_catalog()

    default = catalog.default()
    assert default.model_id == "embeddinggemma-2-q8_0"
    assert default.revision == "6ea3e3a309d12a4779cfda98b8c19800d2d5da71"
    assert default.default_dims == 768  # D9 (2026-11-27)
    assert default.pooling is Pooling.MEAN
    assert default.weights.size_bytes == 309_855_456
    assert default.weights.sha256 == "2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135"
    assert default.license_spdx == "Apache-2.0"
    assert default.space().id == "embeddinggemma-2-q8_0@6ea3e3a309d12a4779cfda98b8c19800d2d5da71/768"

    fallback = catalog.get("qwen3-embedding-0.6b-q8_0")
    assert fallback is not None
    assert fallback.pooling is Pooling.LAST
    assert fallback.weights.sha256 == "06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439"
    assert [spec.model_id for spec in catalog.all()] == ["embeddinggemma-2-q8_0", "qwen3-embedding-0.6b-q8_0"]


def test_catalog_lookups_by_revision() -> None:
    catalog = load_model_catalog()

    assert catalog.get("embeddinggemma-2-q8_0", "6ea3e3a309d12a4779cfda98b8c19800d2d5da71") is not None
    assert catalog.get("embeddinggemma-2-q8_0", "0000000") is None
    assert catalog.get("unknown-model") is None


def test_catalog_reads_a_manifest_file_and_rejects_bad_ones(tmp_path: Path) -> None:
    good = tmp_path / "manifest.json"
    good.write_text(PACKAGED.read_text(encoding="utf-8"), encoding="utf-8")
    assert load_model_catalog(good).default().model_id == "embeddinggemma-2-q8_0"

    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(InvalidModelSpecError):
        ManifestModelCatalog.from_path(bad)
    with pytest.raises(InvalidModelSpecError):
        ManifestModelCatalog.from_path(tmp_path / "missing.json")


def test_the_apache_license_text_and_use_policy_notice_ship_with_the_package() -> None:
    text = license_text("Apache-2.0")
    assert "Apache License" in text
    assert "Version 2.0, January 2004" in text
    assert "END OF TERMS AND CONDITIONS" in text

    notice = model_notice_text("embeddinggemma-2-q8_0")
    assert notice is not None
    assert "https://gemma.ai/resources/prohibited-use/" in notice
    assert "6ea3e3a309d12a4779cfda98b8c19800d2d5da71" in notice
    assert model_notice_text("qwen3-embedding-0.6b-q8_0") is not None

    with pytest.raises(FileNotFoundError):
        license_text("../manifest")
    with pytest.raises(FileNotFoundError):
        license_text("MIT")


def test_paths_and_user_agent() -> None:
    assert models_root("/data") == Path("/data") / "models"
    assert download_user_agent("1.2.3") == "Bento/1.2.3"
