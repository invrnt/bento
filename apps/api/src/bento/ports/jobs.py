from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from bento.domain.device import JobDeferral, WaitReason
from bento.domain.jobs import Job, JobType


@dataclass(frozen=True, slots=True)
class JobBacklog:
    """Queued/retrying jobs (optionally of some types) as the worker sees them now."""

    runnable: int = 0
    deferred: dict[WaitReason, int] = field(default_factory=dict)
    scheduled: int = 0
    next_run_after: datetime | None = None

    @property
    def remaining(self) -> int:
        return self.runnable + sum(self.deferred.values()) + self.scheduled


class JobQueuePort(Protocol):
    async def enqueue(
        self,
        *,
        type: JobType,
        priority: int,
        payload: dict[str, object],
        asset_id: str | None = None,
        max_attempts: int = 3,
    ) -> Job: ...

    async def get(self, job_id: str) -> Job | None: ...

    async def save(self, job: Job) -> None: ...

    async def list(self, *, cursor: str | None = None, limit: int = 50) -> tuple[tuple[Job, ...], str | None]: ...

    async def claim_next(self, worker_id: str) -> Job | None: ...

    async def release_abandoned(self, worker_id: str) -> int:
        """Requeue jobs left running by a worker that is no longer alive; returns how many."""
        ...


class SelectiveJobQueuePort(JobQueuePort, Protocol):
    """A queue that can claim by job type and skip jobs deferred by device conditions."""

    async def claim_next(
        self,
        worker_id: str,
        *,
        types: frozenset[JobType] | None = None,
        deferral: JobDeferral | None = None,
    ) -> Job | None: ...

    async def backlog(
        self, *, types: frozenset[JobType] | None = None, deferral: JobDeferral | None = None
    ) -> JobBacklog: ...


class ActiveJobsPort(Protocol):
    async def has_active(
        self, asset_id: str, *, types: frozenset[JobType], exclude_job_id: str | None = None
    ) -> bool:
        """Whether the asset has queued, running, or retrying jobs of these types (other than `exclude_job_id`)."""
        ...
