from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bento.application.smart_search.reembed import (
    PHASE_QUEUE,
    PHASE_WAIT,
    REEMBED_PRIORITY,
    EmbeddingSpaceState,
    ReembedService,
)
from bento.domain.assets import Asset, AssetKind, AssetMetadata, AssetMode, AssetOrigin, ProcessingState
from bento.domain.jobs import Job, JobStatus, JobType
from bento.domain.smart_search import (
    InvalidEmbeddingSpaceError,
    ModelFile,
    ModelFileRole,
    ModelSpec,
    Pooling,
    space_id_for,
)

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
OLD = space_id_for("old-model", "a" * 40, 512)
NEW = space_id_for("new-model", "b" * 40, 512)
NEW_SMALLER = space_id_for("old-model", "a" * 40, 256)


@dataclass
class Clock:
    current: datetime = NOW

    def now(self) -> datetime:
        return self.current


def _asset(asset_id: str, origin: AssetOrigin | None = AssetOrigin.DEVICE) -> Asset:
    return Asset(
        id=asset_id,
        kind=AssetKind.DOCUMENT,
        mode=AssetMode.DRIVE,
        folder_id=None,
        filename=f"{asset_id}.txt",
        metadata=AssetMetadata(original_filename=f"{asset_id}.txt", mime_type="text/plain", size_bytes=1, sha256="a" * 64),
        processing_state=ProcessingState.INDEXED,
        favorite=False,
        created_at=NOW,
        updated_at=NOW,
        origin=origin,
    )


@dataclass
class Assets:
    items: list[Asset]
    calls: list[tuple[str | None, int]] = field(default_factory=list)

    async def list_live(self, *, after_id: str | None = None, limit: int = 200) -> tuple[Asset, ...]:
        self.calls.append((after_id, limit))
        ordered = sorted(self.items, key=lambda asset: asset.id)
        if after_id is not None:
            ordered = [asset for asset in ordered if asset.id > after_id]
        return tuple(ordered[:limit])


@dataclass
class Spaces:
    states: dict[str, EmbeddingSpaceState]
    flips: list[str] = field(default_factory=list)

    async def active_space_id(self) -> str | None:
        return next((space for space, state in self.states.items() if state is EmbeddingSpaceState.ACTIVE), None)

    async def space_state(self, space_id: str) -> EmbeddingSpaceState | None:
        return self.states.get(space_id)

    async def activate_space(self, space_id: str) -> tuple[str, ...]:
        dropped = tuple(space for space, state in self.states.items() if state is EmbeddingSpaceState.ACTIVE)
        for space in dropped:
            self.states[space] = EmbeddingSpaceState.RETIRED
        self.states[space_id] = EmbeddingSpaceState.ACTIVE
        self.flips.append(space_id)
        return dropped


@dataclass
class Vectors:
    embedded: dict[str, set[str]] = field(default_factory=dict)

    async def assets_with_vectors(self, space_id: str, asset_ids: Sequence[str]) -> frozenset[str]:
        return frozenset(set(asset_ids) & self.embedded.get(space_id, set()))


@dataclass
class Jobs:
    clock: Clock
    jobs: dict[str, Job] = field(default_factory=dict)

    async def enqueue(
        self,
        *,
        type: JobType,
        priority: int,
        payload: dict[str, object],
        asset_id: str | None = None,
        max_attempts: int = 3,
    ) -> Job:
        now = self.clock.now()
        job = Job(
            id=f"job_{len(self.jobs) + 1}",
            type=type,
            status=JobStatus.QUEUED,
            priority=priority,
            payload=dict(payload),
            attempts=0,
            max_attempts=max_attempts,
            created_at=now,
            updated_at=now,
            asset_id=asset_id,
        )
        self.jobs[job.id] = job
        return job

    async def save(self, job: Job) -> None:
        self.jobs[job.id] = job

    async def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    async def has_active(self, asset_id: str, *, types: frozenset[JobType], exclude_job_id: str | None = None) -> bool:
        return any(
            job.asset_id == asset_id
            and job.type in types
            and job.id != exclude_job_id
            and job.status in {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.RETRYING}
            for job in self.jobs.values()
        )

    def of_type(self, job_type: JobType) -> list[Job]:
        return [job for job in self.jobs.values() if job.type == job_type]

    def finish_embeddings(self, asset_ids: set[str]) -> None:
        for job in self.of_type(JobType.EMBEDDING):
            if job.asset_id in asset_ids:
                self.jobs[job.id] = job.complete(self.clock.now())


@dataclass
class Catalog:
    specs: dict[tuple[str, str], ModelSpec] = field(default_factory=dict)

    def default(self) -> ModelSpec:
        raise NotImplementedError

    def get(self, model_id: str, revision: str | None = None) -> ModelSpec | None:
        return self.specs.get((model_id, revision or ""))

    def all(self) -> tuple[ModelSpec, ...]:
        return tuple(self.specs.values())


