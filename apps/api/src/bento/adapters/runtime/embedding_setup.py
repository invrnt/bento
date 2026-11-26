"""Smart search wiring from settings, shared by the worker (owns the server) and the API (reads embedder.json).

Providers (`embeddings_provider`):
- `disabled`: no vectors. `mock`: deterministic hash vectors (tests, development).
- `managed`: the manifest model the person activated, served by a Bento-supervised llama-server.
- `custom`: the person's own GGUF (`custom_model_path`, Advanced), served the same way.
With `embedding_server_url` set, Bento spawns no server and talks to that one instead.
"""

from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bento.adapters.embeddings.disabled import DisabledEmbeddingProvider
from bento.adapters.embeddings.llama_cpp import LlamaCppEmbeddingProvider
from bento.adapters.embeddings.mock import MockEmbeddingProvider
from bento.adapters.runtime.llama_server_process import (
    ExternalEmbeddingServer,
    LlamaServerProcess,
    normalize_server_url,
    resolve_llama_server_binary,
)
from bento.application.smart_search.runtime import (
    EndpointFileReader,
    RuntimeStatusSinkPort,
    RuntimeTarget,
    SmartSearchRuntimeHooks,
    SmartSearchRuntimeService,
    StatusRuntimeTargets,
    custom_model_spec,
    endpoint_file_path,
    run_dir_path,
    weights_installed,
)
from bento.domain.smart_search import (
    DEFAULT_CHUNK_TOKENS,
    EmbeddingSpace,
    InvalidEmbeddingSpaceError,
    InvalidModelSpecError,
    ModelSpec,
    SmartSearchStatus,
    default_embedding_threads,
    parse_space_id,
)
from bento.ports.models import EndpointInfo, ModelCatalogPort, ModelStorePort

LOGGER = logging.getLogger("bento.embeddings.setup")

SMART_PROVIDERS = frozenset({"managed", "custom"})
# The pre-Stage-24 default pointed at a hand-started server; it no longer means "external server".
LEGACY_DEFAULT_SERVER_URL = "http://127.0.0.1:8080/v1/embeddings"


@dataclass(frozen=True, slots=True)
class WorkerEmbedding:
    provider: Any  # EmbeddingVectorProviderPort | SpaceEmbeddingProviderPort (application/indexing/embedding.py)
    runtime: SmartSearchRuntimeService | None
    dimensions: int
    chunk_tokens: int = DEFAULT_CHUNK_TOKENS

    @property
    def hooks(self) -> SmartSearchRuntimeHooks | None:
        """For the activation service (`SmartSearchHooksPort`): start on `starting`, stop on cancel/remove."""
        return SmartSearchRuntimeHooks(self.runtime) if self.runtime is not None else None


def data_dir_of(settings: Any) -> Path:
    return Path(str(settings.data_dir)).expanduser().resolve()


def configured_server_url(settings: Any) -> str | None:
    raw = str(getattr(settings, "embedding_server_url", "") or "").strip()
    if raw == LEGACY_DEFAULT_SERVER_URL:
        return None
    return normalize_server_url(raw)


def embedding_threads(settings: Any, cpu_count: int | None = None) -> int:
    value = getattr(settings, "embedding_threads", None)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return default_embedding_threads(cpu_count or os.cpu_count() or 1)


def default_model_ports(settings: Any) -> tuple[ModelCatalogPort | None, ModelStorePort | None]:
    """The models-download adapters: the packaged manifest catalog and the `<data_dir>/models` store."""
    try:
        models = importlib.import_module("bento.infrastructure.models")
        catalog: ModelCatalogPort = models.packaged_model_catalog()
        store: ModelStorePort = models.model_store(data_dir_of(settings))
    except Exception as exc:  # noqa: BLE001 - managed mode then reports "not installed"
        LOGGER.warning("Managed smart search models are unavailable: %s", exc.__class__.__name__)
        return None, None
    return catalog, store


class SettingsRuntimeTargets:
    """`RuntimeTargetSourcePort` from settings: which model and space to serve, and whether it is installed.

    In `managed` mode with `load_status` (the worker), the persisted smart search status decides the space and
    when to serve (`StatusRuntimeTargets`); without it the settings name the model and dims."""

    def __init__(
        self,
        settings: Any,
        *,
        catalog: ModelCatalogPort | None = None,
        store: ModelStorePort | None = None,
        load_status: Callable[[], Awaitable[SmartSearchStatus]] | None = None,
    ) -> None:
        self._settings = settings
        self._catalog = catalog
        self._store = store
        self._status_targets = (
            StatusRuntimeTargets(catalog=catalog, store=store, load_status=load_status)
            if catalog is not None and store is not None and load_status is not None
            else None
        )

    @property
    def provider(self) -> str:
        return str(getattr(self._settings, "embeddings_provider", "disabled"))

    def model(self) -> tuple[ModelSpec, EmbeddingSpace] | None:
        """The configured spec and space, whether or not its file is installed yet."""
        if self.provider == "managed":
            spec = self._managed_spec()
            return None if spec is None else (spec, spec.space(self._managed_dims(spec)))
        if self.provider == "custom":
            custom = self._custom()
            return None if custom is None else (custom[0], custom[0].space())
        return None

    async def target(self) -> RuntimeTarget | None:
        if self.provider == "managed":
            if self._status_targets is not None:
                return await self._status_targets.target()
            spec = self._managed_spec()
            if spec is None or self._store is None:
                return None
            weights = self._store.path_for(spec, spec.weights)
            if not weights_installed(weights, spec):
                return None
            return RuntimeTarget(spec=spec, space=spec.space(self._managed_dims(spec)), weights=weights)
        if self.provider == "custom":
            custom = self._custom()
            if custom is None:
                return None
            spec, path = custom
            return RuntimeTarget(spec=spec, space=spec.space(), weights=path)
        return None

    def _managed_spec(self) -> ModelSpec | None:
        if self._catalog is None:
            return None
        model_id = str(getattr(self._settings, "smart_search_model", "") or "").strip()
        spec = self._catalog.get(model_id) if model_id else None
        return spec or self._catalog.default()

    def _managed_dims(self, spec: ModelSpec) -> int:
        dims = getattr(self._settings, "embedding_dimensions", None)
        if isinstance(dims, int) and dims in spec.matryoshka_dims:
            return dims
        return spec.default_dims

    def _custom(self) -> tuple[ModelSpec, Path] | None:
        configured = str(getattr(self._settings, "custom_model_path", "") or "").strip()
        if not configured:
            return None
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = (data_dir_of(self._settings).parent / path).resolve()
        try:
            stat = path.stat()
        except OSError:
            return None
        if not path.is_file():
            return None
        dims = getattr(self._settings, "embedding_dimensions", 0)
        try:
            spec = custom_model_spec(
                file_name=path.name,
                identity=str(path),
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                dims=int(dims),
                pooling=getattr(self._settings, "custom_pooling", None),
                query_prefix=getattr(self._settings, "custom_query_prefix", None),
                document_prefix=getattr(self._settings, "custom_document_prefix", None),
            )
        except (InvalidModelSpecError, TypeError, ValueError):
            return None
        return spec, path


