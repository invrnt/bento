"""Worker smart search glue: runtime status relay, re-embed observer, hooks and the space janitor (fakes only)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from bento.application.smart_search.reembed import EmbeddingSpaceState
from bento.domain.jobs import Job, JobStatus, JobType
from bento.domain.smart_search import (
    EmbeddingSpace,
    ModelSpec,
    SmartSearchState,
    SmartSearchStatus,
    legacy_space_id,
    space_id_for,
)
from bento.interfaces.worker.smart_search import (
    ReembedStatusObserver,
    RuntimeStatusRelay,
    SmartSearchSpaceJanitor,
    WorkerSmartSearchHooks,
    is_managed_space,
)

REVISION = "6ea3e3a309d12a4779cfda98b8c19800d2d5da71"
MANAGED = EmbeddingSpace(
    id=space_id_for("embeddinggemma-2-q8_0", REVISION, 512), model_id="embeddinggemma-2-q8_0", revision=REVISION, dims=512
)
CUSTOM = space_id_for("custom", "0123456789ab", 768)
NOW = datetime(2026, 11, 26, tzinfo=UTC)


@dataclass
class FakeActivation:
    calls: list[tuple[str, ...]] = field(default_factory=list)
    ready_result: SmartSearchStatus | None = None

    async def runtime_ready(self, space_id: str) -> SmartSearchStatus | None:
        self.calls.append(("runtime_ready", space_id))
        return self.ready_result

    async def runtime_failed(self, space_id: str) -> SmartSearchStatus | None:
        self.calls.append(("runtime_failed", space_id))
        return None

    async def index_progress(self, space_id: str, done: int, total: int) -> bool:
        self.calls.append(("index_progress", space_id, str(done), str(total)))
        return True

    async def indexed(self, space_id: str) -> SmartSearchStatus | None:
        self.calls.append(("indexed", space_id))
        return None

    async def backlog(self, space_id: str, count: int) -> SmartSearchStatus | None:
        self.calls.append(("backlog", space_id, str(count)))
        return None


@dataclass
class FakeSpaces:
    states: dict[str, EmbeddingSpaceState] = field(default_factory=dict)
    registered: list[EmbeddingSpace] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)

    async def register_space(self, space: EmbeddingSpace) -> None:
        self.registered.append(space)
        if self.states.get(space.id) in {None, EmbeddingSpaceState.RETIRED}:
            self.states[space.id] = EmbeddingSpaceState.BUILDING

    async def space_state(self, space_id: str) -> EmbeddingSpaceState | None:
        return self.states.get(space_id)

    async def registered_space_ids(self) -> tuple[str, ...]:
        return tuple(space_id for space_id, state in self.states.items() if state is not EmbeddingSpaceState.RETIRED)

    async def retire_space(self, space_id: str) -> None:
        self.retired.append(space_id)
        self.states[space_id] = EmbeddingSpaceState.RETIRED


@dataclass
class FakeReembed:
    started: list[str] = field(default_factory=list)

    async def start(self, space_id: str) -> Job:
        self.started.append(space_id)
        return Job(
            id=f"job_{len(self.started)}",
            type=JobType.REEMBED,
            status=JobStatus.QUEUED,
            priority=41,
            payload={"space_id": space_id},
            attempts=0,
            max_attempts=3,
            created_at=NOW,
            updated_at=NOW,
        )


@dataclass
class Backlog:
    remaining: int


@dataclass
class FakeJobs:
    waiting: int = 0
    asked: list[frozenset[JobType] | None] = field(default_factory=list)

    async def backlog(self, *, types: frozenset[JobType] | None = None) -> Backlog:
        self.asked.append(types)
        return Backlog(self.waiting)


def status(state: SmartSearchState, space_id: str | None = MANAGED.id) -> SmartSearchStatus:
    return SmartSearchStatus(state=state, space_id=space_id)


def loader(value: SmartSearchStatus) -> Callable[[], Awaitable[SmartSearchStatus]]:
    async def load() -> SmartSearchStatus:
        return value

    return load


def relay(
    activation: FakeActivation,
    spaces: FakeSpaces,
    reembed: FakeReembed,
    current: SmartSearchStatus,
    jobs: FakeJobs | None = None,
) -> RuntimeStatusRelay:
    return RuntimeStatusRelay(
        activation=activation,
        spaces=spaces,
        reembed=reembed,
        load_status=loader(current),
        served_model=lambda: None,
        jobs=jobs,
    )


def test_managed_space_ids() -> None:
    assert is_managed_space(MANAGED.id)
    assert not is_managed_space(CUSTOM)
    assert not is_managed_space(legacy_space_id("mock", 8))
    assert not is_managed_space(None)
    assert not is_managed_space("not a space")


def test_runtime_ready_of_a_new_managed_space_registers_it_and_queues_reembed() -> None:
    async def scenario() -> None:
        activation, spaces, reembed = FakeActivation(), FakeSpaces(), FakeReembed()
        sink = relay(activation, spaces, reembed, status(SmartSearchState.INDEXING))

        await sink.runtime_ready(MANAGED.id)
        await sink.runtime_ready(MANAGED.id)  # a restart of the same space queues nothing more

        assert activation.calls == [("runtime_ready", MANAGED.id), ("runtime_ready", MANAGED.id)]
        assert [space.id for space in spaces.registered] == [MANAGED.id]
        assert spaces.registered[0].dims == 512 and spaces.registered[0].revision == REVISION
        assert reembed.started == [MANAGED.id]

    asyncio.run(scenario())


def test_runtime_ready_of_a_built_space_in_ready_state_queues_nothing() -> None:
    async def scenario() -> None:
        activation, reembed = FakeActivation(), FakeReembed()
        spaces = FakeSpaces(states={MANAGED.id: EmbeddingSpaceState.ACTIVE})
        sink = relay(activation, spaces, reembed, status(SmartSearchState.READY))

        await sink.runtime_ready(MANAGED.id)

        assert reembed.started == [] and spaces.registered == []

    asyncio.run(scenario())


def test_runtime_ready_while_indexing_resumes_reembed_unless_one_is_waiting() -> None:
    async def scenario() -> None:
        spaces = FakeSpaces(states={MANAGED.id: EmbeddingSpaceState.ACTIVE})
        resumed = FakeReembed()
        await relay(FakeActivation(), spaces, resumed, status(SmartSearchState.INDEXING), FakeJobs()).runtime_ready(
            MANAGED.id
        )
        assert resumed.started == [MANAGED.id]

        jobs, waiting = FakeJobs(waiting=1), FakeReembed()
        await relay(FakeActivation(), spaces, waiting, status(SmartSearchState.INDEXING), jobs).runtime_ready(MANAGED.id)
        assert waiting.started == []
        assert jobs.asked == [frozenset({JobType.REEMBED})]

    asyncio.run(scenario())


def test_custom_and_failed_runtimes_never_touch_spaces() -> None:
    async def scenario() -> None:
        activation, spaces, reembed = FakeActivation(), FakeSpaces(), FakeReembed()
        sink = relay(activation, spaces, reembed, status(SmartSearchState.INDEXING, CUSTOM))

        await sink.runtime_ready(CUSTOM)
        await sink.runtime_failed(MANAGED.id)

        assert activation.calls == [("runtime_ready", CUSTOM), ("runtime_failed", MANAGED.id)]
        assert spaces.registered == [] and reembed.started == []

    asyncio.run(scenario())


def test_reembed_observer_reports_progress_backlog_and_completion() -> None:
    async def scenario() -> None:
        activation = FakeActivation()
        observer = ReembedStatusObserver(activation)

        await observer.progress(MANAGED.id, 40, 100)
        await observer.progress(MANAGED.id, 100, 100)
        await observer.activated(MANAGED.id, ("legacy:mock/8",))

        assert activation.calls == [
            ("backlog", MANAGED.id, "60"),
            ("index_progress", MANAGED.id, "40", "100"),
            ("index_progress", MANAGED.id, "100", "100"),
            ("indexed", MANAGED.id),
        ]

    asyncio.run(scenario())


def test_reembed_observer_never_fails_the_job() -> None:
    class Broken(FakeActivation):
        async def index_progress(self, space_id: str, done: int, total: int) -> bool:
            raise RuntimeError("database is locked")

    asyncio.run(ReembedStatusObserver(Broken()).progress(MANAGED.id, 1, 2))


@dataclass
class FakeRuntimeHooks:
    calls: list[tuple[str, str | None]] = field(default_factory=list)

    async def starting(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> None:
        self.calls.append(("starting", space.id))

    async def update_ready(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> None:
        self.calls.append(("update_ready", space.id))

    async def stopped(self, space_id: str | None) -> None:
        self.calls.append(("stopped", space_id))


def test_stopped_hook_stops_the_runtime_and_drops_the_space() -> None:
    async def scenario() -> None:
        runtime, spaces = FakeRuntimeHooks(), FakeSpaces(states={MANAGED.id: EmbeddingSpaceState.ACTIVE})
        hooks = WorkerSmartSearchHooks(runtime=runtime, spaces=spaces)

        await hooks.stopped(MANAGED.id)
        await hooks.stopped(None)

        assert runtime.calls == [("stopped", MANAGED.id), ("stopped", None)]
        assert spaces.retired == [MANAGED.id]

        # Without a runtime (smart search off in this worker) the vectors still go.
        bare = FakeSpaces(states={MANAGED.id: EmbeddingSpaceState.ACTIVE})
        await WorkerSmartSearchHooks(runtime=None, spaces=bare).stopped(MANAGED.id)
        assert bare.retired == [MANAGED.id]

    asyncio.run(scenario())


def test_janitor_retires_managed_spaces_only_while_off() -> None:
    async def scenario() -> None:
        spaces = FakeSpaces(states={MANAGED.id: EmbeddingSpaceState.ACTIVE, legacy_space_id("mock", 8): EmbeddingSpaceState.ACTIVE})

        busy = SmartSearchSpaceJanitor(load_status=loader(status(SmartSearchState.READY)), spaces=spaces)
        assert await busy.sweep() == ()
        assert spaces.retired == []

        off = SmartSearchSpaceJanitor(load_status=loader(SmartSearchStatus()), spaces=spaces)
        assert await off.sweep() == (MANAGED.id,)
        assert await off.sweep() == ()  # idempotent
        assert spaces.retired == [MANAGED.id]

    asyncio.run(scenario())


def test_janitor_loop_survives_errors_and_stops() -> None:
    async def scenario() -> None:
        async def broken() -> SmartSearchStatus:
            raise RuntimeError("no such table")

        stop = asyncio.Event()
        janitor = SmartSearchSpaceJanitor(load_status=broken, spaces=FakeSpaces(), interval_seconds=0.01)
        task = asyncio.create_task(janitor.run(stop))
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=1.0)

    asyncio.run(scenario())
