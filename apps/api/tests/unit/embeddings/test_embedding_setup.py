from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from bento.adapters.embeddings import DisabledEmbeddingProvider, LlamaCppEmbeddingProvider, MockEmbeddingProvider
from bento.adapters.runtime.embedding_setup import (
    LEGACY_DEFAULT_SERVER_URL,
    SettingsRuntimeTargets,
    build_query_provider,
    build_runtime,
    build_worker_embedding,
    configured_server_url,
    embedding_threads,
)
from bento.adapters.runtime.llama_server_process import ExternalEmbeddingServer, LlamaServerProcess
from bento.application.smart_search.runtime import endpoint_file_path, write_endpoint_file
from bento.domain.smart_search import ModelFile, ModelSpec, parse_manifest
from bento.ports.models import EndpointInfo, InstalledModel

MANIFEST = json.loads((Path(__file__).parents[1] / "smart_search" / "manifest_v1.json").read_text(encoding="utf-8"))
SPECS, DEFAULT_ID = parse_manifest(MANIFEST)
# Same model, a 4-byte weights file, so "installed" needs no 300 MB fixture.
EG2 = replace(SPECS[0], files=(replace(SPECS[0].weights, size_bytes=4),))
QWEN = SPECS[1]


class FakeCatalog:
    def default(self) -> ModelSpec:
        return EG2

    def get(self, model_id: str, revision: str | None = None) -> ModelSpec | None:
        del revision
        return {EG2.model_id: EG2, QWEN.model_id: QWEN}.get(model_id)

    def all(self) -> tuple[ModelSpec, ...]:
        return (EG2, QWEN)


class FakeStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def installed(self) -> tuple[InstalledModel, ...]:
        return ()

    def path_for(self, spec: ModelSpec, file: ModelFile) -> Path:
        return self.root / spec.model_id / spec.revision / file.name

    def part_path_for(self, spec: ModelSpec, file: ModelFile) -> Path:
        return self.path_for(spec, file).with_name(f"{file.name}.part")

    def free_bytes(self) -> int:
        return 10**12

    def remove(self, spec: ModelSpec) -> int:
        del spec
        return 0

    def verify(self, spec: ModelSpec) -> bool:
        del spec
        return True


def settings(tmp_path: Path, **overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "data_dir": str(tmp_path / "data"),
        "embeddings_provider": "managed",
        "embedding_dimensions": 512,
        "embedding_server_url": "",
        "smart_search_model": "",
        "llama_server_path": "",
        "embedding_threads": 0,
        "custom_model_path": "",
        "custom_pooling": "mean",
        "custom_query_prefix": "",
        "custom_document_prefix": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def install(store: FakeStore, spec: ModelSpec, size: int = 4) -> Path:
    path = store.path_for(spec, spec.weights)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"g" * size)
    return path


def test_mock_and_disabled_need_no_runtime(tmp_path: Path) -> None:
    mock = build_worker_embedding(settings(tmp_path, embeddings_provider="mock", embedding_dimensions=8))
    assert isinstance(mock.provider, MockEmbeddingProvider) and mock.runtime is None and mock.dimensions == 8
    disabled = build_worker_embedding(settings(tmp_path, embeddings_provider="disabled"))
    assert isinstance(disabled.provider, DisabledEmbeddingProvider) and disabled.runtime is None


def test_managed_without_catalog_stays_off(tmp_path: Path) -> None:
    setup = build_worker_embedding(settings(tmp_path))
    assert isinstance(setup.provider, DisabledEmbeddingProvider)
    assert setup.runtime is None


def test_managed_target_requires_the_installed_weights(tmp_path: Path) -> None:
    store = FakeStore(tmp_path / "models")
    targets = SettingsRuntimeTargets(settings(tmp_path), catalog=FakeCatalog(), store=store)
    assert asyncio.run(targets.target()) is None  # not downloaded yet
    model = targets.model()
    assert model is not None and model[1].id == EG2.space(512).id

    install(store, EG2, size=3)
    assert asyncio.run(targets.target()) is None  # a partial or wrong file never runs

    weights = install(store, EG2)
    target = asyncio.run(targets.target())
    assert target is not None
    assert target.weights == weights and target.space.dims == 512 and target.spec == EG2


def test_managed_dims_and_model_come_from_settings(tmp_path: Path) -> None:
    store = FakeStore(tmp_path / "models")
    explicit = SettingsRuntimeTargets(settings(tmp_path, embedding_dimensions=256), catalog=FakeCatalog(), store=store)
    assert explicit.model() is not None and explicit.model()[1].dims == 256  # type: ignore[index]
    invalid = SettingsRuntimeTargets(settings(tmp_path, embedding_dimensions=300), catalog=FakeCatalog(), store=store)
    assert invalid.model()[1].dims == EG2.default_dims  # type: ignore[index]
    qwen = SettingsRuntimeTargets(
        settings(tmp_path, smart_search_model=QWEN.model_id, embedding_dimensions=1024), catalog=FakeCatalog(), store=store
    )
    assert qwen.model()[1].id == QWEN.space(1024).id  # type: ignore[index]


