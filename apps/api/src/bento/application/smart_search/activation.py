"""Smart search activation: activate, pause, resume, retry, cancel, remove, status, update, and the model
download job that the worker runs.

Every state change goes through `domain.smart_search.transition()`. The API process and the worker share
the persisted status row; the repository writes state changes compare-and-set, so a pause from the API is
never overwritten by the worker's progress. The download job polls the row between 4 MiB blocks and stops
when the state leaves `downloading`. Contract: `orchestration/api/smart-search-contract.md`.

After `starting`, the runtime owner (`application/smart_search/runtime.py`) takes over: it reaches this
service through `advance()` / `runtime_ready()` / `index_progress()` / `indexed()` / `runtime_failed()`.

Model updates are blue/green (`reembed.py`): a verified newer revision registers its space as `building` and
queues `reembed`, while the status keeps serving the installed space. When the new space becomes active (100 %,
or "Usar ya" through `use_now()`), `space_activated()` moves the status to it and deletes the old files.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from bento.application.smart_search.reembed import EmbeddingSpaceState
from bento.application.work_budget import check_safe_boundary
from bento.domain.errors import DomainError, SettingsSourceLockedError
from bento.domain.jobs import JobPriority, JobType
from bento.domain.smart_search import (
    EmbeddingSpace,
    IllegalSmartSearchTransitionError,
    InvalidEmbeddingSpaceError,
    InvalidModelSpecError,
    ModelSpec,
    SmartSearchErrorCode,
    SmartSearchEvent,
    SmartSearchEventKind,
    SmartSearchState,
    SmartSearchStatus,
    parse_space_id,
    suggest_in_onboarding,
    transition,
)
from bento.ports.jobs import JobQueuePort
from bento.ports.models import (
    DownloadOutcome,
    DownloadResult,
    ModelCatalogPort,
    ModelDownloaderPort,
    ModelStorePort,
)

LOGGER = logging.getLogger("bento.smart_search.activation")

PROVIDER_SETTING = "embeddings_provider"
SPACE_HEADROOM = 0.10
"""The free-space precheck needs the file size plus 10 %."""
MODEL_DOWNLOAD_MAX_ATTEMPTS = 8
NETWORK_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0)
"""In-job waits while the network is down; after them the job is retried later by the queue's backoff. The
waits start over whenever an attempt received bytes, so only an outage with no progress uses them up."""
STATUS_POLL_SECONDS = 0.25
LICENSE_URL = "/api/smart-search/license"
USE_NOW_EVENT = "use_now"
ANDROID_PLATFORM = "android"
_CAS_ATTEMPTS = 5
# States whose space may follow a blue/green flip: the model is installed and the runtime owns the space.
_FOLLOWS_FLIP = frozenset(
    {SmartSearchState.STARTING, SmartSearchState.INDEXING, SmartSearchState.READY, SmartSearchState.ERROR}
)


# --------------------------------------------------------------------------------------
# Errors (public codes, `api/error-model.md`)


class SmartSearchStateConflictError(DomainError):
    def __init__(self, state: str, event: str) -> None:
        super().__init__(
            "smart_search_state_conflict",
            "This smart search action is not allowed in the current state",
            {"state": state, "event": event},
        )


class SmartSearchNoSpaceError(DomainError):
    def __init__(self, required_bytes: int, free_bytes: int) -> None:
        super().__init__(
            "smart_search_no_space",
            "Not enough free disk space for the smart search model",
            {"required_bytes": required_bytes, "free_bytes": free_bytes},
        )


class ModelDownloadRetryLater(Exception):
    """The network stayed down through the in-job waits; the queue retries the job with backoff."""

    def __init__(self) -> None:
        super().__init__("Model download is waiting for the network")


# --------------------------------------------------------------------------------------
# Records and ports


class InstallState(StrEnum):
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    VERIFYING = "verifying"
    INSTALLED = "installed"
    ERROR = "error"
    UPDATE_DOWNLOADING = "update_downloading"


# `model_installs.state` as the update progress shows it.
_UPDATE_PROGRESS_STATES: dict[InstallState, str] = {
    InstallState.DOWNLOADING: "downloading",
    InstallState.PAUSED: "downloading",
    InstallState.UPDATE_DOWNLOADING: "downloading",
    InstallState.VERIFYING: "verifying",
    InstallState.INSTALLED: "installed",
    InstallState.ERROR: "error",
}


class DownloadPurpose(StrEnum):
    ACTIVATE = "activate"
    UPDATE = "update"


class DownloadJobResult(StrEnum):
    SKIPPED = "skipped"  # the status moved on (paused, cancelled, another space) before or while running
    STOPPED = "stopped"  # paused or cancelled mid-download
    STARTING = "starting"  # verified; the runtime owner takes over
    UPDATE_READY = "update_ready"  # an update revision is verified; re-embedding can start
    FAILED = "failed"  # the status is now `error`


@dataclass(frozen=True, slots=True)
class ModelInstallRecord:
    """One `model_installs` row. Never carries paths or URLs."""

    model_id: str
    revision: str
    file: str
    bytes_total: int
    bytes_done: int
    sha256: str
    state: InstallState
    error_code: str | None = None


class SmartSearchStatusRepositoryPort(Protocol):
    async def load(self) -> SmartSearchStatus: ...

    async def replace(self, expected: SmartSearchStatus, new: SmartSearchStatus) -> bool:
        """Compare-and-set: write `new` only while the row still matches `expected`'s state, space, error code
        and network flag. Returns False when another process changed it first."""
        ...

    async def set_download_progress(self, space_id: str, bytes_done: int) -> bool:
        """Only while `downloading`/`paused` in `space_id`."""
        ...

    async def set_index_progress(self, space_id: str, done: int, total: int) -> bool:
        """Only while `indexing` in `space_id`."""
        ...

    async def save_install(self, record: ModelInstallRecord) -> None: ...

    async def installs(self) -> tuple[ModelInstallRecord, ...]: ...

    async def delete_installs(self, model_id: str, revision: str | None = None) -> None: ...


class SmartSearchProviderSwitchPort(Protocol):
    """The `embeddings_provider` setting as the activation flow sees it (the settings form never writes
    `managed` itself)."""

    async def locked(self) -> bool:
        """True when the environment or a policy controls `embeddings_provider`."""
        ...

    async def enable(self) -> None:
        """Set `embeddings_provider = managed`."""
        ...

    async def disable(self) -> None:
        """Set `embeddings_provider = disabled` if it is `managed`."""
        ...


class SmartSearchHooksPort(Protocol):
    """Where the other Stage 24 parts plug in (runtime owner, re-embedding, vector tables)."""

    async def starting(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> None:
        """The status just entered `starting` (after verification, or a runtime retry)."""
        ...

    async def update_ready(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> None:
        """A newer revision is downloaded and verified; build its space blue/green."""
        ...

    async def stopped(self, space_id: str | None) -> None:
        """Cancel/remove: stop the runtime and drop the space's vectors."""
        ...


