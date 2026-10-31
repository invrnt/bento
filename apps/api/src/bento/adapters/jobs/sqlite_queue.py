from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.ids import new_id
from bento.adapters.repositories.mappers import job_from_model, job_to_model
from bento.domain.jobs import Job, JobStatus, JobType
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import JobModel
from bento.ports.repositories import ClockPort


class SQLiteJobQueue:
    def __init__(self, session_factory: sessionmaker[Session], clock: ClockPort) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def enqueue(
        self,
        *,
        type: JobType,
        priority: int,
        payload: dict[str, object],
        asset_id: str | None = None,
        max_attempts: int = 3,
    ) -> Job:
        now = self._clock.now()
        job = Job(
            id=await self.next_id(),
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
        with session_scope(self._session_factory) as session:
            session.add(job_to_model(job))
        return job

    async def next_id(self) -> str:
        return new_id("job")

    async def get(self, job_id: str) -> Job | None:
        with session_scope(self._session_factory) as session:
            model = session.get(JobModel, job_id)
            return job_from_model(model) if model is not None else None

    async def save(self, job: Job) -> None:
        with session_scope(self._session_factory) as session:
            session.merge(job_to_model(job))

    async def list(self, *, cursor: str | None = None, limit: int = 50) -> tuple[tuple[Job, ...], str | None]:
        offset = _decode_cursor(cursor)
        with session_scope(self._session_factory) as session:
            models = list(
                session.scalars(
                    select(JobModel)
                    .order_by(JobModel.updated_at.desc(), JobModel.priority.asc(), JobModel.id.asc())
                    .offset(offset)
                    .limit(limit + 1)
                )
            )
        next_cursor = str(offset + limit) if len(models) > limit else None
        return tuple(job_from_model(model) for model in models[:limit]), next_cursor

    async def claim_next(self, worker_id: str) -> Job | None:
        now = self._clock.now()
        with session_scope(self._session_factory) as session:
            model = session.scalar(
                select(JobModel)
                .where(
                    JobModel.status.in_([JobStatus.QUEUED.value, JobStatus.RETRYING.value]),
                    JobModel.locked_by.is_(None),
                    or_(JobModel.run_after.is_(None), JobModel.run_after <= now),
                )
                .order_by(JobModel.priority.asc(), JobModel.created_at.asc(), JobModel.id.asc())
                .limit(1)
            )
            if model is None:
                return None
            claimed = job_from_model(model).claim(worker_id, now)
            session.merge(job_to_model(claimed))
            return claimed

    async def release_abandoned(self, worker_id: str) -> int:
        """Requeue jobs left running by workers other than `worker_id` (one worker runs at a time)."""
        now = self._clock.now()
        with session_scope(self._session_factory) as session:
            models = session.scalars(
                select(JobModel).where(
                    JobModel.status == JobStatus.RUNNING.value,
                    or_(JobModel.locked_by.is_(None), JobModel.locked_by != worker_id),
                )
            ).all()
            for model in models:
                session.merge(job_to_model(job_from_model(model).release(now)))
            return len(models)

    async def has_active(
        self, asset_id: str, *, types: frozenset[JobType], exclude_job_id: str | None = None
    ) -> bool:
        statement = (
            select(func.count())
            .select_from(JobModel)
            .where(
                JobModel.asset_id == asset_id,
                JobModel.type.in_([job_type.value for job_type in types]),
                JobModel.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value, JobStatus.RETRYING.value]),
            )
        )
        if exclude_job_id is not None:
            statement = statement.where(JobModel.id != exclude_job_id)
        with session_scope(self._session_factory) as session:
            return bool(session.scalar(statement))

    async def complete(self, job_id: str) -> Job | None:
        job = await self.get(job_id)
        if job is None:
            return None
        completed = job.complete(self._clock.now())
        await self.save(completed)
        return completed

    async def fail(self, job_id: str, error: str) -> Job | None:
        job = await self.get(job_id)
        if job is None:
            return None
        failed = job.fail(error, self._clock.now())
        await self.save(failed)
        return failed

    async def retry(self, job_id: str) -> Job | None:
        job = await self.get(job_id)
        if job is None:
            return None
        retried = job.retry(self._clock.now())
        await self.save(retried)
        return retried


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(cursor)
    except ValueError:
        return 0
    return max(value, 0)
