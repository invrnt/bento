"""`reembed` job: move this device's own files into a new embedding space (blue/green).

Contract: `orchestration/api/smart-search-contract.md` §Re-indexing. Activating a different space (model, revision
or dims) registers it as `building` and queues `reembed`. The job pages through this device's own assets
(`ai_indexing_allowed`: never Telegram-origin or peer assets) and queues one `embedding` job per asset that has no
vectors in the new space yet. Search keeps the `active` space until the new one reaches 100 % (every own asset has
vectors in it, or its embedding job finished without them), or until the person chooses "Usar ya". Then one
transaction flips the active pointer, retires the old space and drops its rows and search table; only after that
are the old model files deleted.

Progress is live: each scan remembers which assets are still waiting for their embedding job, and the worker
calls `embedding_finished(asset_id)` when an embedding job ends for good (done, or failed on its last attempt).
That advances `indexing.done` by one per asset, whatever the job retries were, and the last one runs the final
check at once (flip, `ready`). While embedding jobs are still pending the job also re-queues itself
(`phase: "wait"`) as a fallback, for work this process did not scan (for example after a worker restart).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum
from typing import Protocol

from bento.application.indexing.reindex import (
    REINDEX_PAGE_SIZE,
    IndexableAssetsPort,
    SpaceVectorsPort,
    embedding_payload,
    own_indexable_pages,
)
from bento.domain.jobs import Job, JobPriority, JobStatus, JobType
from bento.domain.smart_search import InvalidEmbeddingSpaceError, parse_space_id
from bento.ports.jobs import ActiveJobsPort, JobQueuePort
from bento.ports.models import ModelCatalogPort, ModelStorePort
from bento.ports.repositories import ClockPort

LOGGER = logging.getLogger("bento.smart_search.reembed")

REEMBED_PRIORITY = int(JobPriority.EMBEDDING) + 1
"""After the embedding jobs it queues, so a `wait` check runs once they drained."""
REEMBED_POLL_SECONDS = 60
PHASE_QUEUE = "queue"
PHASE_WAIT = "wait"
_EMBEDDING_TYPES = frozenset({JobType.EMBEDDING})


class EmbeddingSpaceState(StrEnum):
    """`embedding_spaces.state`; at most one space is active."""

    BUILDING = "building"
    ACTIVE = "active"
    RETIRED = "retired"


class EmbeddingSpacesPort(Protocol):
    async def active_space_id(self) -> str | None: ...

    async def space_state(self, space_id: str) -> EmbeddingSpaceState | None: ...

    async def activate_space(self, space_id: str) -> tuple[str, ...]:
        """Atomic flip; returns the space ids whose vectors were dropped."""
        ...


class ReembedObserverPort(Protocol):
    """Reports progress to the smart search status (`indexing.done/total`) and the flip."""

    async def progress(self, space_id: str, done: int, total: int) -> None: ...

    async def activated(self, space_id: str, dropped_space_ids: Sequence[str]) -> None: ...


@dataclass(frozen=True, slots=True)
class ReembedProgress:
    space_id: str
    done: int = 0
    total: int = 0
    queued: int = 0
    active: bool = False
    """The space serves search (it was active already or the flip just happened)."""
    dropped_space_ids: tuple[str, ...] = ()
    scheduled_check: bool = False

    @property
    def complete(self) -> bool:
        return self.done >= self.total


@dataclass(slots=True)
class _Tracked:
    """A space's last scan in this process: its asset count and the assets still waiting for an embedding job."""

    total: int
    pending: set[str]