def build_runtime(
    settings: Any, *, environ: Mapping[str, str] | None = None
) -> LlamaServerProcess | ExternalEmbeddingServer:
    url = configured_server_url(settings)
    if url:
        return ExternalEmbeddingServer(url)
    setting_path = str(getattr(settings, "llama_server_path", "") or "").strip() or None
    return LlamaServerProcess(
        run_dir=run_dir_path(data_dir_of(settings)),
        binary=resolve_llama_server_binary(setting_path, environ=environ),
        threads=embedding_threads(settings),
        environ=environ,
    )


def build_worker_embedding(
    settings: Any,
    *,
    catalog: ModelCatalogPort | None = None,
    store: ModelStorePort | None = None,
    status: RuntimeStatusSinkPort | None = None,
    load_status: Callable[[], Awaitable[SmartSearchStatus]] | None = None,
    environ: Mapping[str, str] | None = None,
) -> WorkerEmbedding:
    provider = str(getattr(settings, "embeddings_provider", "disabled"))
    dimensions = int(getattr(settings, "embedding_dimensions", 768))
    if provider == "mock":
        return WorkerEmbedding(provider=MockEmbeddingProvider(dimensions=dimensions), runtime=None, dimensions=dimensions)
    if provider not in SMART_PROVIDERS:
        return WorkerEmbedding(provider=DisabledEmbeddingProvider(), runtime=None, dimensions=dimensions)
    targets = SettingsRuntimeTargets(settings, catalog=catalog, store=store, load_status=load_status)
    model = targets.model()
    if model is None:
        LOGGER.warning("Smart search is on (%s) but no model is configured; embeddings stay off", provider)
        return WorkerEmbedding(provider=DisabledEmbeddingProvider(), runtime=None, dimensions=dimensions)
    spec, space = model
    runtime = build_runtime(settings, environ=environ)
    service = SmartSearchRuntimeService(
        runtime=runtime,
        targets=targets,
        endpoint_file=endpoint_file_path(data_dir_of(settings)),
        status=status,
        stale_cleanup=runtime.terminate_stale if isinstance(runtime, LlamaServerProcess) else None,
    )
    return WorkerEmbedding(
        provider=LlamaCppEmbeddingProvider(
            spec=spec,
            space=space,
            endpoint=service.current_endpoint,
            ensure=service.ensure_running,
            available=service.available,
            model_source=service.current_model,
        ),
        runtime=service,
        dimensions=space.dims,
        chunk_tokens=spec.chunk_tokens,
    )


def build_query_provider(
    settings: Any, *, catalog: ModelCatalogPort | None = None
) -> LlamaCppEmbeddingProvider | MockEmbeddingProvider | DisabledEmbeddingProvider:
    """For the API process: embeds queries through the worker's server (`embedder.json`); never spawns one."""
    provider = str(getattr(settings, "embeddings_provider", "disabled"))
    if provider == "mock":
        return MockEmbeddingProvider(dimensions=int(getattr(settings, "embedding_dimensions", 768)))
    if provider not in SMART_PROVIDERS:
        return DisabledEmbeddingProvider()
    model = SettingsRuntimeTargets(settings, catalog=catalog).model()
    if model is None:
        return DisabledEmbeddingProvider()
    spec, space = model
    endpoint = EndpointFileReader(endpoint_file_path(data_dir_of(settings)))
    return LlamaCppEmbeddingProvider(
        spec=spec,
        space=space,
        endpoint=endpoint,
        model_source=_served_model(endpoint, catalog) if provider == "managed" and catalog is not None else None,
    )


def _served_model(
    endpoint: Callable[[], EndpointInfo | None], catalog: ModelCatalogPort
) -> Callable[[], tuple[ModelSpec, EmbeddingSpace] | None]:
    """Managed mode: the model and dims the worker serves now (the activation status may have picked other
    dims or a model than the settings name), so queries land in the same space as the documents."""

    def current() -> tuple[ModelSpec, EmbeddingSpace] | None:
        info = endpoint()
        if info is None:
            return None
        try:
            model_id, revision, dims = parse_space_id(info.space_id)
        except InvalidEmbeddingSpaceError:
            return None
        spec = catalog.get(model_id, revision) if revision else None
        if spec is None:
            return None
        try:
            return spec, spec.space(dims)
        except InvalidModelSpecError:
            return None

    return current