@dataclass
class Store:
    removed: list[str] = field(default_factory=list)

    def remove(self, spec: ModelSpec) -> int:
        self.removed.append(spec.model_id)
        return 123

    def installed(self) -> tuple[object, ...]:
        return ()

    def path_for(self, spec: ModelSpec, file: object) -> Path:
        raise NotImplementedError

    def part_path_for(self, spec: ModelSpec, file: object) -> Path:
        raise NotImplementedError

    def free_bytes(self) -> int:
        return 0

    def verify(self, spec: ModelSpec) -> bool:
        return True


@dataclass
class Observer:
    progress_calls: list[tuple[str, int, int]] = field(default_factory=list)
    activations: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    async def progress(self, space_id: str, done: int, total: int) -> None:
        self.progress_calls.append((space_id, done, total))

    async def activated(self, space_id: str, dropped_space_ids: Sequence[str]) -> None:
        self.activations.append((space_id, tuple(dropped_space_ids)))


def _spec(model_id: str, revision: str) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        revision=revision,
        display_name=model_id,
        license_spdx="Apache-2.0",
        source_url="https://bento.example/model",
        files=(
            ModelFile(
                name=f"{model_id}.gguf",
                role=ModelFileRole.WEIGHTS,
                urls=("https://bento.example/model.gguf",),
                size_bytes=10,
                sha256="c" * 64,
            ),
        ),
        native_dims=512,
        matryoshka_dims=(512, 256),
        default_dims=512,
        pooling=Pooling.MEAN,
        context_tokens=2048,
        ubatch_tokens=2048,
        query_template="q: {q}",
        document_template="d: {text}",
    )


@dataclass
class World:
    assets: Assets
    spaces: Spaces
    vectors: Vectors
    jobs: Jobs
    clock: Clock
    store: Store
    observer: Observer
    service: ReembedService


def _world(
    states: dict[str, EmbeddingSpaceState],
    assets: list[Asset],
    *,
    page_size: int = 2,
    jobs_factory: Callable[[Clock], Jobs] = Jobs,
) -> World:
    clock = Clock()
    world_assets = Assets(assets)
    spaces = Spaces(dict(states))
    vectors = Vectors()
    jobs = jobs_factory(clock)
    store = Store()
    observer = Observer()
    catalog = Catalog({("old-model", "a" * 40): _spec("old-model", "a" * 40), ("new-model", "b" * 40): _spec("new-model", "b" * 40)})
    service = ReembedService(
        assets=world_assets,
        spaces=spaces,
        vectors=vectors,
        jobs=jobs,
        active=jobs,
        clock=clock,
        catalog=catalog,
        store=store,
        observer=observer,
        page_size=page_size,
        poll_seconds=60,
    )
    return World(world_assets, spaces, vectors, jobs, clock, store, observer, service)


def _library() -> list[Asset]:
    return [
        _asset("asset_1"),
        _asset("asset_2"),
        _asset("asset_3"),
        _asset("asset_4"),
        _asset("asset_5"),
        _asset("asset_inbox", AssetOrigin.TELEGRAM_INBOX),
        _asset("asset_import", AssetOrigin.TELEGRAM_IMPORT),
        _asset("asset_peer", None),
    ]


def test_reembed_pages_through_own_assets_and_never_queues_telegram_or_peer_files() -> None:
    world = _world({OLD: EmbeddingSpaceState.ACTIVE, NEW: EmbeddingSpaceState.BUILDING}, _library(), page_size=3)

    progress = asyncio.run(world.service.run(NEW))

    embedding_jobs = world.jobs.of_type(JobType.EMBEDDING)
    assert sorted(job.asset_id or "" for job in embedding_jobs) == ["asset_1", "asset_2", "asset_3", "asset_4", "asset_5"]
    assert all(job.payload == {"asset_id": job.asset_id, "space_id": NEW} for job in embedding_jobs)
    assert (progress.total, progress.done, progress.queued) == (5, 0, 5)
    # Keyset pages of 3 over 8 live assets: three calls, each after the last id of the previous page.
    assert [call[0] for call in world.assets.calls] == [None, "asset_3", "asset_import"]
    assert all(limit == 3 for _, limit in world.assets.calls)


def test_reembed_skips_assets_already_in_the_space_and_assets_with_a_pending_job() -> None:
    world = _world({OLD: EmbeddingSpaceState.ACTIVE, NEW: EmbeddingSpaceState.BUILDING}, _library())
    world.vectors.embedded[NEW] = {"asset_1"}
    asyncio.run(world.jobs.enqueue(type=JobType.EMBEDDING, priority=4, payload={"asset_id": "asset_2"}, asset_id="asset_2"))

    progress = asyncio.run(world.service.run(NEW))

    assert progress.queued == 3
    assert (progress.done, progress.total) == (1, 5)
    assert len([job for job in world.jobs.of_type(JobType.EMBEDDING) if job.asset_id == "asset_2"]) == 1


