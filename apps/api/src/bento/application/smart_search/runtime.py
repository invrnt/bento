"""Smart search runtime: one embedding server for the active space, owned by the worker.

The worker calls `SmartSearchRuntimeService.run()` next to its job loop. Each tick asks the target source what
should be served (`RuntimeTarget`, or `None` when smart search is off or the model is not installed), starts or
restarts the server through `EmbeddingRuntimePort`, and stops it when the target goes away. How to reach the
running server is published in `<data_dir>/run/embedder.json` (mode 0600) as
`{space_id, base_url, api_key_file, pid, started_at}`; the API process reads it with `EndpointFileReader` and
treats "missing or unusable" as "vector search unavailable". The key itself never appears in the file.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from bento.domain.smart_search import (
    DEFAULT_CHUNK_TOKENS,
    EmbeddingSpace,
    InvalidEmbeddingSpaceError,
    InvalidModelSpecError,
    ModelFile,
    ModelFileRole,
    ModelSpec,
    Pooling,
    SmartSearchState,
    SmartSearchStatus,
    parse_space_id,
)
from bento.ports.models import EmbeddingRuntimePort, EndpointInfo, ModelCatalogPort, ModelStorePort

LOGGER = logging.getLogger("bento.smart_search.runtime")

RUN_DIR_NAME = "run"
ENDPOINT_FILE_NAME = "embedder.json"
SUPERVISE_INTERVAL_SECONDS = 5.0
CUSTOM_MODEL_ID = "custom"
_CUSTOM_PLACEHOLDER_URL = "https://custom-model.invalid/"
_CUSTOM_PLACEHOLDER_SHA256 = "0" * 64
_URL_PREFIXES = ("http://", "https://", "http+unix://")


class EmbeddingRuntimeUnavailableError(RuntimeError):
    """Smart search is off, or its model is not installed: there is nothing to serve."""


class EmbeddingRuntimeFailedError(RuntimeError):
    """The server could not be started after the restart budget (`error(runtime)`)."""


@dataclass(frozen=True, slots=True)
class RuntimeTarget:
    spec: ModelSpec
    space: EmbeddingSpace
    weights: Path


class RuntimeTargetSourcePort(Protocol):
    async def target(self) -> RuntimeTarget | None:
        """What the server should serve now; `None` stops it. Cheap: called every few seconds."""
        ...


class RuntimeStatusSinkPort(Protocol):
    """Feeds `runtime_ready` / `fail(runtime)` into the smart search state machine
    (`SmartSearchActivationService.runtime_ready` / `runtime_failed`; results are ignored)."""

    async def runtime_ready(self, space_id: str) -> object: ...

    async def runtime_failed(self, space_id: str) -> object: ...


SERVING_STATES = frozenset({SmartSearchState.STARTING, SmartSearchState.INDEXING, SmartSearchState.READY})


class StatusRuntimeTargets:
    """Managed mode: serve the space the persisted smart search status names, once its weights are installed.

    `starting`, `indexing` and `ready` serve; every other state (off, downloading, error, ...) stops the server.
    After `error(runtime)` → `retry` the status is `starting` again, so the next check starts it."""

    def __init__(
        self,
        *,
        catalog: ModelCatalogPort,
        store: ModelStorePort,
        load_status: Callable[[], Awaitable[SmartSearchStatus]],
    ) -> None:
        self._catalog = catalog
        self._store = store
        self._load_status = load_status

    async def target(self) -> RuntimeTarget | None:
        try:
            status = await self._load_status()
        except Exception as exc:  # noqa: BLE001 - an unreadable status serves nothing
            LOGGER.debug("Smart search status unavailable: %s", exc.__class__.__name__)
            return None
        if status.state not in SERVING_STATES or not status.space_id:
            return None
        try:
            model_id, revision, dims = parse_space_id(status.space_id)
        except InvalidEmbeddingSpaceError:
            return None
        spec = self._catalog.get(model_id, revision) if revision else None
        if spec is None:
            return None
        try:
            space = spec.space(dims)
        except InvalidModelSpecError:
            return None
        weights = self._store.path_for(spec, spec.weights)
        if not weights_installed(weights, spec):
            return None
        return RuntimeTarget(spec=spec, space=space, weights=weights)


def weights_installed(weights: Path, spec: ModelSpec) -> bool:
    """The verified file is in place (the store renames `.part` only after the sha256 matched)."""
    try:
        return weights.is_file() and weights.stat().st_size == spec.weights.size_bytes
    except OSError:
        return False


# --------------------------------------------------------------------------------------
# `<data_dir>/run/embedder.json`


def run_dir_path(data_dir: Path) -> Path:
    return data_dir / RUN_DIR_NAME


def endpoint_file_path(data_dir: Path) -> Path:
    return run_dir_path(data_dir) / ENDPOINT_FILE_NAME


def _key_file_text(path: Path) -> str:
    text = str(path)
    return "" if text in {"", "."} else text


def write_endpoint_file(path: Path, info: EndpointInfo) -> None:
    """Atomically write the endpoint file with mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    payload = {
        "space_id": info.space_id,
        "base_url": info.base_url,
        "api_key_file": _key_file_text(info.api_key_file),
        "pid": info.pid,
        "started_at": info.started_at,
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def read_endpoint_file(path: Path) -> EndpointInfo | None:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    space_id = payload.get("space_id")
    base_url = payload.get("base_url")
    key_file = payload.get("api_key_file", "")
    pid = payload.get("pid")
    started_at = payload.get("started_at", "")
    if not isinstance(space_id, str) or not space_id:
        return None
    if not isinstance(base_url, str) or not base_url.startswith(_URL_PREFIXES):
        return None
    if not isinstance(key_file, str) or not isinstance(started_at, str):
        return None
    if pid is not None and (not isinstance(pid, int) or isinstance(pid, bool)):
        return None
    return EndpointInfo(
        space_id=space_id,
        base_url=base_url,
        api_key_file=Path(key_file) if key_file else Path(""),
        pid=pid,
        started_at=started_at,
    )


def remove_endpoint_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


class EndpointFileReader:
    """Read side for the API process; re-reads the file only when it changes."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._stamp: tuple[int, int] | None = None
        self._info: EndpointInfo | None = None

    @property
    def path(self) -> Path:
        return self._path

    def __call__(self) -> EndpointInfo | None:
        try:
            stat = self._path.stat()
        except OSError:
            self._stamp, self._info = None, None
            return None
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp != self._stamp:
            self._stamp, self._info = stamp, read_endpoint_file(self._path)
        return self._info


class EndpointFileRuntime:
    """`EmbeddingRuntimePort` for processes that never run the server (the API): only `endpoint()` works."""

    def __init__(self, path: Path) -> None:
        self._reader = EndpointFileReader(path)

    async def ensure(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> EndpointInfo:
        del spec, weights
        info = self._reader()
        if info is None:
            raise EmbeddingRuntimeUnavailableError(f"No embedding server is running for {space.id}")
        return info

    async def stop(self) -> None:
        return None

    async def health(self) -> bool:
        return self._reader() is not None

    def endpoint(self) -> EndpointInfo | None:
        return self._reader()


# --------------------------------------------------------------------------------------
# Custom models (Advanced: the person's own GGUF)


def custom_model_spec(
    *,
    file_name: str,
    identity: str,
    size_bytes: int,
    mtime_ns: int,
    dims: int,
    pooling: str | None = None,
    query_prefix: str | None = None,
    document_prefix: str | None = None,
    context_tokens: int = 2048,
    ubatch_tokens: int = 2048,
    chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
) -> ModelSpec:
    """A synthetic, never-downloaded spec for `custom` mode. The revision changes with the file, so a new
    file is a new space. Prefixes may be plain prefixes or templates containing `{q}` / `{text}`."""
    name = file_name if file_name and not file_name.startswith(".") and "/" not in file_name else "model.gguf"
    if "\\" in name:
        name = "model.gguf"
    revision = hashlib.sha256(f"{identity}\0{size_bytes}\0{mtime_ns}".encode("utf-8")).hexdigest()[:12]
    try:
        chosen_pooling = Pooling((pooling or Pooling.MEAN.value).strip().lower())
    except ValueError:
        chosen_pooling = Pooling.MEAN
    query = query_prefix or ""
    document = document_prefix or ""
    return ModelSpec(
        model_id=CUSTOM_MODEL_ID,
        revision=revision,
        display_name="Custom model",
        license_spdx="NOASSERTION",
        source_url=_CUSTOM_PLACEHOLDER_URL,
        files=(
            ModelFile(
                name=name,
                role=ModelFileRole.WEIGHTS,
                urls=(_CUSTOM_PLACEHOLDER_URL,),
                size_bytes=max(1, size_bytes),
                sha256=_CUSTOM_PLACEHOLDER_SHA256,
            ),
        ),
        native_dims=dims,
        matryoshka_dims=(dims,),
        default_dims=dims,
        pooling=chosen_pooling,
        context_tokens=context_tokens,
        ubatch_tokens=ubatch_tokens,
        query_template=query if "{q}" in query else f"{query}{{q}}",
        document_template=document if "{text}" in document else f"{document}{{text}}",
        chunk_tokens=chunk_tokens,
    )


# --------------------------------------------------------------------------------------
# The worker-side supervisor


class SmartSearchRuntimeService:
    def __init__(
        self,
        *,
        runtime: EmbeddingRuntimePort,
        targets: RuntimeTargetSourcePort,
        endpoint_file: Path,
        status: RuntimeStatusSinkPort | None = None,
        stale_cleanup: Callable[[EndpointInfo], None] | None = None,
        interval_seconds: float = SUPERVISE_INTERVAL_SECONDS,
    ) -> None:
        self._runtime = runtime
        self._targets = targets
        self._endpoint_file = endpoint_file
        self._status = status
        self._stale_cleanup = stale_cleanup
        self._interval = interval_seconds
        self._lock: asyncio.Lock | None = None
        self._serving: EndpointInfo | None = None
        self._model: tuple[ModelSpec, EmbeddingSpace] | None = None
        self._failed_space: str | None = None
        self._checked_stale = False

    @property
    def endpoint_file(self) -> Path:
        return self._endpoint_file

    @property
    def failed_space(self) -> str | None:
        return self._failed_space

    def current_endpoint(self) -> EndpointInfo | None:
        return self._serving

    def current_model(self) -> tuple[ModelSpec, EmbeddingSpace] | None:
        """The model and space being served (the status may pick another model or dims than the settings)."""
        return self._model

    def attach_status(self, status: RuntimeStatusSinkPort | None) -> None:
        """Late binding: the activation service is built after the runtime (it takes our hooks)."""
        self._status = status

    async def available(self) -> bool:
        target = await self._targets.target()
        return target is not None and target.space.id != self._failed_space

    async def start_now(self, target: RuntimeTarget) -> None:
        """`starting` hook: start (or restart) the server for `target` right away."""
        async with self._guard():
            self._clean_stale_once()
            if self._failed_space is not None:
                await self._runtime.stop()  # a retry gets a fresh restart budget
                self._failed_space = None
            try:
                await self._ensure(target)
            except EmbeddingRuntimeFailedError:
                return  # already reported as `fail(runtime)`

    async def ensure_running(self) -> EndpointInfo:
        """Used by the worker's provider before embedding: start the server now if needed."""
        target = await self._targets.target()
        if target is None:
            raise EmbeddingRuntimeUnavailableError("Smart search has no installed model to serve")
        async with self._guard():
            self._clean_stale_once()
            if self._failed_space == target.space.id:
                raise EmbeddingRuntimeFailedError("The embedding server could not be started")
            if self._serving is not None and self._serving.space_id == target.space.id:
                if await self._runtime.health():
                    return self._serving
                remove_endpoint_file(self._endpoint_file)
                self._serving = None
            return await self._ensure(target)

    async def tick(self) -> None:
        """One supervision step: start, restart (with the runtime's backoff) or stop."""
        target = await self._targets.target()
        async with self._guard():
            self._clean_stale_once()
            if target is None:
                if self._serving is not None:
                    LOGGER.info("Smart search is off or its model was removed; stopping the embedding server")
                await self._stop()
                self._failed_space = None
                return
            if self._failed_space == target.space.id:
                return
            if self._serving is not None and self._serving.space_id == target.space.id:
                if await self._runtime.health():
                    return
                remove_endpoint_file(self._endpoint_file)  # the API falls back to FTS meanwhile
                self._serving = None
            try:
                await self._ensure(target)
            except EmbeddingRuntimeFailedError:
                return

    async def retry(self) -> None:
        """After `error(runtime)` → `retry`: forget the give-up and reset the restart budget."""
        async with self._guard():
            self._failed_space = None
            await self._stop()

    async def stop(self) -> None:
        async with self._guard():
            await self._stop()

    async def run(self, stop_event: asyncio.Event) -> None:
        try:
            while not stop_event.is_set():
                try:
                    await self.tick()
                except Exception as exc:  # noqa: BLE001 - the loop must survive one bad check
                    LOGGER.warning("Smart search runtime check failed: %s", exc.__class__.__name__)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=self._interval)
                except TimeoutError:
                    pass
        finally:
            await self.stop()

    # ----------------------------------------------------------------------------------

    def _guard(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _clean_stale_once(self) -> None:
        if self._checked_stale:
            return
        self._checked_stale = True
        stale = read_endpoint_file(self._endpoint_file)
        if stale is None:
            remove_endpoint_file(self._endpoint_file)
            return
        if self._stale_cleanup is not None:
            try:
                self._stale_cleanup(stale)
            except Exception as exc:  # noqa: BLE001 - best effort
                LOGGER.debug("Leftover embedding server cleanup skipped: %s", exc.__class__.__name__)
        remove_endpoint_file(self._endpoint_file)

    async def _ensure(self, target: RuntimeTarget) -> EndpointInfo:
        try:
            info = await self._runtime.ensure(target.spec, target.space, target.weights)
        except Exception as exc:  # noqa: BLE001 - every start failure is `error(runtime)`
            LOGGER.warning("The embedding server for %s could not start: %s", target.space.id, exc.__class__.__name__)
            self._failed_space = target.space.id
            self._serving = None
            remove_endpoint_file(self._endpoint_file)
            await self._notify(failed=True, space_id=target.space.id)
            raise EmbeddingRuntimeFailedError("The embedding server could not be started") from exc
        self._model = (target.spec, target.space)
        if info != self._serving:
            write_endpoint_file(self._endpoint_file, info)
            self._serving = info
            await self._notify(failed=False, space_id=target.space.id)
        return info

    async def _stop(self) -> None:
        await self._runtime.stop()
        self._serving = None
        self._model = None
        remove_endpoint_file(self._endpoint_file)

    async def _notify(self, *, failed: bool, space_id: str) -> None:
        if self._status is None:
            return
        try:
            if failed:
                await self._status.runtime_failed(space_id)
            else:
                await self._status.runtime_ready(space_id)
        except Exception as exc:  # noqa: BLE001 - status bookkeeping never breaks the runtime
            LOGGER.warning("Could not record the smart search runtime state: %s", exc.__class__.__name__)


class SmartSearchRuntimeHooks:
    """`SmartSearchHooksPort` of the activation service, in the worker: the runtime side of `starting`
    (after verification or a runtime retry) and of cancel/remove."""

    def __init__(self, service: SmartSearchRuntimeService) -> None:
        self._service = service

    async def starting(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> None:
        await self._service.start_now(RuntimeTarget(spec=spec, space=space, weights=weights))

    async def update_ready(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> None:
        del weights
        # The active space keeps serving until the blue/green flip (`reembed`); the supervisor then follows
        # the status to the new space.
        LOGGER.info("Smart search model %s@%s is ready for %s", spec.model_id, spec.revision, space.id)

    async def stopped(self, space_id: str | None) -> None:
        del space_id
        await self._service.stop()
