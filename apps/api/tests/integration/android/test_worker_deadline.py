"""Selective claiming, device-condition deferral in SQL, and bounded worker runs (desktop, no Chaquopy)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bento.adapters.jobs import SQLiteJobQueue
from bento.adapters.jobs.sqlite_queue import job_class
from bento.adapters.repositories import SQLiteAssetRepository
from bento.application.work_budget import check_safe_boundary
from bento.domain.assets import AssetKind
from bento.domain.device import DeviceConditions, DevicePolicy, JobClass, WaitReason, job_deferral
from bento.domain.jobs import Job, JobStatus, JobType
from bento.infrastructure.settings import Settings
from bento.interfaces.worker.dispatch import WorkerDispatcher
from bento.interfaces.worker.runtime import WorkerRuntime
from tests.integration.db.support import make_asset, migrated_session_factory

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
METERED = DeviceConditions(metered=True, unmetered=False, charging=False, battery_pct=70)


@dataclass
class Clock:
    current: datetime = NOW

    def now(self) -> datetime:
        return self.current


async def _seed(tmp_path: Path) -> tuple[SQLiteJobQueue, Clock, dict[str, Job]]:
    factory = migrated_session_factory(tmp_path)
    clock = Clock()
    assets = SQLiteAssetRepository(factory)
    await assets.add(make_asset("asset_photo", kind=AssetKind.IMAGE, filename="a.jpg", sha256="a" * 64))
    await assets.add(make_asset("asset_video", kind=AssetKind.VIDEO, filename="v.mp4", sha256="b" * 64))
    queue = SQLiteJobQueue(factory, clock)
    jobs = {
        "photo": await queue.enqueue(type=JobType.REMOTE_UPLOAD, priority=10, payload={"kind": "original"}, asset_id="asset_photo"),
        "video": await queue.enqueue(type=JobType.REMOTE_UPLOAD, priority=10, payload={"kind": "original"}, asset_id="asset_video"),
        "thumb": await queue.enqueue(type=JobType.REMOTE_UPLOAD, priority=11, payload={"kind": "thumbnail"}, asset_id="asset_photo"),
        "ocr": await queue.enqueue(type=JobType.OCR, priority=3, payload={}, asset_id="asset_photo"),
        "scan": await queue.enqueue(type=JobType.BACKUP_SCAN, priority=5, payload={}),
    }
    return queue, clock, jobs


def test_queue_skips_deferred_classes_and_counts_them_by_reason(tmp_path: Path) -> None:
    async def scenario() -> None:
        queue, clock, jobs = await _seed(tmp_path)
        deferral = job_deferral(METERED, DevicePolicy(wifi_only=True, ocr_requires_charging=True))
        assert deferral.reasons == {
            JobClass.ORIGINAL_UPLOAD: WaitReason.WIFI,
            JobClass.VIDEO_UPLOAD: WaitReason.WIFI,
            JobClass.INDEXING: WaitReason.CHARGING,
        }
        backlog = await queue.backlog(deferral=deferral)
        assert backlog.deferred == {WaitReason.WIFI: 2, WaitReason.CHARGING: 1}
        assert backlog.runnable == 2 and backlog.remaining == 5

        claimed = []
        while (job := await queue.claim_next("w", deferral=deferral)) is not None:
            claimed.append(job.id)
        assert claimed == [jobs["scan"].id, jobs["thumb"].id]

        # `kinds` filter.
        assert await queue.claim_next("w", types=frozenset({JobType.OCR})) is not None
        # Run-now: uploads queued before the override ignore the Wi-Fi rule; newer ones keep waiting.
        clock.current = NOW + timedelta(minutes=5)
        later = await queue.enqueue(type=JobType.REMOTE_UPLOAD, priority=10, payload={"kind": "original"}, asset_id="asset_photo")
        overridden = job_deferral(METERED, DevicePolicy(wifi_only=True), wifi_override_before=NOW + timedelta(minutes=1))
        released = [await queue.claim_next("w", deferral=overridden), await queue.claim_next("w", deferral=overridden)]
        assert {job.id for job in released if job} == {jobs["photo"].id, jobs["video"].id}
        assert await queue.claim_next("w", deferral=overridden) is None
        assert (await queue.backlog(deferral=overridden)).deferred == {WaitReason.WIFI: 1}
        assert later.status == JobStatus.QUEUED

    asyncio.run(scenario())


def test_python_job_class_mirrors_sql_classes(tmp_path: Path) -> None:
    async def scenario() -> None:
        _queue, _clock, jobs = await _seed(tmp_path)
        assert job_class(jobs["photo"]) == JobClass.ORIGINAL_UPLOAD
        assert job_class(jobs["video"], is_video=True) == JobClass.VIDEO_UPLOAD
        assert job_class(jobs["thumb"]) == JobClass.DERIVED_UPLOAD
        assert job_class(jobs["ocr"]) == JobClass.INDEXING
        assert job_class(jobs["scan"]) == JobClass.OTHER

    asyncio.run(scenario())


@dataclass
class FakeMedia:
    clock: list[float]
    handled: list[str] = field(default_factory=list)
    step_seconds: float = 4.0
    boundary_inside: bool = False

    async def process_asset_media(self, asset_id: str) -> tuple[()]:
        self.handled.append(asset_id)
        self.clock[0] += self.step_seconds
        if self.boundary_inside:
            check_safe_boundary()
        return ()


def _runtime(queue: SQLiteJobQueue, media: FakeMedia, clock: list[float], tmp_path: Path) -> WorkerRuntime:
    dispatcher = WorkerDispatcher(jobs=queue, media=media, clock=Clock(), worker_id="w")  # type: ignore[arg-type]
    return WorkerRuntime(
        Settings(data_dir=str(tmp_path / "data"), storage_backend="local"),
        mode="drain",
        dispatcher=dispatcher,
        clock=lambda: clock[0],
        wall_clock=lambda: clock[0],
    )


def test_run_until_stops_at_the_deadline_between_jobs_and_reports_the_backlog(tmp_path: Path) -> None:
    async def scenario() -> None:
        factory = migrated_session_factory(tmp_path)
        queue = SQLiteJobQueue(factory, Clock())
        for index in range(5):
            await queue.enqueue(type=JobType.THUMBNAIL, priority=1, payload={"asset_id": f"asset_{index}"})
        await queue.enqueue(type=JobType.OCR, priority=0, payload={"asset_id": "asset_ocr"})
        clock = [1000.0]
        media = FakeMedia(clock)
        runtime = _runtime(queue, media, clock, tmp_path)

        result = await runtime.run_until(int((clock[0] + 10) * 1000), ["thumbnail"])
        assert result.stopped_reason == "deadline"
        assert result.ran == 3 and len(media.handled) == 3  # 4 s each, 10 s budget: stops between jobs
        assert result.remaining == 2  # thumbnails left; the OCR job is outside `kinds`

        result = await runtime.run_until(int((clock[0] + 60) * 1000), ["thumbnail"])
        assert result.stopped_reason == "idle" and result.ran == 2
        assert result.as_dict()["next_eligible_at"] is None

    asyncio.run(scenario())


def test_a_job_stopped_at_a_safe_boundary_is_requeued_without_an_attempt(tmp_path: Path) -> None:
    async def scenario() -> None:
        factory = migrated_session_factory(tmp_path)
        queue = SQLiteJobQueue(factory, Clock())
        job = await queue.enqueue(type=JobType.THUMBNAIL, priority=1, payload={"asset_id": "asset_1"})
        clock = [0.0]
        media = FakeMedia(clock, step_seconds=30, boundary_inside=True)
        runtime = _runtime(queue, media, clock, tmp_path)

        result = await runtime.run_until(int(10 * 1000), None)
        assert result.stopped_reason == "deadline" and result.ran == 0
        stored = await queue.get(job.id)
        assert stored is not None and stored.status == JobStatus.RETRYING and stored.attempts == 0
        assert stored.locked_by is None

    asyncio.run(scenario())