def test_search_keeps_the_old_space_until_the_new_one_reaches_100_percent() -> None:
    world = _world({OLD: EmbeddingSpaceState.ACTIVE, NEW: EmbeddingSpaceState.BUILDING}, _library())

    first = asyncio.run(world.service.run(NEW))
    assert not first.active and first.scheduled_check
    assert world.spaces.flips == []
    checks = world.jobs.of_type(JobType.REEMBED)
    assert len(checks) == 1
    assert checks[0].payload == {"space_id": NEW, "phase": PHASE_WAIT}
    assert checks[0].priority == REEMBED_PRIORITY
    assert checks[0].run_after == NOW + timedelta(seconds=60)

    # Three files embedded, two still waiting: the old space keeps serving search.
    world.vectors.embedded[NEW] = {"asset_1", "asset_2", "asset_3"}
    world.jobs.finish_embeddings({"asset_1", "asset_2", "asset_3"})
    second = asyncio.run(world.service.handle(checks[0]))
    assert (second.done, second.total) == (3, 5)
    assert world.spaces.states[OLD] is EmbeddingSpaceState.ACTIVE
    assert world.store.removed == []

    # One more embedded, the last one's job finished without a vector (no text): that is 100 %.
    world.vectors.embedded[NEW].add("asset_4")
    world.jobs.finish_embeddings({"asset_4", "asset_5"})
    third = asyncio.run(world.service.handle(world.jobs.of_type(JobType.REEMBED)[-1]))

    assert third.active and third.complete and not third.scheduled_check
    assert third.dropped_space_ids == (OLD,)
    assert world.spaces.states == {OLD: EmbeddingSpaceState.RETIRED, NEW: EmbeddingSpaceState.ACTIVE}
    assert world.spaces.flips == [NEW]
    assert world.store.removed == ["old-model"]  # files go only after the flip
    assert world.observer.activations == [(NEW, (OLD,))]
    assert world.observer.progress_calls[-1] == (NEW, 5, 5)
    # The wait phase never queues embeddings again.
    assert len(world.jobs.of_type(JobType.EMBEDDING)) == 5


def test_use_now_flips_before_100_percent_and_embedding_continues() -> None:
    world = _world({OLD: EmbeddingSpaceState.ACTIVE, NEW: EmbeddingSpaceState.BUILDING}, _library())
    asyncio.run(world.service.run(NEW))

    dropped = asyncio.run(world.service.use_now(NEW))

    assert dropped == (OLD,)
    assert world.spaces.states[NEW] is EmbeddingSpaceState.ACTIVE
    later = asyncio.run(world.service.handle(world.jobs.of_type(JobType.REEMBED)[-1]))
    assert later.active and later.dropped_space_ids == ()
    assert world.spaces.flips == [NEW]
    assert asyncio.run(world.service.use_now(NEW)) == ()


def test_the_first_space_serves_search_at_once() -> None:
    world = _world({NEW: EmbeddingSpaceState.BUILDING}, _library())

    progress = asyncio.run(world.service.run(NEW))

    assert progress.active and progress.queued == 5
    assert world.spaces.flips == [NEW]
    assert world.store.removed == []


def test_a_dims_change_keeps_the_model_files() -> None:
    world = _world({OLD: EmbeddingSpaceState.ACTIVE, NEW_SMALLER: EmbeddingSpaceState.BUILDING}, [_asset("asset_1")])
    world.vectors.embedded[NEW_SMALLER] = {"asset_1"}

    progress = asyncio.run(world.service.run(NEW_SMALLER))

    assert progress.active and progress.dropped_space_ids == (OLD,)
    assert world.store.removed == []


def test_a_job_for_a_retired_or_unknown_space_does_nothing() -> None:
    world = _world({OLD: EmbeddingSpaceState.ACTIVE, NEW: EmbeddingSpaceState.RETIRED}, _library())

    progress = asyncio.run(world.service.run(NEW))
    unknown = asyncio.run(world.service.run(space_id_for("other-model", "c" * 40, 512)))

    assert progress.total == 0 and not progress.active
    assert unknown.total == 0
    assert world.jobs.jobs == {}
    with pytest.raises(InvalidEmbeddingSpaceError):
        asyncio.run(world.service.use_now(NEW))


