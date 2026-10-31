from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from bento.application.media.service import BlobPathResolverPort, BlobRefCatalogPort
from bento.application.sync.ports import AssetIndexRecorderPort
from bento.domain.assets import Asset, AssetKind, ProcessingState
from bento.domain.errors import AssetNotFoundError, ValidationFailedError
from bento.domain.indexing import OCRBlock
from bento.domain.manifest import ManifestEntityType, ManifestEventType
from bento.domain.storage import BlobKind
from bento.ports.manifest import ManifestJournalPort
from bento.ports.providers import OCRProviderPort
from bento.ports.repositories import AssetRepositoryPort, ClockPort
from bento.ports.search import SearchIndexPort

LOGGER = logging.getLogger("bento.indexing.ocr")

@dataclass(frozen=True, slots=True)
class PDFPageRender:
    page_number: int
    image_path: Path


class PDFPageRendererPort(Protocol):
    async def render_pages(self, *, asset_id: str, source_path: Path) -> tuple[PDFPageRender, ...]: ...


class PDFPageTextCatalogPort(Protocol):
    async def save_page_text(self, *, asset_id: str, page_number: int, text: str) -> None: ...


class OCRIndexingService:
    def __init__(
        self,
        *,
        assets: AssetRepositoryPort,
        blob_refs: BlobRefCatalogPort,
        resolver: BlobPathResolverPort,
        provider: OCRProviderPort,
        index: SearchIndexPort,
        manifest: ManifestJournalPort,
        clock: ClockPort,
        pdf_renderer: PDFPageRendererPort | None = None,
        pdf_pages: PDFPageTextCatalogPort | None = None,
        index_recorder: AssetIndexRecorderPort | None = None,
    ) -> None:
        self._assets = assets
        self._blob_refs = blob_refs
        self._resolver = resolver
        self._provider = provider
        self._index = index
        self._manifest = manifest
        self._clock = clock
        self._pdf_renderer = pdf_renderer
        self._pdf_pages = pdf_pages
        self._index_recorder = index_recorder

    async def process_asset_ocr(self, asset_id: str) -> tuple[OCRBlock, ...]:
        asset = await self._assets.get(asset_id)
        if asset is None:
            raise AssetNotFoundError(asset_id)
        if not asset.ai_indexing_allowed:
            LOGGER.info("Skipped OCR of asset %s (origin %s): only this device's own files are indexed", asset.id, asset.origin)
            return ()
        if asset.kind not in {AssetKind.IMAGE, AssetKind.PDF}:
            return ()

        pending_asset = await self._mark_ocr_pending(asset)
        try:
            if not await self._provider.is_enabled():
                await self._mark_ocr_ready(pending_asset)
                return ()

            original_ref = await self._blob_refs.latest_for_asset(asset.id, BlobKind.ORIGINAL)
            if original_ref is None:
                raise AssetNotFoundError(asset_id)

            source_path = self._resolver.resolve(original_ref)
            blocks = await self._extract_blocks(pending_asset, source_path)
            for block in blocks:
                await self._index.index_ocr(block)
            await self._mark_ocr_ready(pending_asset)
            await self._manifest.append(
                type=ManifestEventType.OCR_INDEXED,
                entity_type=ManifestEntityType.ASSET,
                entity_id=asset.id,
                payload={
                    "asset_id": asset.id,
                    "block_count": len(blocks),
                    "page_count": len({block.page_number for block in blocks if block.page_number is not None}),
                },
            )
        except Exception:
            await self._mark_partial_failure(pending_asset)
            raise
        await self._record_index(asset.id, blocks)
        return blocks

    async def _record_index(self, asset_id: str, blocks: tuple[OCRBlock, ...]) -> None:
        """Publish the OCR result to other devices (`asset_index` op); sync failures never fail indexing."""
        if self._index_recorder is None:
            return
        pages: dict[int, list[str]] = {}
        for block in blocks:
            if block.page_number is not None and block.text.strip():
                pages.setdefault(block.page_number, []).append(block.text)
        try:
            await self._index_recorder.record_ocr(
                asset_id,
                ocr_text="\n".join(block.text for block in blocks if block.text.strip()),
                pdf_pages=tuple((page, "\n".join(texts)) for page, texts in sorted(pages.items())),
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not queue the OCR result for sync: %s", exc.__class__.__name__)

    async def _extract_blocks(self, asset: Asset, source_path: Path) -> tuple[OCRBlock, ...]:
        if asset.kind != AssetKind.PDF:
            return await self._provider.extract_text(asset.id, str(source_path))
        if self._pdf_renderer is None:
            raise ValidationFailedError("PDF OCR renderer is not configured")

        blocks: list[OCRBlock] = []
        for page in await self._pdf_renderer.render_pages(asset_id=asset.id, source_path=source_path):
            page_blocks = await self._provider.extract_text(asset.id, str(page.image_path))
            normalized_blocks = tuple(
                replace(block, id=_page_block_id(block, page.page_number, index), page_number=page.page_number)
                for index, block in enumerate(page_blocks)
            )
            blocks.extend(normalized_blocks)
            if self._pdf_pages is not None:
                await self._pdf_pages.save_page_text(
                    asset_id=asset.id,
                    page_number=page.page_number,
                    text="\n".join(block.text for block in normalized_blocks if block.text.strip()),
                )
        return tuple(blocks)

    async def _mark_ocr_pending(self, asset: Asset) -> Asset:
        if asset.processing_state == ProcessingState.OCR_PENDING:
            return asset
        if asset.processing_state == ProcessingState.OCR_READY:
            return asset
        if asset.processing_state == ProcessingState.INDEXED:
            return asset
        pending = asset.transition_to(ProcessingState.OCR_PENDING, self._clock.now())
        await self._assets.save(pending)
        return pending

    async def _mark_ocr_ready(self, asset: Asset) -> None:
        if asset.processing_state == ProcessingState.INDEXED:
            return
        ready = asset.transition_to(ProcessingState.OCR_READY, self._clock.now())
        await self._assets.save(ready)

    async def _mark_partial_failure(self, asset: Asset) -> None:
        if asset.processing_state == ProcessingState.FAILED_PARTIAL:
            return
        await self._assets.save(asset.transition_to(ProcessingState.FAILED_PARTIAL, self._clock.now()))


def _page_block_id(block: OCRBlock, page_number: int, index: int) -> str:
    suffix = f"_p{page_number}_{index}"
    if block.id.endswith(suffix):
        return block.id
    return f"{block.id}{suffix}"
