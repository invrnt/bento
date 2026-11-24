from __future__ import annotations

from sqlalchemy import ColumnElement, and_, false, func, not_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.ids import new_id
from bento.adapters.repositories.mappers import aware, job_from_model, job_to_model
from bento.domain.device import JobClass, JobDeferral, WaitReason
from bento.domain.jobs import Job, JobStatus, JobType
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AssetModel, JobModel
from bento.ports.jobs import JobBacklog
from bento.ports.repositories import ClockPort

_WAITING = (JobStatus.QUEUED.value, JobStatus.RETRYING.value)


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

    async def claim_next(
        self,
        worker_id: str,
        *,
        types: frozenset[JobType] | None = None,
        deferral: JobDeferral | None = None,
    ) -> Job | None:
        """The next due job by priority; `types` limits the job types, `deferral` skips deferred job classes."""
        now = self._clock.now()
        with session_scope(self._session_factory) as session:
            statement = select(JobModel).where(
                JobModel.status.in_(_WAITING),
                JobModel.locked_by.is_(None),
                or_(JobModel.run_after.is_(None), JobModel.run_after <= now),
            )
            if types is not None:
                statement = statement.where(JobModel.type.in_(sorted(job_type.value for job_type in types)))
            if deferral is not None and not deferral.empty:
                statement = statement.where(not_(_deferred_condition(deferral)))
            model = session.scalar(
                statement.order_by(JobModel.priority.asc(), JobModel.created_at.asc(), JobModel.id.asc()).limit(1)
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

    async def backlog(
        self, *, types: frozenset[JobType] | None = None, deferral: JobDeferral | None = None
    ) -> JobBacklog:
        now = self._clock.now()
        waiting = [JobModel.status.in_(_WAITING), JobModel.locked_by.is_(None)]
        if types is not None:
            waiting.append(JobModel.type.in_(sorted(job_type.value for job_type in types)))
        due = or_(JobModel.run_after.is_(None), JobModel.run_after <= now)
        deferred: dict[WaitReason, int] = {}
        with session_scope(self._session_factory) as session:
            counted: ColumnElement[bool] = false()
            if deferral is not None:
                for job_class, reason in deferral.reasons.items():
                    condition = _class_condition(job_class, deferral)
                    count = int(session.scalar(select(func.count()).where(*waiting, due, condition, not_(counted))) or 0)
                    if count:
                        deferred[reason] = deferred.get(reason, 0) + count
                    counted = or_(counted, condition)
            runnable = int(session.scalar(select(func.count()).where(*waiting, due, not_(counted))) or 0)
            scheduled = int(session.scalar(select(func.count()).where(*waiting, not_(due))) or 0)
            next_run_after = session.scalar(select(func.min(JobModel.run_after)).where(*waiting, not_(due)))
        return JobBacklog(
            runnable=runnable,
            deferred=deferred,
            scheduled=scheduled,
            next_run_after=aware(next_run_after) if next_run_after is not None else None,
        )

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


def _deferred_condition(deferral: JobDeferral) -> ColumnElement[bool]:
    return or_(false(), *(_class_condition(job_class, deferral) for job_class in deferral.reasons))


def _class_condition(job_class: JobClass, deferral: JobDeferral) -> ColumnElement[bool]:
    """SQL for "a job of `job_class` that `deferral` holds back" (see `domain/device.py`)."""
    kind = func.json_extract(JobModel.payload_json, "$.kind")
    videos = select(AssetModel.id).where(AssetModel.kind == "video")
    remote = JobModel.type == JobType.REMOTE_UPLOAD.value
    if job_class == JobClass.ORIGINAL_UPLOAD:
        condition = and_(remote, kind == "original", or_(JobModel.asset_id.is_(None), JobModel.asset_id.not_in(videos)))
    elif job_class == JobClass.VIDEO_UPLOAD:
        condition = and_(remote, kind == "original", JobModel.asset_id.in_(videos))
    elif job_class == JobClass.DERIVED_UPLOAD:
        condition = and_(remote, or_(kind.is_(None), kind != "original"))
    elif job_class == JobClass.INDEXING:
        condition = JobModel.type.in_((JobType.OCR.value, JobType.EMBEDDING.value))
    elif job_class == JobClass.BULK_LOCAL:
        condition = JobModel.type == JobType.BACKUP_UPLOAD.value
    else:
        return false()
    cutoff = deferral.wifi_override_before
    if cutoff is not None and deferral.reasons.get(job_class) == WaitReason.WIFI:
        # `POST /backup/run-now`: uploads queued before the override run anyway; newer ones keep waiting.
        condition = and_(condition, JobModel.created_at > cutoff)
    return condition


def job_class(job: Job, *, is_video: bool = False) -> JobClass:
    """Python mirror of `_class_condition` for one job (asset kind supplied by the caller)."""
    if job.type == JobType.REMOTE_UPLOAD:
        if job.payload.get("kind") == "original":
            return JobClass.VIDEO_UPLOAD if is_video else JobClass.ORIGINAL_UPLOAD
        return JobClass.DERIVED_UPLOAD
    if job.type in {JobType.OCR, JobType.EMBEDDING}:
        return JobClass.INDEXING
    if job.type == JobType.BACKUP_UPLOAD:
        return JobClass.BULK_LOCAL
    return JobClass.OTHER
