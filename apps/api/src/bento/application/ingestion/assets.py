from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bento.application.ingestion.metadata import ExtractedUploadMetadata
from bento.application.upload import UploadAssetCommand, UploadAssetResult, UploadAssetUseCase
from bento.domain.assets import Asset, AssetMode, AssetOrigin
from bento.domain.errors import AssetNotFoundError, UnsupportedMediaTypeError
from bento.domain.manifest import ManifestEntityType, ManifestEventType
from bento.domain.storage import BlobKind, BlobRef
from bento.ports.manifest import ManifestJournalPort
from bento.ports.repositories import AssetRepositoryPort, ClockPort


class BlobRefCatalogPort(Protocol):
    async def add(self, blob_ref: BlobRef) -> None: ...

    async def latest_for_asset(self, asset_id: str, kind: BlobKind) -> BlobRef | None: ...


class RemoteUploadSchedulerPort(Protocol):
    async def schedule(self, blob_ref: BlobRef) -> bool:
        """Enqueue the background encrypted upload of a locally stored blob when the vault is ready."""
        ...


class UploadMetadataExtractorPort(Protocol):
    async def extract(
        self,
        source_path: Path,
        *,
        original_filename: str,
        declared_mime_type: str | None,
    ) -> ExtractedUploadMetadata: ...


@dataclass(frozen=True, slots=True)
class UploadedAssetFile:
    source_path: Path
    original_filename: str
    declared_mime_type: str | None = None
    folder_id: str | None = None
    mode: AssetMode | None = None
    allow_duplicate: bool = True
    folder_resolver: Callable[[AssetMode], Awaitable[str | None]] | None = None
    origin: AssetOrigin = AssetOrigin.DEVICE


@dataclass(frozen=True, slots=True)
class AssetFile:
    asset: Asset
    blob_ref: BlobRef


class AssetIngestionService:
    def __init__(
        self,
        *,
        upload: UploadAssetUseCase,
        blob_refs: BlobRefCatalogPort,
        metadata_extractor: UploadMetadataExtractorPort,
        remote_uploads: RemoteUploadSchedulerPort | None = None,
    ) -> None:
        self._upload = upload
        self._blob_refs = blob_refs
        self._metadata_extractor = metadata_extractor
        self._remote_uploads = remote_uploads

    async def upload_file(self, file: UploadedAssetFile) -> UploadAssetResult:
        metadata = await self._metadata_extractor.extract(
            file.source_path,
            original_filename=file.original_filename,
            declared_mime_type=file.declared_mime_type,
        )
        result = await self._upload.execute(
            UploadAssetCommand(
                source_ref=str(file.source_path),
                original_filename=metadata.filename,
                mime_type=metadata.mime_type,
                size_bytes=metadata.size_bytes,
                sha256=metadata.sha256,
                folder_id=file.folder_id,
                mode=file.mode,
                taken_at=metadata.taken_at,
                exif=metadata.exif,
                allow_duplicate=file.allow_duplicate,
                ocr_enabled=False,
                embeddings_enabled=False,
                folder_resolver=file.folder_resolver,
                origin=file.origin,
            )
        )
        if result.blob_ref is not None:
            await self._blob_refs.add(result.blob_ref)
            if self._remote_uploads is not None:
                await self._remote_uploads.schedule(result.blob_ref)
        return result


class AssetFileQueryService:
    def __init__(
        self,
        *,
        assets: AssetRepositoryPort,
        blob_refs: BlobRefCatalogPort,
        manifest: ManifestJournalPort,
        clock: ClockPort,
    ) -> None:
        self._assets = assets
        self._blob_refs = blob_refs
        self._manifest = manifest
        self._clock = clock

    async def get_asset(self, asset_id: str) -> Asset:
        asset = await self._assets.get(asset_id)
        if asset is None:
            raise AssetNotFoundError(asset_id)
        return asset

    async def delete_asset(self, asset_id: str) -> Asset:
        asset = await self.get_asset(asset_id)
        updated = asset.mark_deleted(self._clock.now())
        await self._assets.save(updated)
        await self._manifest.append(
            type=ManifestEventType.ASSET_DELETED,
            entity_type=ManifestEntityType.ASSET,
            entity_id=updated.id,
            payload={},
        )
        return updated

    async def original_file(self, asset_id: str) -> AssetFile:
        asset = await self.get_asset(asset_id)
        blob_ref = await self._require_blob(asset.id, BlobKind.ORIGINAL)
        return AssetFile(asset=asset, blob_ref=blob_ref)

    async def thumbnail_file(self, asset_id: str) -> AssetFile:
        asset = await self.get_asset(asset_id)
        blob_ref = await self._require_blob(asset.id, BlobKind.THUMBNAIL)
        return AssetFile(asset=asset, blob_ref=blob_ref)

    async def preview_file(self, asset_id: str) -> AssetFile:
        asset = await self.get_asset(asset_id)
        if asset.kind.value not in {"image", "pdf", "video"}:
            raise UnsupportedMediaTypeError(asset.metadata.mime_type)
        blob_ref = await self._require_blob(asset.id, BlobKind.PREVIEW)
        return AssetFile(asset=asset, blob_ref=blob_ref)

    async def _require_blob(self, asset_id: str, kind: BlobKind) -> BlobRef:
        blob_ref = await self._blob_refs.latest_for_asset(asset_id, kind)
        if blob_ref is None:
            raise AssetNotFoundError(asset_id)
        return blob_ref
