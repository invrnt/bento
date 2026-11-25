from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from bento.domain.device import (
    NO_DEFERRAL,
    PERMISSIVE_CONDITIONS,
    DeviceConditions,
    DevicePolicy,
    JobDeferral,
    job_deferral,
)
from bento.domain.errors import JobNotFoundError
from bento.domain.jobs import Job
from bento.ports.device import DeviceConditionsPort
from bento.ports.jobs import JobQueuePort
from bento.ports.repositories import ClockPort


@dataclass(frozen=True, slots=True)
class ListJobsQuery:
    cursor: str | None = None
    limit: int = 50


@dataclass(frozen=True, slots=True)
class ListJobsResult:
    items: tuple[Job, ...]
    next_cursor: str | None


class JobsUseCases:
    def __init__(self, *, jobs: JobQueuePort, clock: ClockPort) -> None:
        self._jobs = jobs
        self._clock = clock

    async def list_jobs(self, query: ListJobsQuery) -> ListJobsResult:
        items, next_cursor = await self._jobs.list(cursor=query.cursor, limit=query.limit)
        return ListJobsResult(items=items, next_cursor=next_cursor)

    async def retry_failed_job(self, job_id: str) -> Job:
        job = await self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        updated = job.retry(self._clock.now())
        await self._jobs.save(updated)
        return updated


class JobEligibility:
    """The current job deferral: device conditions x device policy settings x the run-now override."""

    def __init__(
        self,
        *,
        conditions: DeviceConditionsPort,
        policy: Callable[[], DevicePolicy],
        run_now: Callable[[], datetime | None] = lambda: None,
    ) -> None:
        self._conditions = conditions
        self._policy = policy
        self._run_now = run_now

    def current(self) -> JobDeferral:
        conditions = self._conditions.snapshot()
        if conditions == PERMISSIVE_CONDITIONS:
            return NO_DEFERRAL
        return job_deferral(conditions, self._policy(), wifi_override_before=self._run_now())

    def conditions(self) -> DeviceConditions:
        return self._conditions.snapshot()


class AlwaysEligible:
    """Desktop/headless: nothing is ever deferred."""

    def current(self) -> JobDeferral:
        return NO_DEFERRAL

    def conditions(self) -> DeviceConditions:
        return PERMISSIVE_CONDITIONS
