from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bento.application.indexing.embedding import EmbeddingIndexingService
from bento.application.indexing import OCRIndexingService
from bento.application.indexing.reindex import ReindexService
from bento.application.media import PROCESSING_JOB_TYPES, MediaProcessingService, ProcessingCompletionService
from bento.domain.jobs import Job, JobStatus, JobType
from bento.ports.jobs import JobQueuePort
from bento.ports.repositories import ClockPort

if TYPE_CHECKING:
    from bento.interfaces.worker.storage_pipeline import StoragePipelineJobHandler
    from bento.interfaces.worker.telegram import TelegramJobHandlers


LOGGER = logging.getLogger("bento.worker.dispatch")


@dataclass(frozen=True, slots=True)
class WorkerDispatcher:
    jobs: JobQueuePort
    media: MediaProcessingService
    clock: ClockPort
    worker_id: str
    ocr: OCRIndexingService | None = None
    embedding: EmbeddingIndexingService | None = None
    telegram: TelegramJobHandlers | None = None
    storage_pipeline: StoragePipelineJobHandler | None = None
    sync_snapshot: Callable[[Job], Awaitable[None]] | None = None
    processing: ProcessingCompletionService | None = None
    reindex: ReindexService | None = None

    async def process_one(self) -> bool:
        job = await self.jobs.claim_next(self.worker_id)
        if job is None:
            return False
        try:
            await self._handle(job)
        except Exception as exc:
            safe_error = _safe_error(exc)
            LOGGER.warning("Job %s failed: %s", job.id, safe_error)
            failed = job.fail(safe_error, self.clock.now())
            await self.jobs.save(failed)
            if failed.status == JobStatus.FAILED:
                await self._settle(job, failed=True)
        else:
            await self.jobs.save(job.complete(self.clock.now()))
            await self._settle(job, failed=False)
        return True

    async def _settle(self, job: Job, *, failed: bool) -> None:
        """After the last thumbnail/OCR/embedding job of an asset, move it to its terminal processing state."""
        if self.processing is None or job.type not in PROCESSING_JOB_TYPES:
            return
        asset_id = job.asset_id or job.payload.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id:
            return
        try:
            await self.processing.settle(asset_id, finished_job_id=job.id, failed=failed)
        except Exception as exc:  # noqa: BLE001 - settling is bookkeeping; it never fails the job
            LOGGER.warning("Could not settle the processing state of %s: %s", asset_id, exc.__class__.__name__)

    async def _handle(self, job: Job) -> None:
        if self.telegram is not None and self.telegram.handles(job):
            await self.telegram.handle(job)
            return
        if self.storage_pipeline is not None and self.storage_pipeline.handles(job.type):
            await self.storage_pipeline.handle(job)
            return
        if job.type in {JobType.THUMBNAIL, JobType.PDF_THUMBNAIL, JobType.VIDEO_THUMBNAIL}:
            asset_id = job.asset_id or _payload_asset_id(job)
            await self.media.process_asset_media(asset_id)
            return
        if job.type == JobType.OCR:
            if self.ocr is None:
                raise RuntimeError("No OCR handler registered")
            asset_id = job.asset_id or _payload_asset_id(job)
            await self.ocr.process_asset_ocr(asset_id)
            return
        if job.type == JobType.EMBEDDING:
            if self.embedding is None:
                raise RuntimeError("No embedding handler registered")
            asset_id = job.asset_id or _payload_asset_id(job)
            await self.embedding.process_asset_embedding(asset_id)
            return
        if job.type == JobType.SYNC_SNAPSHOT and self.sync_snapshot is not None:
            await self.sync_snapshot(job)
            return
        if job.type == JobType.REINDEX and self.reindex is not None:
            queued = await self.reindex.run()
            LOGGER.info("Reindex queued %s indexing jobs", queued)
            return
        raise RuntimeError(f"No handler registered for job type {job.type.value}")


def _payload_asset_id(job: Job) -> str:
    asset_id = job.payload.get("asset_id")
    if isinstance(asset_id, str) and asset_id:
        return asset_id
    raise RuntimeError("Media job missing asset_id")


def _safe_error(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    return " ".join(message.split())[:500]
