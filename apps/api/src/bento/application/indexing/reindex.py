"""`reindex` job (`POST /api/admin/reindex`): queue OCR and embeddings again for this device's own files.

Files obtained from Telegram (Inbox, imports) and assets that arrived from other devices are skipped: Telegram's API
terms forbid feeding its data to ML models, and peers publish their own index.
"""

from __future__ import annotations

from typing import Protocol

from bento.domain.assets import Asset, supports_ocr
from bento.domain.jobs import JobPriority, JobType
from bento.ports.jobs import ActiveJobsPort, JobQueuePort

REINDEX_PAGE_SIZE = 200


class IndexableAssetsPort(Protocol):
    async def list_live(self, *, after_id: str | None = None, limit: int = 200) -> tuple[Asset, ...]: ...


class ReindexService:
    def __init__(
        self,
        *,
        assets: IndexableAssetsPort,
        jobs: JobQueuePort,
        active: ActiveJobsPort,
        ocr_enabled: bool,
        embeddings_enabled: bool,
    ) -> None:
        self._assets = assets
        self._jobs = jobs
        self._active = active
        self._ocr_enabled = ocr_enabled
        self._embeddings_enabled = embeddings_enabled

    async def run(self) -> int:
        """Returns how many jobs were queued. Assets that already wait for a job of that type are not queued twice."""
        if not (self._ocr_enabled or self._embeddings_enabled):
            return 0
        queued = 0
        after: str | None = None
        while True:
            page = await self._assets.list_live(after_id=after, limit=REINDEX_PAGE_SIZE)
            for asset in page:
                if not asset.ai_indexing_allowed:
                    continue
                if self._ocr_enabled and supports_ocr(asset.kind):
                    queued += await self._queue(asset, JobType.OCR, JobPriority.OCR)
                if self._embeddings_enabled:
                    queued += await self._queue(asset, JobType.EMBEDDING, JobPriority.EMBEDDING)
            if len(page) < REINDEX_PAGE_SIZE:
                return queued
            after = page[-1].id

    async def _queue(self, asset: Asset, job_type: JobType, priority: JobPriority) -> int:
        if await self._active.has_active(asset.id, types=frozenset({job_type})):
            return 0
        await self._jobs.enqueue(type=job_type, priority=int(priority), payload={"asset_id": asset.id}, asset_id=asset.id)
        return 1
