"""`reindex` job (`POST /api/admin/reindex`): queue OCR and embeddings again for this device's own files.

Files obtained from Telegram (Inbox, imports) and assets that arrived from other devices are skipped: Telegram's API
terms forbid feeding its data to ML models, and peers publish their own index.

Space-aware: embedding jobs name the embedding space they fill (`payload.space_id`, the active space when one is
known), and `missing_only` skips assets that already have vectors in that space.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from bento.domain.assets import Asset, supports_ocr
from bento.domain.jobs import JobPriority, JobType
from bento.ports.jobs import ActiveJobsPort, JobQueuePort

REINDEX_PAGE_SIZE = 200


class IndexableAssetsPort(Protocol):
    async def list_live(self, *, after_id: str | None = None, limit: int = 200) -> tuple[Asset, ...]: ...


class ActiveSpacePort(Protocol):
    async def active_space_id(self) -> str | None: ...


class SpaceVectorsPort(Protocol):
    async def assets_with_vectors(self, space_id: str, asset_ids: Sequence[str]) -> frozenset[str]: ...


async def own_indexable_pages(
    assets: IndexableAssetsPort, *, page_size: int = REINDEX_PAGE_SIZE
) -> AsyncIterator[tuple[Asset, ...]]:
    """Keyset pages of live assets that this device may index (`ai_indexing_allowed`); empty pages are skipped."""
    after: str | None = None
    while True:
        page = await assets.list_live(after_id=after, limit=page_size)
        own = tuple(asset for asset in page if asset.ai_indexing_allowed)
        if own:
            yield own
        if len(page) < page_size:
            return
        after = page[-1].id


def embedding_payload(asset_id: str, space_id: str | None) -> dict[str, object]:
    payload: dict[str, object] = {"asset_id": asset_id}
    if space_id is not None:
        payload["space_id"] = space_id
    return payload


class ReindexService:
    def __init__(
        self,
        *,
        assets: IndexableAssetsPort,
        jobs: JobQueuePort,
        active: ActiveJobsPort,
        ocr_enabled: bool,
        embeddings_enabled: bool,
        spaces: ActiveSpacePort | None = None,
        vectors: SpaceVectorsPort | None = None,
        page_size: int = REINDEX_PAGE_SIZE,
    ) -> None:
        self._assets = assets
        self._jobs = jobs
        self._active = active
        self._ocr_enabled = ocr_enabled
        self._embeddings_enabled = embeddings_enabled
        self._spaces = spaces
        self._vectors = vectors
        self._page_size = max(page_size, 1)

    async def run(self, *, space_id: str | None = None, missing_only: bool = False) -> int:
        """Returns how many jobs were queued. Assets that already wait for a job of that type are not queued twice.

        `space_id` defaults to the active space. `missing_only` (needs a vector port and a space) queues
        embeddings only for assets without vectors in that space.
        """
        if not (self._ocr_enabled or self._embeddings_enabled):
            return 0
        target = space_id
        if target is None and self._embeddings_enabled and self._spaces is not None:
            target = await self._spaces.active_space_id()
        queued = 0
        async for page in own_indexable_pages(self._assets, page_size=self._page_size):
            embedded = await self._embedded(target, page) if missing_only else frozenset()
            for asset in page:
                if self._ocr_enabled and supports_ocr(asset.kind):
                    queued += await self._queue(asset, JobType.OCR, JobPriority.OCR, {"asset_id": asset.id})
                if self._embeddings_enabled and asset.id not in embedded:
                    queued += await self._queue(
                        asset, JobType.EMBEDDING, JobPriority.EMBEDDING, embedding_payload(asset.id, target)
                    )
        return queued

    async def _embedded(self, space_id: str | None, page: tuple[Asset, ...]) -> frozenset[str]:
        if space_id is None or self._vectors is None:
            return frozenset()
        return await self._vectors.assets_with_vectors(space_id, [asset.id for asset in page])

    async def _queue(self, asset: Asset, job_type: JobType, priority: JobPriority, payload: dict[str, object]) -> int:
        if await self._active.has_active(asset.id, types=frozenset({job_type})):
            return 0
        await self._jobs.enqueue(type=job_type, priority=int(priority), payload=payload, asset_id=asset.id)
        return 1
