"""`text_extract` job: index the text a document already contains, without OCR.

Plain text files (`text/plain`, `text/markdown`, `text/csv`) and the text layer of PDFs are read through a
`TextExtractorPort` and stored as the asset's document text, which full-text search and the embedding text read.
It runs after thumbnails and before OCR and embeddings, whether OCR is enabled or not.

PDFs: a text layer that is near-empty (`usable_text_layer`) is not stored while OCR is enabled, so OCR reads the
pages as before; when both exist the text layer wins (OCR skips PDFs that have document text, and FTS and the
embedding text prefer it). Only this device's own files are read, as for OCR (`Asset.ai_indexing_allowed`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from bento.application.media.service import BlobPathResolverPort, BlobRefCatalogPort
from bento.application.sync.ports import AssetIndexRecorderPort
from bento.application.work_budget import check_safe_boundary
from bento.domain.assets import Asset, AssetKind
from bento.domain.errors import AssetNotFoundError
from bento.domain.indexing import ExtractedPage, ExtractedText, usable_text_layer
from bento.domain.jobs import JobPriority, JobType
from bento.domain.storage import BlobKind
from bento.ports.jobs import ActiveJobsPort, JobQueuePort
from bento.ports.providers import TextExtractorPort
from bento.ports.repositories import AssetRepositoryPort

LOGGER = logging.getLogger("bento.indexing.text")

_EMBEDDING_TYPES = frozenset({JobType.EMBEDDING})


class DocumentTextStorePort(Protocol):
    """Where FTS and the embedding text read document text (`asset_text` rows with `source = "document"`)."""

    async def replace_document_text(self, asset_id: str, pages: Sequence[ExtractedPage]) -> None:
        """Replace the asset's document text with `pages` (none: remove it) and refresh its FTS row."""
        ...


class PDFPageTextPort(Protocol):
    async def save_page_text(self, *, asset_id: str, page_number: int, text: str) -> None: ...


class TextExtractionService:
    def __init__(
        self,
        *,
        assets: AssetRepositoryPort,
        blob_refs: BlobRefCatalogPort,
        resolver: BlobPathResolverPort,
        extractor: TextExtractorPort,
        store: DocumentTextStorePort,
        ocr_enabled: Callable[[], bool] = lambda: False,
        embeddings_enabled: Callable[[], bool] = lambda: False,
        jobs: JobQueuePort | None = None,
        active: ActiveJobsPort | None = None,
        pdf_pages: PDFPageTextPort | None = None,
        index_recorder: AssetIndexRecorderPort | None = None,
    ) -> None:
        self._assets = assets
        self._blob_refs = blob_refs
        self._resolver = resolver
        self._extractor = extractor
        self._store = store
        self._ocr_enabled = ocr_enabled
        self._embeddings_enabled = embeddings_enabled
        self._jobs = jobs
        self._active = active
        self._pdf_pages = pdf_pages
        self._index_recorder = index_recorder

    def eligible(self, asset: Asset) -> bool:
        return asset.ai_indexing_allowed and not asset.is_deleted and self._extractor.supports(asset.metadata.mime_type)

    async def process_asset_text(self, asset_id: str) -> ExtractedText | None:
        """The text stored for the asset, or None when the asset is not processed here."""
        asset = await self._assets.get(asset_id)
        if asset is None:
            raise AssetNotFoundError(asset_id)
        if not asset.ai_indexing_allowed:
            LOGGER.info(
                "Skipped text extraction of asset %s (origin %s): only this device's own files are indexed",
                asset.id,
                asset.origin,
            )
            return None
        if not self.eligible(asset):
            return None
        original_ref = await self._blob_refs.latest_for_asset(asset.id, BlobKind.ORIGINAL)
        if original_ref is None:
            raise AssetNotFoundError(asset_id)
        source_path = self._resolver.resolve(original_ref)
        if not Path(source_path).exists():
            # An original that is only in the remote store (evicted from the cache): nothing to read locally.
            LOGGER.info("Skipped text extraction of asset %s: the original is not on this device", asset.id)
            return None

        extracted = await self._extractor.extract(
            Path(source_path), asset.metadata.mime_type, checkpoint=check_safe_boundary
        )
        kept = self._kept(asset, extracted)
        await self._store.replace_document_text(asset.id, kept.pages)
        if kept.empty:
            return kept
        await self._save_pdf_pages(asset, kept)
        await self._record_index(asset.id, kept)
        await self._refresh_embedding(asset)
        return kept

    def _kept(self, asset: Asset, extracted: ExtractedText) -> ExtractedText:
        """A PDF's near-empty text layer is dropped while OCR is enabled: OCR reads those pages instead."""
        if extracted.empty:
            return ExtractedText(pages_read=extracted.pages_read, truncated=extracted.truncated)
        if asset.kind == AssetKind.PDF and not usable_text_layer(extracted) and self._ocr_enabled():
            return ExtractedText(pages_read=extracted.pages_read, truncated=extracted.truncated)
        return extracted

    async def _save_pdf_pages(self, asset: Asset, extracted: ExtractedText) -> None:
        if self._pdf_pages is None or asset.kind != AssetKind.PDF:
            return
        for page in extracted.pages:
            if page.page_number is not None:
                await self._pdf_pages.save_page_text(asset_id=asset.id, page_number=page.page_number, text=page.text)

    async def _record_index(self, asset_id: str, extracted: ExtractedText) -> None:
        """Publish the text to other devices like OCR text (`asset_index` op); sync failures never fail the job."""
        if self._index_recorder is None:
            return
        try:
            await self._index_recorder.record_ocr(
                asset_id,
                ocr_text=extracted.text,
                pdf_pages=tuple(
                    (page.page_number, page.text) for page in extracted.pages if page.page_number is not None
                ),
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not queue the extracted text for sync: %s", exc.__class__.__name__)

    async def _refresh_embedding(self, asset: Asset) -> None:
        """Assets embedded before their text was known (existing libraries) get a fresh embedding job; a new
        upload already has one queued, which reads this text when it runs."""
        if self._jobs is None or self._active is None or not self._embeddings_enabled():
            return
        if await self._active.has_active(asset.id, types=_EMBEDDING_TYPES):
            return
        await self._jobs.enqueue(
            type=JobType.EMBEDDING,
            priority=int(JobPriority.EMBEDDING),
            payload={"asset_id": asset.id},
            asset_id=asset.id,
        )