class EmbeddingSpaceRegistryPort(Protocol):
    """`embedding_spaces` (the vector index adapter implements it)."""

    async def space_state(self, space_id: str) -> EmbeddingSpaceState | None: ...

    async def register_space(self, space: EmbeddingSpace) -> None:
        """Add the space as `building` if it is new (a retired one comes back as `building`)."""
        ...


class ReembedControlPort(Protocol):
    """The blue/green re-embedding owner (`ReembedService`)."""

    async def start(self, space_id: str) -> object:
        """Queue `reembed` for a registered space."""
        ...

    async def use_now(self, space_id: str) -> tuple[str, ...]:
        """Flip search to the space before it reaches 100 %; returns the space ids whose vectors were dropped."""
        ...


class NoopSmartSearchHooks:
    async def starting(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> None:
        return None

    async def update_ready(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> None:
        return None

    async def stopped(self, space_id: str | None) -> None:
        return None


@dataclass(frozen=True, slots=True)
class UpdateProgress:
    """The newer revision's `model_installs` row. The status stays `ready` while an update downloads."""

    bytes_done: int
    bytes_total: int
    state: str
    """`downloading | verifying | installed | error`."""


@dataclass(frozen=True, slots=True)
class SmartSearchStatusView:
    """Everything `GET /api/smart-search` returns."""

    status: SmartSearchStatus
    spec: ModelSpec
    dims: int
    free_bytes: int
    update: ModelSpec | None
    locked: bool
    update_progress: UpdateProgress | None = None
    can_use_now: bool = False
    """A re-embed into a newer space is pending and the person may switch search to it now ("Usar ya")."""
    suggest_in_onboarding: bool = False
    model_installed: bool = False
    """The status's weights file is installed and verified (`model_available` of `GET /api/settings`)."""

    @property
    def download_host(self) -> str:
        return urlsplit(self.spec.weights.urls[0]).hostname or ""

    def body(self) -> dict[str, Any]:
        status = self.status
        return {
            "state": status.state.value,
            "waiting_network": status.waiting_network,
            "error_code": status.error_code.value if status.error_code is not None else None,
            "failed_step": status.failed_step.value if status.failed_step is not None else None,
            "space_id": status.space_id,
            "download": {"bytes_done": status.bytes_done, "bytes_total": status.bytes_total},
            "indexing": {"done": status.indexed_done, "total": status.indexed_total},
            "model": {
                "model_id": self.spec.model_id,
                "display_name": self.spec.display_name,
                "license_spdx": self.spec.license_spdx,
                "license_url": LICENSE_URL,
                "size_bytes": self.spec.text_bytes,
                "download_host": self.download_host,
                "dims": self.dims,
            },
            "free_bytes": self.free_bytes,
            "update_available": (
                {
                    "revision": self.update.revision,
                    "size_bytes": self.update.text_bytes,
                    "progress": (
                        {
                            "bytes_done": self.update_progress.bytes_done,
                            "bytes_total": self.update_progress.bytes_total,
                            "state": self.update_progress.state,
                        }
                        if self.update_progress is not None
                        else None
                    ),
                }
                if self.update is not None
                else None
            ),
            "locked": self.locked,
            "search_available": status.search_available,
            "can_use_now": self.can_use_now,
            "suggest_in_onboarding": self.suggest_in_onboarding,
        }


@dataclass(slots=True)
class _LiveProgress:
    """Shared between the download thread (writes) and the status watcher (reads)."""

    bytes_done: int = 0
    stop: bool = False

    def update(self, done: int, total: int) -> None:
        del total
        self.bytes_done = done

    def should_stop(self) -> bool:
        check_safe_boundary()  # bounded worker runs (Android budgets) stop between blocks
        return self.stop


# --------------------------------------------------------------------------------------
# Service


@dataclass(slots=True)
class SmartSearchActivationService:
    catalog: ModelCatalogPort
    store: ModelStorePort
    repository: SmartSearchStatusRepositoryPort
    jobs: JobQueuePort
    provider_switch: SmartSearchProviderSwitchPort
    hooks: SmartSearchHooksPort = field(default_factory=NoopSmartSearchHooks)
    downloader: ModelDownloaderPort | None = None
    write_license: Callable[[ModelSpec], None] | None = None
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    poll_interval_seconds: float = STATUS_POLL_SECONDS
    network_retry_delays: tuple[float, ...] = NETWORK_RETRY_DELAYS
    spaces: EmbeddingSpaceRegistryPort | None = None
    """With `reembed`, enables blue/green updates and "Usar ya"; without them an update only downloads."""
    reembed: ReembedControlPort | None = None
    platform: str = "auto"
    host_resources: Callable[[], tuple[int, int]] | None = None
    """`(cpu_cores, ram_bytes)` of this machine, for the onboarding suggestion (D8). None never suggests."""

    # -- read ------------------------------------------------------------------------------

    async def status(self) -> SmartSearchStatusView:
        status = await self.repository.load()
        spec, dims = self._spec_for(status)
        update = self._update_for(status)
        installs = await self.repository.installs()
        locked = await self.provider_switch.locked()
        return SmartSearchStatusView(
            status=status,
            spec=spec,
            dims=dims,
            free_bytes=self.store.free_bytes(),
            update=update,
            locked=locked,
            update_progress=_update_progress(installs, update),
            can_use_now=await self._pending_reembed_space(status, installs) is not None,
            suggest_in_onboarding=self._suggest_in_onboarding(status, locked),
            model_installed=status.state is not SmartSearchState.OFF and self._installed(spec),
        )

    # -- person actions --------------------------------------------------------------------

    async def activate(self, model_id: str | None = None, dims: int | None = None) -> SmartSearchStatusView:
        if await self.provider_switch.locked():
            raise SettingsSourceLockedError([PROVIDER_SETTING])
        spec = self.catalog.get(model_id) if model_id else self.catalog.default()
        if spec is None:
            raise InvalidModelSpecError("Unknown smart search model", {"model_id": model_id})
        space = spec.space(dims)
        current = await self.repository.load()
        if current.state is not SmartSearchState.OFF:
            raise SmartSearchStateConflictError(current.state.value, SmartSearchEventKind.ACTIVATE.value)
        self._check_space(spec, already=0)
        event = SmartSearchEvent(
            SmartSearchEventKind.ACTIVATE, space_id=space.id, bytes_total=spec.weights.size_bytes
        )
        await self.provider_switch.enable()
        await self._apply(event)
        await self.repository.save_install(_record(spec, InstallState.DOWNLOADING, 0))
        await self._enqueue(spec, space, DownloadPurpose.ACTIVATE)
        return await self.status()

    async def pause(self) -> SmartSearchStatusView:
        new = await self._apply(SmartSearchEvent(SmartSearchEventKind.PAUSE))
        await self._mark_install(new, InstallState.PAUSED)
        return await self.status()

    async def resume(self) -> SmartSearchStatusView:
        new = await self._apply(SmartSearchEvent(SmartSearchEventKind.RESUME))
        spec, space = self._spec_and_space(new)
        await self._mark_install(new, InstallState.DOWNLOADING)
        if spec is not None and space is not None:
            await self._enqueue(spec, space, DownloadPurpose.ACTIVATE)
        return await self.status()

    async def retry(self) -> SmartSearchStatusView:
        new = await self._apply(SmartSearchEvent(SmartSearchEventKind.RETRY))
        spec, space = self._spec_and_space(new)
        if spec is not None and space is not None:
            if new.state is SmartSearchState.DOWNLOADING:
                await self.repository.save_install(_record(spec, InstallState.DOWNLOADING, new.bytes_done))
                await self._enqueue(spec, space, DownloadPurpose.ACTIVATE)
            elif new.state is SmartSearchState.STARTING:
                await self.hooks.starting(spec, space, self.store.path_for(spec, spec.weights))
        return await self.status()

    async def cancel(self) -> SmartSearchStatusView:
        previous, _ = await self._apply_with_previous(SmartSearchEvent(SmartSearchEventKind.CANCEL))
        await self._clean_up(previous)
        return await self.status()

    async def remove(self) -> tuple[SmartSearchStatusView, int]:
        """Returns the new status and the bytes freed on disk."""
        previous, _ = await self._apply_with_previous(SmartSearchEvent(SmartSearchEventKind.REMOVE))
        freed = await self._clean_up(previous)
        return await self.status(), freed

    async def update(self) -> SmartSearchStatusView:
        current = await self.repository.load()
        newer = self._update_for(current)
        if current.state is not SmartSearchState.READY or newer is None:
            raise SmartSearchStateConflictError(current.state.value, "update")
        for record in await self.repository.installs():
            if (record.model_id, record.revision) == (newer.model_id, newer.revision) and record.state in {
                InstallState.UPDATE_DOWNLOADING,
                InstallState.INSTALLED,
            }:
                return await self.status()
        space = newer.space(_dims_or_default(current.space_id, newer))
        self._check_space(newer, already=0)
        await self.repository.save_install(_record(newer, InstallState.UPDATE_DOWNLOADING, 0))
        await self._enqueue(newer, space, DownloadPurpose.UPDATE)
        return await self.status()

    async def use_now(self) -> SmartSearchStatusView:
        """"Usar ya": switch search to the pending re-embed space before it reaches 100 %."""
        current = await self.repository.load()
        space_id = await self._pending_reembed_space(current, await self.repository.installs())
        if space_id is None or self.reembed is None:
            raise SmartSearchStateConflictError(current.state.value, USE_NOW_EVENT)
        try:
            dropped = await self.reembed.use_now(space_id)
        except InvalidEmbeddingSpaceError as exc:  # retired or dropped by a concurrent flip
            raise SmartSearchStateConflictError(current.state.value, USE_NOW_EVENT) from exc
        await self.space_activated(space_id, dropped)
        return await self.status()

    # -- runtime owner API (Stage 24 embeddings-runtime / reembed) ---------------------------

    async def space_activated(self, space_id: str, dropped_space_ids: Sequence[str] = ()) -> SmartSearchStatus | None:
        """The blue/green flip committed: the status follows to `space_id` (the runtime supervisor then serves
        it) and the files of models no longer used are deleted. Idempotent; `ReembedObserverPort.activated`.

        The state does not change, so this is not a state machine event: only the space (and the size of its
        verified weights) moves."""
        try:
            model_id, revision, dims = parse_space_id(space_id)
        except InvalidEmbeddingSpaceError:
            return None
        spec = self.catalog.get(model_id, revision)
        if spec is None or dims not in spec.matryoshka_dims:
            return None
        previous: SmartSearchStatus | None = None
        current = await self.repository.load()
        for _ in range(_CAS_ATTEMPTS):
            if current.state not in _FOLLOWS_FLIP or current.space_id == space_id:
                break
            size = spec.weights.size_bytes
            moved = replace(current, space_id=space_id, bytes_done=size, bytes_total=size)
            if await self.repository.replace(current, moved):
                previous, current = current, moved
                break
            current = await self.repository.load()
        old_spaces = [*dropped_space_ids, *([previous.space_id] if previous and previous.space_id else [])]
        await self._remove_old_models(spec, old_spaces)
        return current

    async def reembed_progress(self, space_id: str, done: int, total: int) -> None:
        """`ReembedObserverPort.progress`: only shown while the status is `indexing` in that space."""
        await self.repository.set_index_progress(space_id, done, total)


    async def advance(self, space_id: str, event: SmartSearchEvent) -> SmartSearchStatus | None:
        """Apply a system event to `space_id`'s status. None when the status moved on (another space, or the
        event is no longer legal), which callers treat as "someone else decided"."""
        for _ in range(_CAS_ATTEMPTS):
            current = await self.repository.load()
            if current.space_id != space_id:
                return None
            try:
                new = transition(current, event)
            except IllegalSmartSearchTransitionError:
                return None
            if new == current:
                return current
            if await self.repository.replace(current, new):
                return new
        return None

    async def runtime_ready(self, space_id: str) -> SmartSearchStatus | None:
        return await self.advance(space_id, SmartSearchEvent(SmartSearchEventKind.RUNTIME_READY))

    async def runtime_failed(self, space_id: str) -> SmartSearchStatus | None:
        return await self.advance(
            space_id, SmartSearchEvent(SmartSearchEventKind.FAIL, error_code=SmartSearchErrorCode.RUNTIME)
        )

    async def index_progress(self, space_id: str, done: int, total: int) -> bool:
        return await self.repository.set_index_progress(space_id, done, total)

    async def indexed(self, space_id: str) -> SmartSearchStatus | None:
        return await self.advance(space_id, SmartSearchEvent(SmartSearchEventKind.INDEXED))

    async def backlog(self, space_id: str, count: int) -> SmartSearchStatus | None:
        return await self.advance(space_id, SmartSearchEvent(SmartSearchEventKind.BACKLOG, backlog=count))

    # -- the MODEL_DOWNLOAD job ---------------------------------------------------------------

    async def run_download_job(self, payload: Mapping[str, Any], *, final_attempt: bool) -> DownloadJobResult:
        """Run one `model_download` job. Raises `ModelDownloadRetryLater` when the network stays down and
        attempts remain; on the final attempt the status becomes `error(download)` instead."""
        if self.downloader is None:
            raise RuntimeError("No model downloader configured")
        model_id, revision, space_id, purpose = _parse_payload(payload)
        spec = self.catalog.get(model_id, revision)
        if spec is None:
            LOGGER.warning("Model download job names a model that is not in the manifest")
            if purpose is DownloadPurpose.ACTIVATE:
                await self._fail(space_id, SmartSearchErrorCode.DOWNLOAD)
                return DownloadJobResult.FAILED
            return DownloadJobResult.SKIPPED
        space = spec.space(_dims_or_default(space_id, spec))
        if purpose is DownloadPurpose.ACTIVATE and not await self._still_downloading(space_id):
            return DownloadJobResult.SKIPPED

        already_installed = await asyncio.to_thread(self.store.verify, spec)
        if not already_installed:
            result = await self._download_with_retries(spec, space_id, purpose)
            if result is None:
                return DownloadJobResult.SKIPPED
            handled = await self._handle_download_result(spec, space_id, purpose, result, final_attempt)
            if handled is not None:
                return handled
        return await self._verify_and_start(spec, space, purpose)

    async def _download_with_retries(
        self, spec: ModelSpec, space_id: str, purpose: DownloadPurpose
    ) -> DownloadOutcome | None:
        file = spec.weights
        start = await self._bytes_done(spec, space_id, purpose)
        free = self.store.free_bytes()
        if free < max(0, file.size_bytes - start):
            return DownloadOutcome(DownloadResult.NO_SPACE, start)
        delays = self.network_retry_delays
        attempt = 0
        while True:
            outcome = await self._download_once(spec, space_id, purpose, start)
            if outcome.result is not DownloadResult.NETWORK:
                return outcome
            if outcome.bytes_done > start:
                # Bytes arrived since the last drop: this is a new drop, not the same outage, so the waits
                # start over. Otherwise a long download over a flaky link spends the budget while it progresses.
                attempt = 0
            if attempt == len(delays):
                return outcome
            start = max(start, outcome.bytes_done)
            if purpose is DownloadPurpose.ACTIVATE:
                await self.advance(space_id, SmartSearchEvent(SmartSearchEventKind.NETWORK_LOST))
            await self.sleep(delays[attempt])
            attempt += 1
            check_safe_boundary()
            if purpose is DownloadPurpose.ACTIVATE and not await self._still_downloading(space_id):
                return None

    async def _download_once(
        self, spec: ModelSpec, space_id: str, purpose: DownloadPurpose, start: int
    ) -> DownloadOutcome:
        assert self.downloader is not None
        file = spec.weights
        part = self.store.part_path_for(spec, file)
        progress = _LiveProgress(bytes_done=start)
        watcher = asyncio.create_task(self._watch(progress, spec, space_id, purpose, start))
        try:
            outcome = await self.downloader.download(file, part, progress.update, progress.should_stop)
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
        await self._persist_progress(spec, space_id, purpose, outcome.bytes_done)
        return outcome

    async def _watch(
        self, progress: _LiveProgress, spec: ModelSpec, space_id: str, purpose: DownloadPurpose, start: int
    ) -> None:
        persisted = start
        restored = False
        while True:
            try:
                done = progress.bytes_done
                if done != persisted:
                    await self._persist_progress(spec, space_id, purpose, done)
                    persisted = done
                if purpose is DownloadPurpose.ACTIVATE:
                    status = await self.repository.load()
                    if status.state is not SmartSearchState.DOWNLOADING or status.space_id != space_id:
                        progress.stop = True
                        return
                    if status.waiting_network and done > start and not restored:
                        restored = True
                        await self.advance(space_id, SmartSearchEvent(SmartSearchEventKind.NETWORK_RESTORED))
                else:
                    status = await self.repository.load()
                    if status.state is SmartSearchState.OFF:
                        progress.stop = True
                        return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a status read failing must not kill the download
                LOGGER.debug("Smart search status poll failed: %s", exc.__class__.__name__)
            await asyncio.sleep(self.poll_interval_seconds)

    async def _handle_download_result(
        self,
        spec: ModelSpec,
        space_id: str,
        purpose: DownloadPurpose,
        outcome: DownloadOutcome,
        final_attempt: bool,
    ) -> DownloadJobResult | None:
        """None means "the file is complete, go on to verification"."""
        result = outcome.result
        if result is DownloadResult.COMPLETED:
            return None
        if result is DownloadResult.STOPPED:
            await self._after_stop(spec, space_id, purpose)
            return DownloadJobResult.STOPPED
        if result is DownloadResult.NETWORK and not final_attempt:
            if purpose is DownloadPurpose.ACTIVATE:
                await self.advance(space_id, SmartSearchEvent(SmartSearchEventKind.NETWORK_LOST))
            raise ModelDownloadRetryLater()
        code = {
            DownloadResult.CHECKSUM: SmartSearchErrorCode.CHECKSUM,
            DownloadResult.NO_SPACE: SmartSearchErrorCode.SPACE,
        }.get(result, SmartSearchErrorCode.DOWNLOAD)
        if purpose is DownloadPurpose.UPDATE:
            await self.repository.save_install(_record(spec, InstallState.ERROR, outcome.bytes_done, code.value))
            return DownloadJobResult.FAILED
        if code is SmartSearchErrorCode.CHECKSUM:
            # The downloader deleted the part file; the state machine records checksum errors from `verifying`.
            await self.advance(space_id, SmartSearchEvent(SmartSearchEventKind.DOWNLOADED))
        await self._fail(space_id, code)
        await self.repository.save_install(_record(spec, InstallState.ERROR, outcome.bytes_done, code.value))
        return DownloadJobResult.FAILED

    async def _verify_and_start(
        self, spec: ModelSpec, space: EmbeddingSpace, purpose: DownloadPurpose
    ) -> DownloadJobResult:
        weights = self.store.path_for(spec, spec.weights)
        if purpose is DownloadPurpose.UPDATE:
            if not await asyncio.to_thread(self.store.verify, spec):
                await asyncio.to_thread(self.store.remove, spec)
                await self.repository.save_install(
                    _record(spec, InstallState.ERROR, 0, SmartSearchErrorCode.CHECKSUM.value)
                )
                return DownloadJobResult.FAILED
            self._license(spec)
            await self.repository.save_install(_record(spec, InstallState.INSTALLED, spec.weights.size_bytes))
            await self.hooks.update_ready(spec, space, weights)
            await self._build_space(space)
            return DownloadJobResult.UPDATE_READY

        if await self.advance(space.id, SmartSearchEvent(SmartSearchEventKind.DOWNLOADED)) is None:
            return DownloadJobResult.SKIPPED
        await self.repository.save_install(_record(spec, InstallState.VERIFYING, spec.weights.size_bytes))
        if not await asyncio.to_thread(self.store.verify, spec):
            await asyncio.to_thread(self.store.remove, spec)
            await self._fail(space.id, SmartSearchErrorCode.CHECKSUM)
            await self.repository.save_install(
                _record(spec, InstallState.ERROR, 0, SmartSearchErrorCode.CHECKSUM.value)
            )
            return DownloadJobResult.FAILED
        self._license(spec)
        if await self.advance(space.id, SmartSearchEvent(SmartSearchEventKind.VERIFIED)) is None:
            return DownloadJobResult.SKIPPED
        await self.repository.save_install(_record(spec, InstallState.INSTALLED, spec.weights.size_bytes))
        await self.hooks.starting(spec, space, weights)
        return DownloadJobResult.STARTING

    async def _after_stop(self, spec: ModelSpec, space_id: str, purpose: DownloadPurpose) -> None:
        """A stop because of a cancel/remove leaves nothing behind, even bytes written after the API's delete."""
        status = await self.repository.load()
        if purpose is DownloadPurpose.UPDATE:
            if status.state is SmartSearchState.OFF:
                await asyncio.to_thread(self.store.remove, spec)
            return
        if status.space_id != space_id and not _uses_model(status, spec):
            await asyncio.to_thread(self.store.remove, spec)

    # -- helpers ------------------------------------------------------------------------------

    async def _build_space(self, space: EmbeddingSpace) -> None:
        """Register a verified update's space as `building` and queue its re-embedding (idempotent: a retried
        job registers the same space again and `reembed` skips assets that already have vectors)."""
        if self.spaces is None or self.reembed is None:
            return
        if await self.spaces.space_state(space.id) is EmbeddingSpaceState.ACTIVE:
            return
        await self.spaces.register_space(space)
        await self.reembed.start(space.id)

    async def _pending_reembed_space(
        self, status: SmartSearchStatus, installs: Sequence[ModelInstallRecord]
    ) -> str | None:
        """The `building` space that "Usar ya" would switch to, if any: a verified update's space, or the
        status's own space while an older one still serves search."""
        if self.spaces is None or self.reembed is None or not status.search_available:
            return None
        candidates: list[str] = []
        newer = self._update_for(status)
        if newer is not None and any(
            (record.model_id, record.revision, record.state) == (newer.model_id, newer.revision, InstallState.INSTALLED)
            for record in installs
        ):
            candidates.append(newer.space(_dims_or_default(status.space_id, newer)).id)
        if status.space_id:
            candidates.append(status.space_id)
        for space_id in candidates:
            if await self.spaces.space_state(space_id) is EmbeddingSpaceState.BUILDING:
                return space_id
        return None

    def _suggest_in_onboarding(self, status: SmartSearchStatus, locked: bool) -> bool:
        if status.state is not SmartSearchState.OFF or locked or self.platform == ANDROID_PLATFORM:
            return False
        if self.host_resources is None:
            return False
        try:
            cores, ram_bytes = self.host_resources()
        except (OSError, ValueError):
            return False
        return suggest_in_onboarding(cores, ram_bytes)

    def _installed(self, spec: ModelSpec) -> bool:
        try:
            installed = self.store.installed()
        except OSError:
            return False
        return any((item.model_id, item.revision) == (spec.model_id, spec.revision) for item in installed)

    async def _remove_old_models(self, active: ModelSpec, space_ids: Sequence[str]) -> None:
        """Delete the files and install rows of models the active space no longer uses (after the flip)."""
        seen: set[tuple[str, str]] = {(active.model_id, active.revision)}
        for space_id in space_ids:
            try:
                model_id, revision, _ = parse_space_id(space_id)
            except InvalidEmbeddingSpaceError:
                continue
            if not revision or (model_id, revision) in seen:
                continue  # legacy spaces have no managed files; a dims change keeps the same model
            seen.add((model_id, revision))
            old = self.catalog.get(model_id, revision) or _spec_at(self.catalog.get(model_id), revision)
            if old is None:
                continue
            try:
                freed = await asyncio.to_thread(self.store.remove, old)
            except OSError as exc:  # leftover files never undo the flip; the next remove retries
                LOGGER.warning("Could not delete an old model's files: %s", exc.__class__.__name__)
                continue
            await self.repository.delete_installs(old.model_id, old.revision)
            LOGGER.info("Deleted an old smart search model's files (%s bytes)", freed)

    async def _apply(self, event: SmartSearchEvent) -> SmartSearchStatus:
        _, new = await self._apply_with_previous(event)
        return new

    async def _apply_with_previous(self, event: SmartSearchEvent) -> tuple[SmartSearchStatus, SmartSearchStatus]:
        """A person's action: illegal transitions become `smart_search_state_conflict`."""
        current = await self.repository.load()
        for _ in range(_CAS_ATTEMPTS):
            try:
                new = transition(current, event)
            except IllegalSmartSearchTransitionError as exc:
                raise SmartSearchStateConflictError(current.state.value, event.kind.value) from exc
            if await self.repository.replace(current, new):
                return current, new
            current = await self.repository.load()
        raise SmartSearchStateConflictError(current.state.value, event.kind.value)

    async def _fail(self, space_id: str, code: SmartSearchErrorCode) -> None:
        await self.advance(space_id, SmartSearchEvent(SmartSearchEventKind.FAIL, error_code=code))

    async def _clean_up(self, previous: SmartSearchStatus) -> int:
        """After cancel/remove: delete every model file this device holds (including a pending update), tell
        the runtime and vector owners, and turn the provider setting off."""
        freed = 0
        seen: set[tuple[str, str]] = set()
        specs: list[ModelSpec] = []
        spec, _ = self._spec_and_space(previous)
        if spec is not None:
            specs.append(spec)
        for record in await self.repository.installs():
            if (record.model_id, record.revision) in {(s.model_id, s.revision) for s in specs}:
                continue
            known = self.catalog.get(record.model_id, record.revision) or _spec_at(
                self.catalog.get(record.model_id), record.revision
            )
            if known is not None:
                specs.append(known)
        for item in specs:
            key = (item.model_id, item.revision)
            if key in seen:
                continue
            seen.add(key)
            freed += await asyncio.to_thread(self.store.remove, item)
            await self.repository.delete_installs(item.model_id, item.revision)
        await self.hooks.stopped(previous.space_id)
        await self.provider_switch.disable()
        return freed

    async def _enqueue(self, spec: ModelSpec, space: EmbeddingSpace, purpose: DownloadPurpose) -> None:
        await self.jobs.enqueue(
            type=JobType.MODEL_DOWNLOAD,
            priority=int(JobPriority.EMBEDDING),
            payload={
                "model_id": spec.model_id,
                "revision": spec.revision,
                "space_id": space.id,
                "purpose": purpose.value,
            },
            asset_id=None,
            max_attempts=MODEL_DOWNLOAD_MAX_ATTEMPTS,
        )

    async def _mark_install(self, status: SmartSearchStatus, state: InstallState) -> None:
        spec, _ = self._spec_and_space(status)
        if spec is not None:
            await self.repository.save_install(_record(spec, state, status.bytes_done))

    async def _still_downloading(self, space_id: str) -> bool:
        status = await self.repository.load()
        return status.state is SmartSearchState.DOWNLOADING and status.space_id == space_id

    async def _bytes_done(self, spec: ModelSpec, space_id: str, purpose: DownloadPurpose) -> int:
        if purpose is DownloadPurpose.ACTIVATE:
            status = await self.repository.load()
            return status.bytes_done if status.space_id == space_id else 0
        for record in await self.repository.installs():
            if (record.model_id, record.revision, record.file) == (spec.model_id, spec.revision, spec.weights.name):
                return record.bytes_done
        return 0

    async def _persist_progress(self, spec: ModelSpec, space_id: str, purpose: DownloadPurpose, done: int) -> None:
        if purpose is DownloadPurpose.ACTIVATE:
            await self.repository.set_download_progress(space_id, done)
        else:
            await self.repository.save_install(_record(spec, InstallState.UPDATE_DOWNLOADING, done))

    def _check_space(self, spec: ModelSpec, *, already: int) -> None:
        size = spec.text_bytes
        required = size + math.ceil(size * SPACE_HEADROOM) - max(0, already)
        free = self.store.free_bytes()
        if free < required:
            raise SmartSearchNoSpaceError(required, free)

    def _license(self, spec: ModelSpec) -> None:
        if self.write_license is None:
            return
        try:
            self.write_license(spec)
        except OSError as exc:
            LOGGER.warning("Could not write the model license next to the file: %s", exc.__class__.__name__)

    def _spec_for(self, status: SmartSearchStatus) -> tuple[ModelSpec, int]:
        default = self.catalog.default()
        if not status.space_id:
            return default, default.default_dims
        try:
            model_id, revision, dims = parse_space_id(status.space_id)
        except InvalidEmbeddingSpaceError:
            return default, default.default_dims
        spec = (
            self.catalog.get(model_id, revision)
            or _spec_at(self.catalog.get(model_id), revision)
            or default
        )
        return spec, dims if dims in spec.matryoshka_dims else spec.default_dims

    def _spec_and_space(self, status: SmartSearchStatus) -> tuple[ModelSpec | None, EmbeddingSpace | None]:
        if not status.space_id:
            return None, None
        try:
            model_id, revision, dims = parse_space_id(status.space_id)
        except InvalidEmbeddingSpaceError:
            return None, None
        spec = self.catalog.get(model_id, revision) or _spec_at(self.catalog.get(model_id), revision)
        if spec is None or dims not in spec.matryoshka_dims:
            return spec, None
        return spec, spec.space(dims)

    def _update_for(self, status: SmartSearchStatus) -> ModelSpec | None:
        if status.state is SmartSearchState.OFF or not status.space_id:
            return None
        try:
            model_id, revision, _ = parse_space_id(status.space_id)
        except InvalidEmbeddingSpaceError:
            return None
        current = self.catalog.get(model_id)
        if current is None or current.revision == revision:
            return None
        return current


def _update_progress(installs: Sequence[ModelInstallRecord], update: ModelSpec | None) -> UpdateProgress | None:
    if update is None:
        return None
    for record in installs:
        if (record.model_id, record.revision, record.file) == (update.model_id, update.revision, update.weights.name):
            return UpdateProgress(
                bytes_done=record.bytes_done,
                bytes_total=record.bytes_total,
                state=_UPDATE_PROGRESS_STATES.get(record.state, "downloading"),
            )
    return None


def _record(spec: ModelSpec, state: InstallState, bytes_done: int, error_code: str | None = None) -> ModelInstallRecord:
    weights = spec.weights
    return ModelInstallRecord(
        model_id=spec.model_id,
        revision=spec.revision,
        file=weights.name,
        bytes_total=weights.size_bytes,
        bytes_done=max(0, min(bytes_done, weights.size_bytes)),
        sha256=weights.sha256,
        state=state,
        error_code=error_code,
    )


def _spec_at(spec: ModelSpec | None, revision: str) -> ModelSpec | None:
    """The same model at an older revision the manifest no longer lists (only used to find its files: the
    store keeps one directory per revision)."""
    if spec is None:
        return None
    try:
        return replace(spec, revision=revision)
    except InvalidModelSpecError:
        return None


def _uses_model(status: SmartSearchStatus, spec: ModelSpec) -> bool:
    if not status.space_id or status.state is SmartSearchState.OFF:
        return False
    try:
        model_id, revision, _ = parse_space_id(status.space_id)
    except InvalidEmbeddingSpaceError:
        return False
    return (model_id, revision) == (spec.model_id, spec.revision)


def _dims_or_default(space_id: str | None, spec: ModelSpec) -> int:
    if space_id:
        try:
            _, _, dims = parse_space_id(space_id)
        except InvalidEmbeddingSpaceError:
            return spec.default_dims
        if dims in spec.matryoshka_dims:
            return dims
    return spec.default_dims


def _parse_payload(payload: Mapping[str, Any]) -> tuple[str, str, str, DownloadPurpose]:
    try:
        model_id = str(payload["model_id"])
        revision = str(payload["revision"])
        space_id = str(payload["space_id"])
        purpose = DownloadPurpose(str(payload.get("purpose") or DownloadPurpose.ACTIVATE.value))
    except (KeyError, ValueError) as exc:
        raise RuntimeError("model_download job has a malformed payload") from exc
    if not model_id or not revision or not space_id:
        raise RuntimeError("model_download job has a malformed payload")
    return model_id, revision, space_id, purpose
