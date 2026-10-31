from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bento.application.indexing.embedding import EmbeddingIndexingService
from bento.application.indexing import OCRIndexingService
from bento.application.media import MediaProcessingService
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

    async def process_one(self) -> bool:
        job = await self.jobs.claim_next(self.worker_id)
        if job is None:
            return False
        try:
            await self._handle(job)
        except Exception as exc:
            safe_error = _safe_error(exc)
            LOGGER.warning("Job %s failed: %s", job.id, safe_error)
            await self.jobs.save(job.fail(safe_error, self.clock.now()))
        else:
            await self.jobs.save(job.complete(self.clock.now()))
        return True

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
        raise RuntimeError(f"No handler registered for job type {job.type.value}")


def _payload_asset_id(job: Job) -> str:
    asset_id = job.payload.get("asset_id")
    if isinstance(asset_id, str) and asset_id:
        return asset_id
    raise RuntimeError("Media job missing asset_id")


def _safe_error(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    return " ".join(message.split())[:500]
