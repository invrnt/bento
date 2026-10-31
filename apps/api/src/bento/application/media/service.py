from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bento.domain.assets import Asset, AssetKind, ProcessingState
from bento.domain.errors import AssetNotFoundError
from bento.domain.manifest import ManifestEntityType, ManifestEventType
from bento.domain.storage import BlobKind, BlobRef
from bento.ports.blob_store import BlobStorePort
from bento.ports.manifest import ManifestJournalPort
from bento.ports.repositories import AssetRepositoryPort, ClockPort


class BlobRefCatalogPort(Protocol):
    async def add(self, blob_ref: BlobRef) -> None: ...

    async def latest_for_asset(self, asset_id: str, kind: BlobKind) -> BlobRef | None: ...


class ThumbnailCatalogPort(Protocol):
    async def add(self, *, asset_id: str, blob_ref: BlobRef, width: int | None, height: int | None) -> None: ...


class BlobPathResolverPort(Protocol):
    def resolve(self, blob_ref: BlobRef) -> Path: ...


class BlobSourceMaterializerPort(Protocol):
    def materialize(self, blob_ref: BlobRef) -> AbstractAsyncContextManager[Path]: ...


class RemoteUploadSchedulerPort(Protocol):
    async def schedule_many(self, blob_refs: tuple[BlobRef, ...]) -> int: ...


class MediaGeneratorPort(Protocol):
    async def generate(self, asset: Asset, source_path: Path) -> tuple["GeneratedMediaFile", ...]: ...

    async def cleanup(self, generated_files: tuple["GeneratedMediaFile", ...]) -> None: ...


@dataclass(frozen=True, slots=True)
class GeneratedMediaFile:
    path: Path
    kind: BlobKind
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    width: int | None = None
    height: int | None = None


class MediaProcessingService:
    def __init__(
        self,
        *,
        assets: AssetRepositoryPort,
        blob_refs: BlobRefCatalogPort,
        thumbnails: ThumbnailCatalogPort,
        blob_store: BlobStorePort,
        materializer: BlobSourceMaterializerPort,
        generator: MediaGeneratorPort,
        manifest: ManifestJournalPort,
        clock: ClockPort,
        remote_uploads: RemoteUploadSchedulerPort | None = None,
    ) -> None:
        self._remote_uploads = remote_uploads
        self._assets = assets
        self._blob_refs = blob_refs
        self._thumbnails = thumbnails
        self._blob_store = blob_store
        self._materializer = materializer
        self._generator = generator
        self._manifest = manifest
        self._clock = clock

    async def process_asset_media(self, asset_id: str) -> tuple[BlobRef, ...]:
        asset = await self._assets.get(asset_id)
        if asset is None:
            raise AssetNotFoundError(asset_id)
        original_ref = await self._blob_refs.latest_for_asset(asset.id, BlobKind.ORIGINAL)
        if original_ref is None:
            raise AssetNotFoundError(asset_id)
        if asset.kind not in {AssetKind.IMAGE, AssetKind.PDF, AssetKind.VIDEO}:
            return ()

        async with self._materializer.materialize(original_ref) as source_path:
            generated_files = await self._generator.generate(asset, source_path)
        stored_refs: list[BlobRef] = []
        thumbnail_ready = asset.processing_state != ProcessingState.THUMBNAIL_PENDING
        try:
            for generated in generated_files:
                metadata = asset.metadata.__class__(
                    original_filename=generated.filename,
                    mime_type=generated.mime_type,
                    size_bytes=generated.size_bytes,
                    sha256=generated.sha256,
                    taken_at=asset.metadata.taken_at,
                    exif=asset.metadata.exif,
                )
                blob_ref = await self._blob_store.store(
                    str(generated.path),
                    asset_id=asset.id,
                    kind=generated.kind,
                    metadata=metadata,
                )
                if generated.kind == BlobKind.THUMBNAIL:
                    await self._thumbnails.add(
                        asset_id=asset.id,
                        blob_ref=blob_ref,
                        width=generated.width,
                        height=generated.height,
                    )
                    await self._manifest.append(
                        type=ManifestEventType.THUMBNAIL_CREATED,
                        entity_type=ManifestEntityType.BLOB,
                        entity_id=blob_ref.id,
                        payload={"asset_id": asset.id, "width": generated.width, "height": generated.height},
                    )
                    if not thumbnail_ready:
                        asset = asset.transition_to(ProcessingState.THUMBNAIL_READY, self._clock.now())
                        await self._assets.save(asset)
                        thumbnail_ready = True
                elif generated.kind == BlobKind.PREVIEW:
                    await self._blob_refs.add(blob_ref)
                    await self._manifest.append(
                        type=ManifestEventType.BLOB_STORED,
                        entity_type=ManifestEntityType.BLOB,
                        entity_id=blob_ref.id,
                        payload={"asset_id": asset.id, "kind": blob_ref.kind.value},
                    )
                stored_refs.append(blob_ref)
        finally:
            await self._generator.cleanup(generated_files)

        if self._remote_uploads is not None and stored_refs:
            await self._remote_uploads.schedule_many(tuple(stored_refs))
        return tuple(stored_refs)
