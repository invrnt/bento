"""Worker side of the storage pipeline: job handlers and the periodic loop (watchers, backfill, retention, cache)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from bento.application.backup import ScanDebouncer
from bento.domain.errors import StorageUnavailableError
from bento.domain.jobs import Job, JobType
from bento.domain.storage import StorageBackend
from bento.infrastructure.storage_pipeline import StoragePipelineComponents
from bento.ports.backup import FolderWatcherPort

LOGGER = logging.getLogger("bento.worker.storage_pipeline")

PIPELINE_JOB_TYPES = frozenset(
    {JobType.REMOTE_UPLOAD, JobType.BACKUP_SCAN, JobType.BACKUP_UPLOAD, JobType.TRASH_PURGE, JobType.CACHE_EVICT}
)


@dataclass(frozen=True, slots=True)
class StoragePipelineJobHandler:
    components: StoragePipelineComponents

    def handles(self, job_type: JobType) -> bool:
        return job_type in PIPELINE_JOB_TYPES

    async def handle(self, job: Job) -> None:
        payload = job.payload
        if job.type == JobType.REMOTE_UPLOAD:
            await self._remote_upload(job)
        elif job.type == JobType.BACKUP_SCAN:
            paths = payload.get("paths")
            await self.components.backup.scan_source(
                str(payload.get("source_id") or ""),
                paths=tuple(str(path) for path in paths) if isinstance(paths, list) else None,
                retry_failed=bool(payload.get("retry_failed")),
            )
        elif job.type == JobType.BACKUP_UPLOAD:
            await self.components.backup.upload_pending()
        elif job.type == JobType.TRASH_PURGE:
            if payload.get("expired"):
                await self.components.trash.purge_expired()
                return
            ids = payload.get("ids")
            result = await self.components.trash.purge(
                tuple(str(item) for item in ids) if isinstance(ids, list) else (), retry_later=False
            )
            if result.deferred:
                raise StorageUnavailableError(StorageBackend.TELEGRAM.value)
        elif job.type == JobType.CACHE_EVICT:
            await self.components.cache.evict(max_bytes=self.components.cache_max_bytes)
        else:
            raise RuntimeError(f"No storage pipeline handler for {job.type.value}")

    async def _remote_upload(self, job: Job) -> None:
        blob_id = job.payload.get("blob_id")
        if not isinstance(blob_id, str) or not blob_id:
            raise RuntimeError("remote_upload job missing blob_id")
        try:
            await self.components.pipeline.upload(blob_id)
        except Exception as exc:
            if job.attempts + 1 < job.max_attempts:
                raise
            # Exhausted: keep a retryable FAILED job so the Actividad panel can offer "Reintentar".
            error = " ".join((str(exc) or exc.__class__.__name__).split())[:500]
            LOGGER.warning("Remote upload of %s failed permanently: %s", blob_id, error)
            await self.components.pipeline.park_failure(blob_id, error)


@dataclass
class StoragePipelineLoop:
    """Periodic, idempotent housekeeping; every step only reads state or enqueues jobs."""

    components: StoragePipelineComponents
    watcher: FolderWatcherPort | None = None
    debouncer: ScanDebouncer = field(default_factory=ScanDebouncer)
    clock: Callable[[], float] = time.monotonic
    tick_seconds: float = 0.5
    sources_interval: float = 30.0
    backfill_interval: float = 120.0
    full_scan_interval: float = 6 * 3600.0
    retention_interval: float = 3600.0
    cache_interval: float = 600.0
    _last: dict[str, float] = field(default_factory=dict)
    _watched: dict[str, str] = field(default_factory=dict)
    _remote_ready: bool = False
    _paused: bool | None = None

    async def run(self, stop_event: asyncio.Event) -> None:
        try:
            while not stop_event.is_set():
                try:
                    await self.tick()
                except Exception as exc:  # housekeeping must never stop the worker
                    LOGGER.warning("Storage pipeline housekeeping failed: %s", exc.__class__.__name__)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=self.tick_seconds)
                except TimeoutError:
                    continue
        finally:
            if self.watcher is not None:
                await asyncio.to_thread(self.watcher.stop)

    async def tick(self) -> None:
        backup = self.components.backup
        for source_id, paths in self.debouncer.due():
            await backup.enqueue_scan(source_id, paths=paths)

        if self._due("sources", self.sources_interval):
            await self._sync_watches()
            paused = (await backup.get_policy()).effective_paused
            if self._paused is True and not paused:
                await backup.enqueue_scans_for_all()
            self._paused = paused

        ready = self.components.pipeline.remote_available()
        became_ready = ready and not self._remote_ready
        self._remote_ready = ready
        if became_ready or (ready and self._due("backfill", self.backfill_interval)):
            if became_ready:
                self._last["backfill"] = self.clock()
            queued = await self.components.pipeline.backfill()
            if queued:
                LOGGER.info("Queued %s local blobs for encrypted upload", queued)

        if self._due("full_scan", self.full_scan_interval):
            await backup.enqueue_scans_for_all()
        if self._due("retention", self.retention_interval):
            if not await self.components.backup_jobs.has_waiting(JobType.TRASH_PURGE):
                await self.components.jobs.enqueue(type=JobType.TRASH_PURGE, priority=7, payload={"expired": True})
        if self._due("cache", self.cache_interval):
            await self.components.request_cache_eviction()

    async def _sync_watches(self) -> None:
        if self.watcher is None:
            return
        sources = {source.id: source for source in await self.components.backup.list_sources() if source.enabled}
        for source_id in set(self._watched) - set(sources):
            await asyncio.to_thread(self.watcher.unwatch, source_id)
            self._watched.pop(source_id, None)
            self.debouncer.discard(source_id)
        for source in sources.values():
            if self._watched.get(source.id) != source.path:
                await asyncio.to_thread(self.watcher.watch, source.id, source.path, self.debouncer.add)
                self._watched[source.id] = source.path

    def _due(self, name: str, interval: float) -> bool:
        now = self.clock()
        last = self._last.get(name)
        if last is not None and now - last < interval:
            return False
        self._last[name] = now
        return True
