from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Protocol

from bento.application.media.service import BlobPathResolverPort, BlobRefCatalogPort
from bento.application.sync.ports import AssetIndexRecorderPort
from bento.domain.assets import Asset, AssetKind, ProcessingState
from bento.domain.errors import AssetNotFoundError, ValidationFailedError
from bento.domain.indexing import EmbeddingRecord
from bento.domain.manifest import ManifestEntityType, ManifestEventType
from bento.domain.storage import BlobKind
from bento.ports.manifest import ManifestJournalPort
from bento.ports.repositories import AssetRepositoryPort, ClockPort

LOGGER = logging.getLogger("bento.indexing.embedding")

Vector = tuple[float, ...]


class EmbeddingVectorProviderPort(Protocol):
    async def is_enabled(self) -> bool: ...

    async def embed_text(self, asset_id: str, text: str) -> tuple[EmbeddingRecord, Vector]: ...

    async def embed_image(self, asset_id: str, image_path: Path) -> tuple[EmbeddingRecord, Vector]: ...


class EmbeddingVectorIndexPort(Protocol):
    async def index_embedding_vector(self, record: EmbeddingRecord, vector: Vector) -> None: ...


class EmbeddingTextCatalogPort(Protocol):
    async def text_for_asset(self, asset_id: str) -> str | None: ...


class EmbeddingIndexingService:
    def __init__(
        self,
        *,
        assets: AssetRepositoryPort,
        blob_refs: BlobRefCatalogPort,
        resolver: BlobPathResolverPort,
        provider: EmbeddingVectorProviderPort,
        index: EmbeddingVectorIndexPort,
        manifest: ManifestJournalPort,
        clock: ClockPort,
        text_catalog: EmbeddingTextCatalogPort | None = None,
        index_recorder: AssetIndexRecorderPort | None = None,
    ) -> None:
        self._assets = assets
        self._blob_refs = blob_refs
        self._resolver = resolver
        self._provider = provider
        self._index = index
        self._manifest = manifest
        self._clock = clock
        self._text_catalog = text_catalog
        self._index_recorder = index_recorder

    async def process_asset_embedding(self, asset_id: str) -> EmbeddingRecord | None:
        asset = await self._assets.get(asset_id)
        if asset is None:
            raise AssetNotFoundError(asset_id)

        pending_asset = await self._mark_embedding_pending(asset)
        try:
            if not await self._provider.is_enabled():
                await self._mark_indexed(pending_asset)
                return None

            original_ref = await self._blob_refs.latest_for_asset(asset.id, BlobKind.ORIGINAL)
            if original_ref is None:
                raise AssetNotFoundError(asset_id)

            source_path = self._resolver.resolve(original_ref)
            record, vector = await self._embed_asset(pending_asset, source_path)
            await self._index.index_embedding_vector(record, vector)
            await self._mark_indexed(pending_asset)
            await self._manifest.append(
                type=ManifestEventType.EMBEDDING_INDEXED,
                entity_type=ManifestEntityType.ASSET,
                entity_id=asset.id,
                payload={
                    "asset_id": asset.id,
                    "embedding_id": record.id,
                    "provider": record.provider,
                    "dimensions": record.dimensions,
                },
            )
        except Exception:
            await self._mark_partial_failure(pending_asset)
            raise
        await self._record_index(record, vector)
        return record

    async def _record_index(self, record: EmbeddingRecord, vector: Vector) -> None:
        """Publish the embedding to other devices (`asset_index` op); sync failures never fail indexing."""
        if self._index_recorder is None:
            return
        try:
            await self._index_recorder.record_embedding(
                record.asset_id, provider=record.provider, dimensions=record.dimensions, vector=vector
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not queue the embedding for sync: %s", exc.__class__.__name__)

    async def _embed_asset(self, asset: Asset, source_path: Path) -> tuple[EmbeddingRecord, Vector]:
        if asset.kind == AssetKind.IMAGE:
            return await self._provider.embed_image(asset.id, source_path)

        text = await self._text_for_asset(asset)
        if not text.strip():
            raise ValidationFailedError("No text is available for embedding", {"asset_id": asset.id})
        return await self._provider.embed_text(asset.id, text)

    async def _text_for_asset(self, asset: Asset) -> str:
        if self._text_catalog is not None:
            indexed_text = await self._text_catalog.text_for_asset(asset.id)
            if indexed_text:
                return indexed_text
        return _asset_metadata_text(asset)

    async def _mark_embedding_pending(self, asset: Asset) -> Asset:
        if asset.processing_state in {
            ProcessingState.EMBEDDING_PENDING,
            ProcessingState.EMBEDDING_READY,
            ProcessingState.INDEXED,
        }:
            return asset
        pending = asset.transition_to(ProcessingState.EMBEDDING_PENDING, self._clock.now())
        await self._assets.save(pending)
        return pending

    async def _mark_indexed(self, asset: Asset) -> None:
        if asset.processing_state == ProcessingState.INDEXED:
            return
        await self._assets.save(asset.transition_to(ProcessingState.INDEXED, self._clock.now()))

    async def _mark_partial_failure(self, asset: Asset) -> None:
        if asset.processing_state == ProcessingState.FAILED_PARTIAL:
            return
        await self._assets.save(asset.transition_to(ProcessingState.FAILED_PARTIAL, self._clock.now()))


def _asset_metadata_text(asset: Asset) -> str:
    parts = [asset.filename, asset.metadata.original_filename, asset.metadata.mime_type]
    if asset.metadata.exif:
        parts.append(json.dumps(dict(asset.metadata.exif), ensure_ascii=False, sort_keys=True))
    return " ".join(part for part in parts if part)