class ReembedService:
    def __init__(
        self,
        *,
        assets: IndexableAssetsPort,
        spaces: EmbeddingSpacesPort,
        vectors: SpaceVectorsPort,
        jobs: JobQueuePort,
        active: ActiveJobsPort,
        clock: ClockPort,
        catalog: ModelCatalogPort | None = None,
        store: ModelStorePort | None = None,
        observer: ReembedObserverPort | None = None,
        page_size: int = REINDEX_PAGE_SIZE,
        poll_seconds: int = REEMBED_POLL_SECONDS,
    ) -> None:
        self._assets = assets
        self._spaces = spaces
        self._vectors = vectors
        self._jobs = jobs
        self._active = active
        self._clock = clock
        self._catalog = catalog
        self._store = store
        self._observer = observer
        self._page_size = max(page_size, 1)
        self._poll_seconds = max(poll_seconds, 1)
        self._tracked: dict[str, _Tracked] = {}
        self._checks: dict[str, str] = {}
        """The `wait` check job id last scheduled per space, dropped once live progress completed the space."""

    async def start(self, space_id: str) -> Job:
        """Queue the `reembed` job for a registered space (the activation flow calls this)."""
        parse_space_id(space_id)
        return await self._jobs.enqueue(
            type=JobType.REEMBED, priority=REEMBED_PRIORITY, payload={"space_id": space_id, "phase": PHASE_QUEUE}
        )

    async def handle(self, job: Job) -> ReembedProgress:
        space_id = job.payload.get("space_id")
        if not isinstance(space_id, str) or not space_id:
            raise RuntimeError("Re-embed job missing space_id")
        phase = job.payload.get("phase", PHASE_QUEUE)
        if self._checks.get(space_id) == job.id:
            del self._checks[space_id]
        return await self.run(space_id, queue=phase != PHASE_WAIT)

    async def run(self, space_id: str, *, queue: bool = True, schedule: bool = True) -> ReembedProgress:
        """Scan, report progress, and flip once nothing is pending. `schedule=False` adds no `wait` check (the
        caller already has one queued)."""
        state = await self._spaces.space_state(space_id)
        if state is None or state is EmbeddingSpaceState.RETIRED:
            self._tracked.pop(space_id, None)
            LOGGER.info("Skipped re-embedding into a space that is no longer in use")
            return ReembedProgress(space_id=space_id)

        dropped: tuple[str, ...] = ()
        if state is EmbeddingSpaceState.BUILDING and await self._spaces.active_space_id() is None:
            dropped = await self._activate(space_id)  # nothing to keep serving: the first space is live at once
            state = EmbeddingSpaceState.ACTIVE

        total, pending_ids, queued = await self._scan(space_id, queue=queue)
        pending = len(pending_ids)
        done = total - pending
        if pending:
            self._tracked[space_id] = _Tracked(total=total, pending=pending_ids)
        else:
            self._tracked.pop(space_id, None)
        if self._observer is not None:
            await self._observer.progress(space_id, done, total)

        if pending == 0:
            if state is not EmbeddingSpaceState.ACTIVE:
                dropped = await self._activate(space_id)
            return ReembedProgress(
                space_id=space_id, done=done, total=total, queued=queued, active=True, dropped_space_ids=dropped
            )

        if schedule:
            await self._schedule_check(space_id)
        return ReembedProgress(
            space_id=space_id,
            done=done,
            total=total,
            queued=queued,
            active=state is EmbeddingSpaceState.ACTIVE,
            dropped_space_ids=dropped,
            scheduled_check=schedule,
        )

    async def embedding_finished(self, asset_id: str) -> None:
        """An embedding job for `asset_id` ended for good. Idempotent: an asset counts once per scan, so retries
        and duplicate jobs never over-count. When it was the last pending asset of a space, the final check runs
        now (no waiting for the next `wait` job)."""
        for space_id, tracked in list(self._tracked.items()):
            if asset_id not in tracked.pending:
                continue
            tracked.pending.discard(asset_id)
            if not tracked.pending:
                progress = await self.run(space_id, queue=False, schedule=False)
                if progress.complete:
                    await self._drop_check(space_id)
            elif self._observer is not None:
                await self._observer.progress(space_id, tracked.total - len(tracked.pending), tracked.total)

    async def use_now(self, space_id: str) -> tuple[str, ...]:
        """Flip to the space before it reaches 100 % ("Usar ya"); the queued embedding jobs keep filling it."""
        state = await self._spaces.space_state(space_id)
        if state is None or state is EmbeddingSpaceState.RETIRED:
            raise InvalidEmbeddingSpaceError("Unknown embedding space", {"space_id": space_id})
        if state is EmbeddingSpaceState.ACTIVE:
            return ()
        return await self._activate(space_id)

    async def _scan(self, space_id: str, *, queue: bool) -> tuple[int, set[str], int]:
        """(own assets, the ids of those still waiting for an embedding job, jobs queued now)."""
        total = queued = 0
        pending: set[str] = set()
        async for page in own_indexable_pages(self._assets, page_size=self._page_size):
            total += len(page)
            embedded = await self._vectors.assets_with_vectors(space_id, [asset.id for asset in page])
            for asset in page:
                if asset.id in embedded:
                    continue
                if await self._active.has_active(asset.id, types=_EMBEDDING_TYPES):
                    pending.add(asset.id)
                elif queue:
                    await self._jobs.enqueue(
                        type=JobType.EMBEDDING,
                        priority=int(JobPriority.EMBEDDING),
                        payload=embedding_payload(asset.id, space_id),
                        asset_id=asset.id,
                    )
                    queued += 1
                    pending.add(asset.id)
                # Otherwise its job already ran and produced no vector (no text, a failure): it counts as done.
        return total, pending, queued

    async def _schedule_check(self, space_id: str) -> None:
        job = await self._jobs.enqueue(
            type=JobType.REEMBED, priority=REEMBED_PRIORITY, payload={"space_id": space_id, "phase": PHASE_WAIT}
        )
        await self._jobs.save(replace(job, run_after=self._clock.now() + timedelta(seconds=self._poll_seconds)))
        self._checks[space_id] = job.id

    async def _drop_check(self, space_id: str) -> None:
        """Live progress finished the space: its `wait` check has nothing left to do. Left queued, it could run
        after a removal and a new activation of the same space and count the new space's files as done."""
        job_id = self._checks.pop(space_id, None)
        if job_id is None:
            return
        job = await self._jobs.get(job_id)
        if job is not None and job.status is JobStatus.QUEUED:
            await self._jobs.save(job.complete(self._clock.now()))

    async def _activate(self, space_id: str) -> tuple[str, ...]:
        dropped = await self._spaces.activate_space(space_id)
        LOGGER.info("Search now uses the new embedding space (%s older spaces dropped)", len(dropped))
        self._remove_model_files(space_id, dropped)
        if self._observer is not None:
            await self._observer.activated(space_id, dropped)
        return dropped

    def _remove_model_files(self, space_id: str, dropped: Sequence[str]) -> None:
        """Delete the files of models no longer used by the active space (after the flip committed)."""
        if self._catalog is None or self._store is None:
            return
        try:
            model_id, revision, _ = parse_space_id(space_id)
        except InvalidEmbeddingSpaceError:
            return
        for old in dict.fromkeys(dropped):
            try:
                old_model, old_revision, _ = parse_space_id(old)
            except InvalidEmbeddingSpaceError:
                continue
            if not old_revision or (old_model, old_revision) == (model_id, revision):
                continue  # legacy spaces have no managed files; a dims change keeps the same model
            spec = self._catalog.get(old_model, old_revision)
            if spec is None:
                continue
            try:
                freed = self._store.remove(spec)
            except Exception as exc:  # noqa: BLE001 - leftover files never undo the flip
                LOGGER.warning("Could not delete an old model's files: %s", exc.__class__.__name__)
                continue
            LOGGER.info("Deleted an old model's files (%s bytes)", freed)