def test_start_queues_the_reembed_job_and_handle_requires_a_space() -> None:
    world = _world({NEW: EmbeddingSpaceState.BUILDING}, [])

    job = asyncio.run(world.service.start(NEW))

    assert job.type is JobType.REEMBED
    assert job.payload == {"space_id": NEW, "phase": PHASE_QUEUE}
    assert job.priority == REEMBED_PRIORITY
    with pytest.raises(InvalidEmbeddingSpaceError):
        asyncio.run(world.service.start("not a space"))
    broken = Job(
        id="job_x",
        type=JobType.REEMBED,
        status=JobStatus.RUNNING,
        priority=REEMBED_PRIORITY,
        payload={},
        attempts=0,
        max_attempts=3,
        created_at=NOW,
        updated_at=NOW,
    )
    with pytest.raises(RuntimeError):
        asyncio.run(world.service.handle(broken))


# ------------------------------------------------------------------------------------------
# Live progress: each finished embedding job advances `indexing.done` (no waiting for the `wait` check)


def _finish(world: World, asset_id: str, *, embedded: bool = True) -> None:
    """The worker finished `asset_id`'s embedding job for good and told the service."""
    if embedded:
        world.vectors.embedded.setdefault(NEW, set()).add(asset_id)
    world.jobs.finish_embeddings({asset_id})
    asyncio.run(world.service.embedding_finished(asset_id))


def test_progress_advances_with_each_finished_embedding_job() -> None:
    world = _world({NEW: EmbeddingSpaceState.BUILDING}, _library())
    asyncio.run(world.service.run(NEW))
    assert world.observer.progress_calls == [(NEW, 0, 5)]

    for asset_id in ("asset_1", "asset_2", "asset_3", "asset_4"):
        _finish(world, asset_id)

    assert world.observer.progress_calls == [(NEW, 0, 5), (NEW, 1, 5), (NEW, 2, 5), (NEW, 3, 5), (NEW, 4, 5)]
    done = [call[1] for call in world.observer.progress_calls]
    assert done == sorted(done)


def test_the_last_finished_job_completes_the_space_without_waiting_for_the_check() -> None:
    world = _world({OLD: EmbeddingSpaceState.ACTIVE, NEW: EmbeddingSpaceState.BUILDING}, _library())
    asyncio.run(world.service.run(NEW))
    check = world.jobs.of_type(JobType.REEMBED)[0]
    assert check.run_after == NOW + timedelta(seconds=60)

    for asset_id in ("asset_1", "asset_2", "asset_3", "asset_4"):
        _finish(world, asset_id)
    assert world.spaces.flips == []
    _finish(world, "asset_5", embedded=False)  # no text: its job ended without a vector, which counts as done

    # The clock never moved: the flip and the 100 % report came from the last job, not from the 60 s check.
    assert world.clock.current == NOW
    assert world.spaces.flips == [NEW]
    assert world.spaces.states == {OLD: EmbeddingSpaceState.RETIRED, NEW: EmbeddingSpaceState.ACTIVE}
    assert world.observer.progress_calls[-1] == (NEW, 5, 5)
    assert world.observer.activations == [(NEW, (OLD,))]
    # No extra check was queued, and the one waiting has nothing left to do: it is closed, so it cannot run
    # later against the same space activated again after a removal.
    checks = world.jobs.of_type(JobType.REEMBED)
    assert [job.id for job in checks] == [check.id]
    assert checks[0].status is JobStatus.SUCCEEDED


def test_retries_and_duplicate_reports_never_over_count() -> None:
    world = _world({NEW: EmbeddingSpaceState.BUILDING}, _library())
    asyncio.run(world.service.run(NEW))

    _finish(world, "asset_1")
    asyncio.run(world.service.embedding_finished("asset_1"))  # the same asset again (a duplicate job)
    asyncio.run(world.service.embedding_finished("asset_peer"))  # never pending in this space
    asyncio.run(world.service.embedding_finished("asset_unknown"))

    assert world.observer.progress_calls == [(NEW, 0, 5), (NEW, 1, 5)]


def test_a_rescan_resets_the_live_count_to_the_exact_numbers() -> None:
    world = _world({NEW: EmbeddingSpaceState.BUILDING}, _library())
    asyncio.run(world.service.run(NEW))
    _finish(world, "asset_1")
    # A job finished while nobody told the service (for example the worker restarted in between).
    world.vectors.embedded[NEW].add("asset_2")
    world.jobs.finish_embeddings({"asset_2"})

    progress = asyncio.run(world.service.run(NEW, queue=False))
    _finish(world, "asset_3")

    assert (progress.done, progress.total) == (2, 5)
    assert world.observer.progress_calls[-1] == (NEW, 3, 5)


def test_a_retired_space_stops_counting() -> None:
    world = _world({NEW: EmbeddingSpaceState.BUILDING}, _library())
    asyncio.run(world.service.run(NEW))
    world.spaces.states[NEW] = EmbeddingSpaceState.RETIRED  # the person removed the model meanwhile
    asyncio.run(world.service.run(NEW, queue=False))
    calls = list(world.observer.progress_calls)

    _finish(world, "asset_1")

    assert world.observer.progress_calls == calls
