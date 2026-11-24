"""The worker as a reusable runtime: the desktop worker process, and the Android engine's worker thread.

Modes:
- `full`: job loop plus the Inbox loop (Telegram activity waits), storage-pipeline housekeeping with the folder
  watcher, and the sync loop. This is exactly the desktop worker.
- `drain`: no Inbox loop and no folder watcher; jobs run only inside `run_until` calls (Android background work).
  The sync loop and storage housekeeping still run while the runtime is up, so periodic runs pull and flush.

`run_until(deadline, kinds)` runs eligible jobs until the deadline or until nothing eligible is left, stopping only
between jobs or at a handler's safe boundary (`application/work_budget.py`). Jobs held back by device conditions
are skipped, and the result says so. One job runs at a time (`worker_concurrency` stays 1).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from bento.application.work_budget import WorkBudgetExceeded, work_deadline
from bento.domain.jobs import JobType
from bento.infrastructure import services
from bento.infrastructure.settings import Settings
from bento.interfaces.worker.dispatch import WorkerDispatcher
from bento.ports.jobs import JobBacklog

LOGGER = logging.getLogger("bento.worker")

WorkerMode = Literal["full", "drain"]
StoppedReason = Literal["idle", "deadline", "conditions", "error", "stopped"]
IDLE_POLL_SECONDS = 1.0
ANNOUNCE_INTERVAL_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class RunResult:
    ran: int
    remaining: int
    next_eligible_at: datetime | None
    stopped_reason: StoppedReason
    waiting: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "ran": self.ran,
            "remaining": self.remaining,
            "next_eligible_at": int(self.next_eligible_at.timestamp() * 1000) if self.next_eligible_at else None,
            "stopped_reason": self.stopped_reason,
            "waiting": dict(self.waiting),
        }


class WorkerRuntime:
    def __init__(
        self,
        settings: Settings,
        *,
        mode: WorkerMode = "full",
        dispatcher: WorkerDispatcher | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if mode not in ("full", "drain"):
            raise ValueError(f"Unknown worker mode: {mode}")
        self.settings = settings
        self.mode: WorkerMode = mode
        self._dispatcher = dispatcher
        self._clock = clock
        self._wall_clock = wall_clock
        self._eligibility = services.get_job_eligibility(settings)
        self._job_lock: asyncio.Lock | None = None
        self._wake: asyncio.Event | None = None
        self._announced_at = float("-inf")

    @property
    def dispatcher(self) -> WorkerDispatcher:
        if self._dispatcher is None:
            from bento.interfaces.worker.main import _create_dispatcher

            self._dispatcher = _create_dispatcher(worker_id=f"worker-{os.getpid()}", settings=self.settings)
        return self._dispatcher

    def wake(self) -> None:
        """Re-check the queue now (new conditions, new media); call on the runtime's loop."""
        if self._wake is not None:
            self._wake.set()

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run until `stop_event`: background loops always, the job loop only in `full` mode."""
        from bento.adapters.sync import configure_change_capture
        from bento.infrastructure.storage_pipeline import get_storage_pipeline
        from bento.interfaces.worker.storage_pipeline import StoragePipelineLoop
        from bento.interfaces.worker.sync_loop import start_sync_loop, stop_sync_loop
        from bento.interfaces.worker.telegram import run_inbox_loop

        settings = self.settings
        LOGGER.info(
            "Worker started in %s mode (%s) with concurrency=%s", settings.storage_backend, self.mode, settings.worker_concurrency
        )
        self._job_lock = asyncio.Lock()
        self._wake = asyncio.Event()
        configure_change_capture(settings.storage_backend != "local")
        dispatcher = self.dispatcher
        released = await dispatcher.jobs.release_abandoned(dispatcher.worker_id)
        if released:
            LOGGER.info("Requeued %s jobs left running by a previous worker", released)
        tasks: list[asyncio.Task[None]] = []
        if self.mode == "full":
            tasks.append(asyncio.create_task(run_inbox_loop(settings, stop_event), name="bento-inbox-loop"))
        watcher = services.get_folder_watcher(settings) if self.mode == "full" else None
        pipeline_loop = asyncio.create_task(
            StoragePipelineLoop(get_storage_pipeline(settings), watcher=watcher).run(stop_event), name="bento-pipeline-loop"
        )
        sync_task = start_sync_loop(settings, stop_event)
        try:
            while not stop_event.is_set():
                if self.mode == "full" and await self._process_one():
                    continue
                await self._announce_attention()
                self._flush_notifications()
                self._wake.clear()
                waiters = [asyncio.ensure_future(stop_event.wait()), asyncio.ensure_future(self._wake.wait())]
                try:
                    await asyncio.wait(waiters, timeout=IDLE_POLL_SECONDS, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for waiter in waiters:
                        waiter.cancel()
        finally:
            stop_event.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            await pipeline_loop
            await stop_sync_loop(sync_task)

    async def _announce_attention(self, *, force: bool = False) -> None:
        """At most every `ANNOUNCE_INTERVAL_SECONDS` (and at the end of bounded runs): notify new Activity items."""
        now = self._clock()
        if not force and now - self._announced_at < ANNOUNCE_INTERVAL_SECONDS:
            return
        self._announced_at = now
        from bento.infrastructure.storage_pipeline import get_storage_pipeline

        try:
            await get_storage_pipeline(self.settings).activity.announce()
        except Exception as exc:  # noqa: BLE001 - notifications are best effort
            LOGGER.debug("Attention announcement skipped: %s", exc.__class__.__name__)

    def _flush_notifications(self) -> None:
        """Deliver progress the 1 Hz limiter is still holding once its window has closed."""
        flush = getattr(services.get_notifier(self.settings), "flush", None)
        if callable(flush):
            flush()

    async def run_until(self, deadline_epoch_ms: int, kinds: list[str] | None = None) -> RunResult:
        """Run eligible jobs (of `kinds`, or all) until `deadline_epoch_ms` or until none is eligible."""
        types = _job_types(kinds)
        deadline = self._clock() + max(0.0, deadline_epoch_ms / 1000 - self._wall_clock())
        ran = 0
        reason: StoppedReason = "idle"
        try:
            while True:
                if self._clock() >= deadline:
                    reason = "deadline"
                    break
                with work_deadline(deadline, clock=self._clock):
                    processed = await self._process_one(types=types)
                if not processed:
                    reason = "idle"
                    break
                ran += 1
        except WorkBudgetExceeded:
            reason = "deadline"
        except Exception:  # noqa: BLE001 - reported to the host; the job itself was failed by the dispatcher
            LOGGER.exception("Bounded worker run failed")
            reason = "error"
        await self._announce_attention(force=True)
        self._flush_notifications()
        backlog = await self.backlog(types)
        if reason == "idle" and backlog.deferred and not backlog.runnable:
            reason = "conditions"
        return RunResult(
            ran=ran,
            remaining=backlog.remaining,
            next_eligible_at=backlog.next_run_after,
            stopped_reason=reason,
            waiting={key.value: value for key, value in backlog.deferred.items()},
        )

    async def backlog(self, types: frozenset[JobType] | None = None) -> JobBacklog:
        jobs = self.dispatcher.jobs
        backlog = getattr(jobs, "backlog", None)
        if backlog is None:
            return JobBacklog()
        return await backlog(types=types, deferral=self._eligibility.current())

    async def _process_one(self, *, types: frozenset[JobType] | None = None) -> bool:
        lock = self._job_lock or asyncio.Lock()
        self._job_lock = lock
        async with lock:
            return await self.dispatcher.process_one(types=types, deferral=self._eligibility.current())


def _job_types(kinds: list[str] | None) -> frozenset[JobType] | None:
    if kinds is None:
        return None
    try:
        return frozenset(JobType(kind) for kind in kinds)
    except ValueError as exc:
        raise ValueError(f"Unknown job kind: {exc}") from None
