from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from bento.adapters.jobs.sqlite_queue import SQLiteJobQueue
from bento.domain.jobs import JobStatus, JobType
from bento.infrastructure.db.base import Base
from bento.infrastructure.db.engine import create_session_factory, sqlite_url


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def test_release_abandoned_requeues_jobs_from_dead_workers(tmp_path) -> None:
    factory = create_session_factory(sqlite_url(tmp_path / "jobs.sqlite3"))
    Base.metadata.create_all(factory.kw["bind"])
    queue = SQLiteJobQueue(factory, _Clock())

    async def scenario() -> tuple[int, list[JobStatus], int]:
        first = await queue.enqueue(type=JobType.THUMBNAIL, priority=1, payload={})
        second = await queue.enqueue(type=JobType.THUMBNAIL, priority=1, payload={})
        await queue.claim_next("worker-dead")
        mine = await queue.claim_next("worker-alive")
        released = await queue.release_abandoned("worker-alive")
        statuses = [(await queue.get(job.id)).status for job in (first, second)]
        reclaimed = await queue.claim_next("worker-alive")
        attempts = reclaimed.attempts if reclaimed else -1
        assert mine is not None and mine.locked_by == "worker-alive"
        return released, statuses, attempts

    released, statuses, attempts = asyncio.run(scenario())

    assert released == 1
    assert sorted(statuses) == sorted([JobStatus.RETRYING, JobStatus.RUNNING])
    assert attempts == 0
