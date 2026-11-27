"""The worker's dispatcher feeds live re-embed progress: an embedding job counts once it ends for good, so a
retried attempt never advances `indexing.done` and the last job flips the space at once (bug 2 of the
2026-11-26 real-model exit check)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import Any, cast

from bento.application.smart_search.reembed import EmbeddingSpaceState
from bento.domain.jobs import Job, JobStatus, JobType
from bento.interfaces.worker.dispatch import WorkerDispatcher
from tests.unit.search.test_reembed_service import NEW, NOW, Jobs, World, _asset, _world


@dataclass
class ClaimingJobs(Jobs):
    """The reembed test queue plus claiming: lowest priority first, retries due at once (no real clock)."""

    def claim_sync(self, worker_id: str) -> Job | None:
        due = [job for job in self.jobs.values() if job.status in {JobStatus.QUEUED, JobStatus.RETRYING}]
        due = [job for job in due if job.type is not JobType.REEMBED]  # only embeddings run in these tests
        if not due:
            return None
        job = min(due, key=lambda item: (item.priority, item.created_at, item.id)).claim(worker_id, NOW)
        self.jobs[job.id] = job
        return job

    async def claim_next(self, worker_id: str, **_: Any) -> Job | None:
        return self.claim_sync(worker_id)


@dataclass
class FlakyEmbedding:
    """`EmbeddingIndexingService` stand-in: writes the vector, but fails the first `failures[asset]` attempts."""

    world: World
    failures: dict[str, int] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    async def process_asset_embedding(self, asset_id: str) -> None:
        self.calls.append(asset_id)
        if self.failures.get(asset_id, 0) > 0:
            self.failures[asset_id] -= 1
            raise RuntimeError("The embedding server is unavailable")
        self.world.vectors.embedded.setdefault(NEW, set()).add(asset_id)


class FixedClock:
    def now(self) -> Any:
        return NOW


def _dispatching_world(assets: int, failures: dict[str, int]) -> tuple[World, WorkerDispatcher, FlakyEmbedding]:
    world = _world(
        {NEW: EmbeddingSpaceState.BUILDING},
        [_asset(f"asset_{index}") for index in range(1, assets + 1)],
        jobs_factory=ClaimingJobs,
    )
    queue = world.jobs
    embedding = FlakyEmbedding(world, failures=dict(failures))
    dispatcher = WorkerDispatcher(
        jobs=cast(Any, queue),
        media=cast(Any, None),
        clock=FixedClock(),
        worker_id="worker-test",
        embedding=cast(Any, embedding),
        reembed=world.service,
    )
    return world, dispatcher, embedding


def _drain(dispatcher: WorkerDispatcher) -> int:
    async def run() -> int:
        ran = 0
        while await dispatcher.process_one():
            ran += 1
        return ran

    return asyncio.run(run())


def test_a_retried_attempt_does_not_count_and_progress_stays_monotonic() -> None:
    world, dispatcher, embedding = _dispatching_world(4, failures={"asset_2": 1})
    asyncio.run(world.service.run(NEW))

    ran = _drain(dispatcher)

    assert ran == 5 and embedding.calls.count("asset_2") == 2
    done = [call[1] for call in world.observer.progress_calls]
    assert done == [0, 1, 2, 3, 4]
    assert all(total == 4 for _, _, total in world.observer.progress_calls)


def test_a_job_that_fails_for_good_counts_once() -> None:
    world, dispatcher, embedding = _dispatching_world(2, failures={"asset_1": 99})
    asyncio.run(world.service.run(NEW))
    job = next(job for job in world.jobs.of_type(JobType.EMBEDDING) if job.asset_id == "asset_1")
    world.jobs.jobs[job.id] = replace(job, max_attempts=2)

    _drain(dispatcher)

    assert embedding.calls.count("asset_1") == 2
    assert [call[1] for call in world.observer.progress_calls] == [0, 1, 2]
    assert world.jobs.jobs[job.id].status is JobStatus.FAILED


def test_the_last_embedding_job_reports_100_percent_without_the_wait_check() -> None:
    world, dispatcher, _ = _dispatching_world(3, failures={})
    asyncio.run(world.service.run(NEW))
    checks = world.jobs.of_type(JobType.REEMBED)

    _drain(dispatcher)

    assert world.observer.progress_calls[-1] == (NEW, 3, 3)
    # No new check, and the waiting one was closed without running (it was due only in 60 s).
    assert [job.id for job in world.jobs.of_type(JobType.REEMBED)] == [job.id for job in checks]
    assert all(job.status is JobStatus.SUCCEEDED for job in world.jobs.of_type(JobType.REEMBED))
