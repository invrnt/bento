from __future__ import annotations

from typing import Protocol

from bento.domain.jobs import Job, JobType


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


class ActiveJobsPort(Protocol):
    async def has_active(
        self, asset_id: str, *, types: frozenset[JobType], exclude_job_id: str | None = None
    ) -> bool:
        """Whether the asset has queued, running, or retrying jobs of these types (other than `exclude_job_id`)."""
        ...
