"""Settle an asset's processing state once no thumbnail, OCR, or embedding work is left for it.

Without this, assets with nothing (more) to process would keep showing "Indexando": a text file with AI indexing
off never leaves `blob_stored`, a photo stops at `thumbnail_ready`. Peers receive every asset as `indexed`, so the
uploading device must end there too.
"""

from __future__ import annotations

from bento.domain.assets import Asset
from bento.domain.jobs import JobType
from bento.ports.jobs import ActiveJobsPort
from bento.ports.repositories import AssetRepositoryPort, ClockPort

PROCESSING_JOB_TYPES = frozenset(
    {
        JobType.THUMBNAIL,
        JobType.PDF_THUMBNAIL,
        JobType.VIDEO_THUMBNAIL,
        JobType.METADATA,
        JobType.OCR,
        JobType.EMBEDDING,
    }
)


class ProcessingCompletionService:
    def __init__(self, *, assets: AssetRepositoryPort, jobs: ActiveJobsPort, clock: ClockPort) -> None:
        self._assets = assets
        self._jobs = jobs
        self._clock = clock

    async def settle(self, asset_id: str, *, finished_job_id: str | None = None, failed: bool = False) -> Asset | None:
        """Call when a processing job of the asset finished (`failed`: for good). No-op while other work is left."""
        asset = await self._assets.get(asset_id)
        if asset is None:
            return None
        if await self._jobs.has_active(asset.id, types=PROCESSING_JOB_TYPES, exclude_job_id=finished_job_id):
            return asset
        settled = asset.finish_processing(self._clock.now(), failed=failed)
        if settled != asset:
            await self._assets.save(settled)
        return settled
