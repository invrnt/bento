"""Stage 24 smart search settings: choices, defaults, legacy `jina` aliases, validation, advanced/hidden flags."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest

from bento.application.settings import EditableSettingsService, resolve_effective_settings
from bento.domain import settings_registry
from bento.domain.settings import PersistedSettings, SettingApplyMode, SettingSource, SettingValueType
from bento.domain.settings_registry import (
    ADVANCED_SETTINGS,
    DEFAULT_SMART_SEARCH_MODEL_ID,
    LEGACY_CUSTOM_MODEL_PATH,
    MANAGED_MODEL_DIMS,
    SETTINGS_BY_ALIAS,
    SETTINGS_BY_KEY,
    SMART_SEARCH_MODEL_IDS,
    embeddings_provider_choices,
    is_advanced,
    is_hidden,
    smart_search_model_choices,
)
from bento.domain.smart_search import EMBEDDINGS_PROVIDER_CHOICES, ModelSpec, default_embedding_threads, parse_manifest
from bento.infrastructure.settings import Settings, load_effective_settings
from bento.interfaces.desktop import launcher

CANONICAL_MANIFEST = Path(__file__).parent / "smart_search" / "manifest_v1.json"
SHIPPED_MANIFEST = Path(settings_registry.__file__).parents[1] / "infrastructure" / "models" / "manifest.json"
ADVANCED_KEYS = {
    "custom_model_path",
    "custom_mmproj_path",
    "custom_query_prefix",
    "custom_document_prefix",
    "custom_pooling",
    "embedding_dimensions",
    "llama_server_path",
    "embedding_server_url",
    "embedding_threads",
}


class MemorySettingsRepository:
    def __init__(self, persisted: PersistedSettings | None = None) -> None:
        self.persisted = persisted or PersistedSettings()

    async def load(self) -> PersistedSettings:
        return self.persisted

    async def compare_and_set(self, *, expected_revision, values, secret_references):
        assert expected_revision == self.persisted.revision
        merged = dict(self.persisted.values)
        merged.update(values)
        self.persisted = PersistedSettings(expected_revision + 1, merged, dict(self.persisted.secret_references))
        return self.persisted


class ManifestCatalog:
    """`ModelCatalogPort` over parsed manifest specs."""

    def __init__(self, specs: tuple[ModelSpec, ...]) -> None:
        self._specs = {spec.model_id: spec for spec in specs}

    def default(self) -> ModelSpec:
        return next(iter(self._specs.values()))

    def get(self, model_id: str, revision: str | None = None) -> ModelSpec | None:
        return self._specs.get(model_id)

    def all(self) -> tuple[ModelSpec, ...]:
        return tuple(self._specs.values())


def _manifest(path: Path) -> tuple[tuple[ModelSpec, ...], str]:
    return parse_manifest(json.loads(path.read_text(encoding="utf-8")))


def _saved(**values: Any) -> PersistedSettings:
    return PersistedSettings(values={key: json.dumps(value) for key, value in values.items()})


def _service(
    persisted: PersistedSettings | None = None,
    *,
    platform: str | None = None,
    catalog: ManifestCatalog | None = None,
) -> EditableSettingsService:
    return EditableSettingsService(
        repository=MemorySettingsRepository(persisted),  # type: ignore[arg-type]
        environ={},
        runtime_mode="desktop",
        policy_values={"platform": platform} if platform else None,
        model_catalog=catalog,
    )


def _validate(values: dict[str, Any], **kwargs: Any):
    service = _service(**{key: kwargs.pop(key) for key in ("persisted", "platform", "catalog") if key in kwargs})
    return asyncio.run(service.validate(values, **kwargs))


def _codes(result) -> list[tuple[str, str]]:
    return [(issue.key, issue.code) for issue in result.errors]


# --------------------------------------------------------------------------------------
# Choices and defaults


def test_embeddings_provider_choices_and_default() -> None:
    definition = SETTINGS_BY_KEY["embeddings_provider"]

    assert definition.choices == EMBEDDINGS_PROVIDER_CHOICES == ("disabled", "managed", "custom", "mock")
    assert definition.default == "disabled"
    assert Settings().embeddings_provider == "disabled"
    assert "jina" not in definition.choices
    assert "jina_model_path" not in SETTINGS_BY_KEY


def test_smart_search_model_choices_mirror_the_canonical_manifest() -> None:
    specs, default_id = _manifest(CANONICAL_MANIFEST)
    definition = SETTINGS_BY_KEY["smart_search_model"]

    assert SMART_SEARCH_MODEL_IDS == tuple(spec.model_id for spec in specs)
    assert definition.choices == SMART_SEARCH_MODEL_IDS
    assert definition.default == DEFAULT_SMART_SEARCH_MODEL_ID == default_id == "embeddinggemma-2-q8_0"
    assert dict(MANAGED_MODEL_DIMS) == {spec.model_id: spec.matryoshka_dims for spec in specs}
    assert Settings().smart_search_model == default_id


def test_registry_mirror_matches_the_shipped_manifest_when_present() -> None:
    if not SHIPPED_MANIFEST.is_file():
        return  # Created by the models-download agent; the canonical fixture above is the contract.
    specs, default_id = _manifest(SHIPPED_MANIFEST)

    assert default_id == DEFAULT_SMART_SEARCH_MODEL_ID
    assert {spec.model_id: spec.matryoshka_dims for spec in specs} == dict(MANAGED_MODEL_DIMS)


@pytest.mark.parametrize(
    ("key", "value_type", "default"),
    [
        ("smart_search_model", SettingValueType.CHOICE, "embeddinggemma-2-q8_0"),
        ("custom_model_path", SettingValueType.PATH, ""),
        ("custom_mmproj_path", SettingValueType.PATH, ""),
        ("custom_query_prefix", SettingValueType.STRING, ""),
        ("custom_document_prefix", SettingValueType.STRING, ""),
        ("custom_pooling", SettingValueType.CHOICE, "auto"),
        ("embedding_dimensions", SettingValueType.INTEGER, 512),
        ("llama_server_path", SettingValueType.PATH, ""),
        ("embedding_server_url", SettingValueType.STRING, ""),
        ("embedding_threads", SettingValueType.INTEGER, default_embedding_threads(os.cpu_count() or 1)),
    ],
)
def test_smart_search_registry_entries_match_settings_model(key: str, value_type: SettingValueType, default: object) -> None:
    definition = SETTINGS_BY_KEY[key]

    assert (definition.group, definition.value_type, definition.default) == ("ai", value_type, default)
    assert definition.apply_mode == SettingApplyMode.RESTART_SERVICES
    assert definition.label_key == f"settings.{key}.label"
    assert not definition.secret and definition.editable
    assert Settings().model_dump()[key] == default


def test_embedding_threads_default_is_cpu_safe() -> None:
    default = SETTINGS_BY_KEY["embedding_threads"].default

    assert 1 <= default <= 4
    assert default == min(4, max(1, (os.cpu_count() or 1) // 2))
    assert (SETTINGS_BY_KEY["embedding_threads"].minimum, SETTINGS_BY_KEY["embedding_threads"].maximum) == (1, 64)


def test_custom_pooling_offers_auto_and_the_domain_poolings() -> None:
    assert SETTINGS_BY_KEY["custom_pooling"].choices == ("auto", "mean", "last", "cls")


# --------------------------------------------------------------------------------------
# Environment aliases


def test_custom_model_path_keeps_the_legacy_environment_aliases() -> None:
    for alias in ("BENTO_CUSTOM_MODEL_PATH", "JINA_MODEL_PATH", "BENTO_EMBEDDING_MODEL_PATH"):
        assert SETTINGS_BY_ALIAS[alias].key == "custom_model_path"
    for alias, key in {
        "BENTO_SMART_SEARCH_MODEL": "smart_search_model",
        "BENTO_CUSTOM_MMPROJ_PATH": "custom_mmproj_path",
        "BENTO_CUSTOM_QUERY_PREFIX": "custom_query_prefix",
        "BENTO_CUSTOM_DOCUMENT_PREFIX": "custom_document_prefix",
        "BENTO_CUSTOM_POOLING": "custom_pooling",
        "BENTO_EMBEDDING_DIMENSIONS": "embedding_dimensions",
        "BENTO_LLAMA_SERVER_PATH": "llama_server_path",
        "BENTO_EMBEDDING_SERVER_URL": "embedding_server_url",
        "BENTO_EMBEDDING_THREADS": "embedding_threads",
    }.items():
        assert SETTINGS_BY_ALIAS[alias].key == key


@pytest.mark.parametrize("alias", ["JINA_MODEL_PATH", "BENTO_EMBEDDING_MODEL_PATH", "BENTO_CUSTOM_MODEL_PATH"])
def test_headless_alias_sets_custom_model_path(alias: str) -> None:
    snapshot = resolve_effective_settings(
        persisted=PersistedSettings(), environ={alias: "/models/own.gguf"}, runtime_mode="headless"
    )
    settings = load_effective_settings(Settings(), environ={alias: "/models/own.gguf"}, persisted=PersistedSettings())

    assert snapshot.values["custom_model_path"].value == "/models/own.gguf"
    assert snapshot.values["custom_model_path"].source == SettingSource.ENVIRONMENT
    assert snapshot.values["custom_model_path"].locked is True
    assert settings.custom_model_path == "/models/own.gguf"
    assert settings.jina_model_path == "/models/own.gguf"


def test_new_alias_wins_over_the_legacy_ones() -> None:
    snapshot = resolve_effective_settings(
        persisted=PersistedSettings(),
        environ={"JINA_MODEL_PATH": "/old.gguf", "BENTO_CUSTOM_MODEL_PATH": "/new.gguf"},
        runtime_mode="headless",
    )

    assert snapshot.values["custom_model_path"].value == "/new.gguf"


def test_settings_model_accepts_the_old_field_name() -> None:
    assert Settings(jina_model_path="/m.gguf").custom_model_path == "/m.gguf"
    assert Settings(custom_model_path="/m.gguf").jina_model_path == "/m.gguf"


def test_import_preview_maps_legacy_aliases_to_new_keys() -> None:
    preview = asyncio.run(
        _service().import_preview("JINA_MODEL_PATH=/models/own.gguf\nBENTO_EMBEDDING_THREADS=2\nEMBEDDINGS_PROVIDER=jina")
    )
    items = {item["env_key"]: item for item in preview["items"]}

    assert items["JINA_MODEL_PATH"]["key"] == "custom_model_path"
    assert items["JINA_MODEL_PATH"]["value"] == "/models/own.gguf"
    assert items["BENTO_EMBEDDING_THREADS"]["value"] == 2
    assert items["EMBEDDINGS_PROVIDER"]["key"] == "embeddings_provider"


# --------------------------------------------------------------------------------------
# Leftover `jina` values follow the 0009 rule


def test_saved_jina_with_an_existing_model_becomes_custom(tmp_path: Path) -> None:
    model = tmp_path / "own.gguf"
    model.write_bytes(b"GGUF")
    snapshot = resolve_effective_settings(
        persisted=_saved(embeddings_provider="jina", custom_model_path=str(model), data_dir=str(tmp_path / "data")),
        environ={},
        runtime_mode="desktop",
    )

    assert snapshot.values["embeddings_provider"].value == "custom"
    assert snapshot.values["custom_model_path"].value == str(model)


def test_saved_jina_without_a_model_becomes_disabled(tmp_path: Path) -> None:
    snapshot = resolve_effective_settings(
        persisted=_saved(
            embeddings_provider="jina", custom_model_path=str(tmp_path / "missing.gguf"), data_dir=str(tmp_path / "data")
        ),
        environ={},
        runtime_mode="desktop",
    )

    assert snapshot.values["embeddings_provider"].value == "disabled"


def test_saved_jina_at_the_old_default_path_becomes_custom_with_that_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    legacy = (tmp_path / LEGACY_CUSTOM_MODEL_PATH).resolve()
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"GGUF")
    snapshot = resolve_effective_settings(
        persisted=_saved(embeddings_provider="jina", data_dir=str(data_dir)),
        environ={},
        runtime_mode="desktop",
    )

    assert snapshot.values["embeddings_provider"].value == "custom"
    assert snapshot.values["custom_model_path"].value == LEGACY_CUSTOM_MODEL_PATH


def test_unknown_saved_provider_and_model_fall_back_safely(tmp_path: Path) -> None:
    snapshot = resolve_effective_settings(
        persisted=_saved(embeddings_provider="weird", smart_search_model="gone-model", data_dir=str(tmp_path / "data")),
        environ={},
        runtime_mode="desktop",
    )

    assert snapshot.values["embeddings_provider"].value == "disabled"
    assert snapshot.values["smart_search_model"].value == DEFAULT_SMART_SEARCH_MODEL_ID


def test_jina_from_the_environment_does_not_break_loading(tmp_path: Path) -> None:
    model = tmp_path / "own.gguf"
    model.write_bytes(b"GGUF")
    base = Settings(data_dir=str(tmp_path / "data"))

    missing = load_effective_settings(base, environ={"EMBEDDINGS_PROVIDER": "jina"}, persisted=PersistedSettings())
    present = load_effective_settings(
        base,
        environ={"EMBEDDINGS_PROVIDER": "jina", "JINA_MODEL_PATH": str(model)},
        persisted=PersistedSettings(),
    )

    assert missing.embeddings_provider == "disabled"
    assert present.embeddings_provider == "custom"
    assert present.custom_model_path == str(model)


def test_settings_model_maps_jina_itself(tmp_path: Path) -> None:
    model = tmp_path / "own.gguf"
    model.write_bytes(b"GGUF")

    assert Settings(embeddings_provider="jina", data_dir=str(tmp_path / "data")).embeddings_provider == "disabled"
    assert Settings(embeddings_provider="jina", custom_model_path=str(model)).embeddings_provider == "custom"
    assert Settings(smart_search_model="gone-model").smart_search_model == DEFAULT_SMART_SEARCH_MODEL_ID


def test_android_never_resolves_managed() -> None:
    snapshot = resolve_effective_settings(
        persisted=_saved(embeddings_provider="managed"),
        environ={},
        runtime_mode="desktop",
        policy_values={"platform": "android"},
    )

    assert snapshot.values["embeddings_provider"].value == "disabled"
    assert "managed" not in embeddings_provider_choices("android")
    assert embeddings_provider_choices("auto") == EMBEDDINGS_PROVIDER_CHOICES


# --------------------------------------------------------------------------------------
# Validation


def test_jina_is_rejected_as_new_input() -> None:
    result = _validate({"embeddings_provider": "jina"})

    assert _codes(result) == [("embeddings_provider", "invalid_value")]


def test_custom_requires_a_model_path_unless_an_external_server_is_set() -> None:
    assert _codes(_validate({"embeddings_provider": "custom"})) == [("custom_model_path", "model_path_required")]
    assert _validate({"embeddings_provider": "custom", "custom_model_path": "/models/own.gguf"}).valid is True
    assert _validate({"embeddings_provider": "custom", "embedding_server_url": "http://127.0.0.1:9000"}).valid is True


def test_managed_is_unavailable_on_android() -> None:
    result = _validate({"embeddings_provider": "managed"}, platform="android")

    assert _codes(result) == [("embeddings_provider", "smart_search_unavailable")]
    assert _validate({"embeddings_provider": "mock"}, platform="android").valid is True


@pytest.mark.parametrize("with_catalog", [False, True])
@pytest.mark.parametrize(
    ("model_id", "dims", "valid"),
    [
        ("embeddinggemma-2-q8_0", 512, True),
        ("embeddinggemma-2-q8_0", 128, True),
        ("embeddinggemma-2-q8_0", 300, False),
        ("embeddinggemma-2-q8_0", 1024, False),
        ("qwen3-embedding-0.6b-q8_0", 1024, True),
        ("qwen3-embedding-0.6b-q8_0", 128, False),
    ],
)
def test_managed_dimensions_follow_the_model_matryoshka_list(
    model_id: str, dims: int, valid: bool, with_catalog: bool
) -> None:
    catalog = ManifestCatalog(_manifest(CANONICAL_MANIFEST)[0]) if with_catalog else None
    result = _validate(
        {"embeddings_provider": "managed", "smart_search_model": model_id, "embedding_dimensions": dims},
        catalog=catalog,
    )

    assert result.valid is valid
    if not valid:
        assert _codes(result) == [("embedding_dimensions", "invalid_model_spec")]


def test_default_dimensions_are_valid_for_every_managed_model() -> None:
    for model_id in SMART_SEARCH_MODEL_IDS:
        assert _validate({"embeddings_provider": "managed", "smart_search_model": model_id}).valid is True


def test_dimensions_are_free_outside_managed_mode() -> None:
    assert _validate({"embeddings_provider": "mock", "embedding_dimensions": 300}).valid is True


def test_managed_model_missing_from_the_catalog_is_rejected() -> None:
    specs = tuple(spec for spec in _manifest(CANONICAL_MANIFEST)[0] if spec.model_id == DEFAULT_SMART_SEARCH_MODEL_ID)
    result = _validate(
        {"embeddings_provider": "managed", "smart_search_model": "qwen3-embedding-0.6b-q8_0"},
        catalog=ManifestCatalog(specs),
    )

    assert _codes(result) == [("smart_search_model", "invalid_model_spec")]


@pytest.mark.parametrize(
    ("values", "key"),
    [
        ({"smart_search_model": "unknown-model"}, "smart_search_model"),
        ({"custom_pooling": "max"}, "custom_pooling"),
        ({"embedding_threads": 0}, "embedding_threads"),
        ({"embedding_threads": 65}, "embedding_threads"),
        ({"embedding_dimensions": 0}, "embedding_dimensions"),
    ],
)
def test_constraint_errors(values: dict[str, Any], key: str) -> None:
    assert _codes(_validate(values)) == [(key, "invalid_value")]


def test_embedding_server_url_must_be_http_and_warns_off_device() -> None:
    assert _codes(_validate({"embedding_server_url": "ftp://127.0.0.1/x"})) == [("embedding_server_url", "invalid_url")]

    for local in ("http://127.0.0.1:8080/v1/embeddings", "http://localhost:8080", "http://[::1]:8080"):
        result = _validate({"embedding_server_url": local})
        assert result.valid is True
        assert [issue.code for issue in result.warnings if issue.key == "embedding_server_url"] == []

    remote = _validate({"embedding_server_url": "http://192.168.1.5:8080"})
    assert remote.valid is True
    assert ("embedding_server_url", "embedding_server_not_local") in [(issue.key, issue.code) for issue in remote.warnings]


def test_custom_model_probes(tmp_path: Path) -> None:
    model = tmp_path / "own.gguf"
    model.write_bytes(b"GGUF")
    base = {"embeddings_provider": "custom", "data_dir": str(tmp_path / "data")}

    passed = _validate({**base, "custom_model_path": str(model)}, run_probes=True)
    failed = _validate(
        {**base, "custom_model_path": str(model), "custom_mmproj_path": str(tmp_path / "missing.gguf")}, run_probes=True
    )
    relative = _validate({**base, "custom_model_path": "own.gguf"}, run_probes=True)

    assert passed.valid is True
    assert [(probe.key, probe.status) for probe in passed.probes] == [("data_dir", "passed"), ("custom_model_path", "passed")]
    assert _codes(failed) == [("custom_mmproj_path", "settings_probe_failed")]
    # Relative paths resolve against the data directory's parent, like the runtime.
    assert relative.valid is True


def test_llama_server_path_probe_requires_an_executable(tmp_path: Path) -> None:
    program = tmp_path / "llama-server"
    program.write_text("#!/bin/sh\n", encoding="utf-8")
    program.chmod(0o644)

    assert _codes(_validate({"llama_server_path": str(program)}, run_probes=True)) == [
        ("llama_server_path", "settings_probe_failed")
    ]
    program.chmod(0o755)
    assert _validate({"llama_server_path": str(program)}, run_probes=True).valid is True


def test_runtime_settings_restart_services() -> None:
    result = _validate({"embedding_threads": 1 if SETTINGS_BY_KEY["embedding_threads"].default != 1 else 2})

    assert result.restart_plan.mode == SettingApplyMode.RESTART_SERVICES
    assert result.restart_plan.services == ("api", "worker")


# --------------------------------------------------------------------------------------
# Advanced and hidden flags


def test_advanced_settings_are_the_ai_runtime_knobs() -> None:
    assert ADVANCED_SETTINGS == ADVANCED_KEYS
    assert all(SETTINGS_BY_KEY[key].group == "ai" for key in ADVANCED_SETTINGS)
    assert all(is_advanced(key) for key in ADVANCED_KEYS)
    assert not any(is_advanced(key) for key in ("embeddings_provider", "smart_search_model", "ocr_provider"))


def test_smart_search_model_is_visible_only_with_more_than_one_model(monkeypatch: pytest.MonkeyPatch) -> None:
    assert len(SMART_SEARCH_MODEL_IDS) > 1
    assert is_hidden("smart_search_model") is False
    assert is_hidden("smart_search_model", "android") is True
    assert smart_search_model_choices("android") == ()
    assert not any(is_hidden(key) for key in SETTINGS_BY_KEY if key != "smart_search_model")

    monkeypatch.setattr(settings_registry, "SMART_SEARCH_MODEL_IDS", (DEFAULT_SMART_SEARCH_MODEL_ID,))
    assert is_hidden("smart_search_model") is True


# --------------------------------------------------------------------------------------
# Desktop `model-file` probe


def test_model_file_probe_reads_custom_model_path(monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path) -> None:
    model = tmp_path / "own.gguf"
    model.write_bytes(b"GGUF")
    monkeypatch.setattr(launcher, "get_settings", lambda: Settings(data_dir=str(tmp_path), custom_model_path=str(model)))

    assert launcher.main(("probe", "model-file")) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == {"probe": "model-file", "status": "ok"}
    assert str(model) not in output


def test_model_file_probe_fails_without_a_configured_path(monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(launcher, "get_settings", lambda: Settings(data_dir=str(tmp_path)))

    assert launcher.main(("probe", "model-file")) == 1
    assert json.loads(capsys.readouterr().out) == {"code": "not_readable", "probe": "model-file", "status": "failed"}
