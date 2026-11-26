"""Worker-side smart search glue: the runtime's status sink, the re-embed observer, the activation hooks and the
space janitor. Contract: `orchestration/api/smart-search-contract.md` (§State machine, §Re-indexing).

- `RuntimeStatusRelay` is the runtime supervisor's `RuntimeStatusSinkPort`. It forwards `runtime_ready` /
  `fail(runtime)` to the activation service, and when a *managed* space comes up it registers the space and
  queues `reembed`, which fills it and drives `indexing → ready`.
- `ReembedStatusObserver` reports re-embed progress through the activation service (`index_progress`, `backlog`,
  `indexed`).
- `WorkerSmartSearchHooks` wraps the runtime hooks: `stopped(space_id)` also drops that space's vectors.
- `SmartSearchSpaceJanitor` does the same when cancel/remove ran in the API process (its hooks cannot reach the
  worker): once the persisted status is `off`, every registered managed space is retired and its vectors dropped.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Protocol

from bento.application.smart_search.reembed import EmbeddingSpaceState
from bento.application.smart_search.runtime import CUSTOM_MODEL_ID
from bento.domain.jobs import Job, JobType
from bento.domain.smart_search import (
    EmbeddingSpace,
    InvalidEmbeddingSpaceError,
    ModelSpec,
    SmartSearchState,
    SmartSearchStatus,
    parse_space_id,
)

LOGGER = logging.getLogger("bento.worker.smart_search")

JANITOR_INTERVAL_SECONDS = 30.0
_REEMBED_TYPES = frozenset({JobType.REEMBED})


class ActivationProgressPort(Protocol):
    """The slice of `SmartSearchActivationService` the worker drives (agent A's runtime-owner API)."""

    async def runtime_ready(self, space_id: str) -> SmartSearchStatus | None: ...

    async def runtime_failed(self, space_id: str) -> SmartSearchStatus | None: ...

    async def index_progress(self, space_id: str, done: int, total: int) -> bool: ...

    async def indexed(self, space_id: str) -> SmartSearchStatus | None: ...

    async def backlog(self, space_id: str, count: int) -> SmartSearchStatus | None: ...

    async def space_activated(self, space_id: str, dropped_space_ids: Sequence[str] = ()) -> SmartSearchStatus | None: ...


class SpaceRegistryPort(Protocol):
    """`SQLiteVecSearchIndex` as the `embedding_spaces` registry and per-space vector store."""

    async def register_space(self, space: EmbeddingSpace) -> None: ...

    async def space_state(self, space_id: str) -> EmbeddingSpaceState | None: ...

    async def registered_space_ids(self) -> tuple[str, ...]: ...

    async def retire_space(self, space_id: str) -> None: ...


class ReembedStarterPort(Protocol):
    async def start(self, space_id: str) -> Job: ...


class PendingJobsPort(Protocol):
    async def backlog(self, *, types: frozenset[JobType] | None = None) -> object: ...


class RuntimeHooksPort(Protocol):
    async def starting(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> None: ...

    async def update_ready(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> None: ...

    async def stopped(self, space_id: str | None) -> None: ...


ServedModel = Callable[[], tuple[ModelSpec, EmbeddingSpace] | None]
StatusLoader = Callable[[], Awaitable[SmartSearchStatus]]


def is_managed_space(space_id: str | None) -> bool:
    """`<model_id>@<revision>/<dims>` of a manifest model: not legacy, not the synthetic `custom` model."""
    if not space_id:
        return False
    try:
        model_id, revision, _ = parse_space_id(space_id)
    except InvalidEmbeddingSpaceError:
        return False
    return bool(revision) and model_id != CUSTOM_MODEL_ID


class ReembedStatusObserver:
    """`ReembedObserverPort`: re-embed progress becomes the status' `indexing.done/total`.

    Pending work over the backlog threshold moves `ready` back to `indexing` (the domain ignores small backlogs);
    a finished scan moves `indexing` to `ready`. Calls for a space the status no longer names are no-ops there."""

    def __init__(self, activation: ActivationProgressPort) -> None:
        self._activation = activation

    async def progress(self, space_id: str, done: int, total: int) -> None:
        pending = max(total - done, 0)
        try:
            if pending > 0:
                await self._activation.backlog(space_id, pending)
            await self._activation.index_progress(space_id, done, total)
            if pending == 0:
                await self._activation.indexed(space_id)
        except Exception as exc:  # noqa: BLE001 - status bookkeeping never fails the re-embed job
            LOGGER.warning("Could not record the re-embedding progress: %s", exc.__class__.__name__)

    async def activated(self, space_id: str, dropped_space_ids: Sequence[str]) -> None:
        try:
            await self._activation.space_activated(space_id, dropped_space_ids)
        except Exception as exc:  # noqa: BLE001 - status bookkeeping never fails the re-embed job
            LOGGER.warning("Could not record the embedding space switch: %s", exc.__class__.__name__)
            return
        LOGGER.info("Search switched to the new embedding space (%s older spaces dropped)", len(dropped_space_ids))


class RuntimeStatusRelay:
    """`RuntimeStatusSinkPort` for the worker's runtime supervisor.

    On `runtime_ready` of a managed space: register it (`building` when new) and queue `reembed` when the space
    still has to be built or the status is `indexing`. At most once per space per worker process, and not while
    a `reembed` job is already waiting, unless the space was (re)registered just now: removal retires it, and
    activating it again in the same process must fill it again."""

    def __init__(
        self,
        *,
        activation: ActivationProgressPort,
        spaces: SpaceRegistryPort,
        reembed: ReembedStarterPort,
        load_status: StatusLoader,
        served_model: ServedModel | None = None,
        jobs: PendingJobsPort | None = None,
    ) -> None:
        self._activation = activation
        self._spaces = spaces
        self._reembed = reembed
        self._load_status = load_status
        self._served_model = served_model
        self._jobs = jobs
        self._started: set[str] = set()

    async def runtime_ready(self, space_id: str) -> SmartSearchStatus | None:
        result = await self._activation.runtime_ready(space_id)
        if is_managed_space(space_id):
            try:
                await self._prepare_space(space_id)
            except Exception as exc:  # noqa: BLE001 - the next runtime_ready (or restart) tries again
                LOGGER.warning("Could not start re-embedding into the new space: %s", exc.__class__.__name__)
        return result

    async def runtime_failed(self, space_id: str) -> SmartSearchStatus | None:
        return await self._activation.runtime_failed(space_id)

    async def _prepare_space(self, space_id: str) -> None:
        state = await self._spaces.space_state(space_id)
        fresh = state is None or state is EmbeddingSpaceState.RETIRED
        if fresh:
            await self._spaces.register_space(self._space(space_id))
            state = EmbeddingSpaceState.BUILDING
        elif space_id in self._started:
            return
        status = await self._load_status()
        indexing = status.space_id == space_id and status.state is SmartSearchState.INDEXING
        if state is EmbeddingSpaceState.ACTIVE and not indexing:
            return  # built already; new files get their own embedding jobs
        # A fresh space (first activation, or activated again after removal in this process) always gets its
        # own `queue` scan: a `wait` check left from before the removal never queues embedding jobs.
        if not fresh and await self._reembed_waiting():
            self._started.add(space_id)
            return
        await self._reembed.start(space_id)
        self._started.add(space_id)
        LOGGER.info("Queued re-embedding of this device's files into the active smart search space")

    def _space(self, space_id: str) -> EmbeddingSpace:
        served = self._served_model() if self._served_model is not None else None
        if served is not None and served[1].id == space_id:
            return served[1]
        model_id, revision, dims = parse_space_id(space_id)
        return EmbeddingSpace(id=space_id, model_id=model_id, revision=revision, dims=dims)

    async def _reembed_waiting(self) -> bool:
        if self._jobs is None:
            return False
        backlog = getattr(self._jobs, "backlog", None)
        if backlog is None:
            return False
        try:
            result = await backlog(types=_REEMBED_TYPES)
        except Exception:  # noqa: BLE001 - when unsure, queue: the job is idempotent
            return False
        return int(getattr(result, "remaining", 0) or 0) > 0


class WorkerSmartSearchHooks:
    """`SmartSearchHooksPort` in the worker: the runtime hooks, plus dropping a stopped space's vectors."""

    def __init__(self, *, runtime: RuntimeHooksPort | None, spaces: SpaceRegistryPort) -> None:
        self._runtime = runtime
        self._spaces = spaces

    async def starting(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> None:
        if self._runtime is not None:
            await self._runtime.starting(spec, space, weights)

    async def update_ready(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> None:
        if self._runtime is not None:
            await self._runtime.update_ready(spec, space, weights)

    async def stopped(self, space_id: str | None) -> None:
        if self._runtime is not None:
            await self._runtime.stopped(space_id)
        if space_id and is_managed_space(space_id):
            await self._spaces.retire_space(space_id)
            LOGGER.info("Dropped the vectors of the removed smart search space")


class SmartSearchSpaceJanitor:
    """Cancel/remove run in the API process; the worker drops the vectors once the status says `off`."""

    def __init__(
        self,
        *,
        load_status: StatusLoader,
        spaces: SpaceRegistryPort,
        interval_seconds: float = JANITOR_INTERVAL_SECONDS,
    ) -> None:
        self._load_status = load_status
        self._spaces = spaces
        self._interval = interval_seconds

    async def sweep(self) -> tuple[str, ...]:
        """Retire every registered managed space while smart search is off. Returns the retired space ids."""
        status = await self._load_status()
        if status.state is not SmartSearchState.OFF:
            return ()
        retired: list[str] = []
        for space_id in await self._spaces.registered_space_ids():
            if not is_managed_space(space_id):
                continue
            await self._spaces.retire_space(space_id)
            retired.append(space_id)
        if retired:
            LOGGER.info("Smart search is off: dropped the vectors of %s embedding spaces", len(retired))
        return tuple(retired)

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.sweep()
            except Exception as exc:  # noqa: BLE001 - the loop must survive one bad check
                LOGGER.debug("Smart search space check skipped: %s", exc.__class__.__name__)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._interval)
            except TimeoutError:
                pass