def test_worker_embedding_for_managed_wires_provider_and_runtime(tmp_path: Path) -> None:
    store = FakeStore(tmp_path / "models")
    install(store, EG2)
    setup = build_worker_embedding(settings(tmp_path), catalog=FakeCatalog(), store=store, environ={"PATH": ""})

    assert isinstance(setup.provider, LlamaCppEmbeddingProvider)
    assert setup.provider.space == EG2.space(512)
    assert setup.dimensions == 512 and setup.chunk_tokens == 512
    assert setup.runtime is not None
    assert setup.runtime.endpoint_file == (tmp_path / "data").resolve() / "run" / "embedder.json"
    assert asyncio.run(setup.provider.is_enabled()) is True


def test_custom_model_target(tmp_path: Path) -> None:
    model = tmp_path / "models" / "mine.gguf"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"gguf")
    values = settings(
        tmp_path,
        embeddings_provider="custom",
        custom_model_path=str(model),
        embedding_dimensions=384,
        custom_pooling="cls",
        custom_query_prefix="query: ",
        custom_document_prefix="passage: ",
    )

    target = asyncio.run(SettingsRuntimeTargets(values).target())

    assert target is not None
    assert target.weights == model
    assert target.spec.model_id == "custom" and target.space.dims == 384
    assert target.spec.format_query("playa") == "query: playa"
    assert asyncio.run(SettingsRuntimeTargets(settings(tmp_path, embeddings_provider="custom")).target()) is None


def test_server_url_and_threads(tmp_path: Path) -> None:
    assert configured_server_url(settings(tmp_path, embedding_server_url=LEGACY_DEFAULT_SERVER_URL)) is None
    assert configured_server_url(settings(tmp_path, embedding_server_url="  ")) is None
    assert configured_server_url(settings(tmp_path, embedding_server_url="http://llama:8080/v1/embeddings")) == "http://llama:8080"
    assert configured_server_url(settings(tmp_path, embedding_server_url="http://127.0.0.1:9000/")) == "http://127.0.0.1:9000"

    assert embedding_threads(settings(tmp_path, embedding_threads=3)) == 3
    assert embedding_threads(settings(tmp_path, embedding_threads=0), cpu_count=16) == 4
    assert embedding_threads(settings(tmp_path, embedding_threads=None), cpu_count=2) == 1

    assert isinstance(build_runtime(settings(tmp_path, embedding_server_url="http://llama:8080")), ExternalEmbeddingServer)
    assert isinstance(build_runtime(settings(tmp_path), environ={"PATH": ""}), LlamaServerProcess)


def test_query_provider_reads_the_workers_endpoint_file(tmp_path: Path) -> None:
    async def scenario() -> None:
        values = settings(tmp_path)
        provider = build_query_provider(values, catalog=FakeCatalog())
        assert isinstance(provider, LlamaCppEmbeddingProvider)
        assert await provider.is_enabled() is False

        write_endpoint_file(
            endpoint_file_path((tmp_path / "data").resolve()),
            EndpointInfo(EG2.space(512).id, "http://127.0.0.1:1", tmp_path / "k.key", 1, "t"),
        )
        assert await provider.is_enabled() is True

        assert isinstance(build_query_provider(settings(tmp_path, embeddings_provider="disabled")), DisabledEmbeddingProvider)
        assert isinstance(build_query_provider(values), DisabledEmbeddingProvider)  # no catalog: nothing to query

    asyncio.run(scenario())


def test_managed_query_provider_follows_the_space_the_worker_serves(tmp_path: Path) -> None:
    async def scenario() -> None:
        provider = build_query_provider(settings(tmp_path, embedding_dimensions=512), catalog=FakeCatalog())
        assert isinstance(provider, LlamaCppEmbeddingProvider)
        assert provider.space.id == EG2.space(512).id  # nothing served yet: the settings decide

        # The activation status picked 256 dims; the worker serves that space, so queries must use it too.
        write_endpoint_file(
            endpoint_file_path((tmp_path / "data").resolve()),
            EndpointInfo(EG2.space(256).id, "http://127.0.0.1:1", tmp_path / "k.key", 1, "t"),
        )
        assert provider.space.id == EG2.space(256).id
        assert await provider.is_enabled() is True

    asyncio.run(scenario())
