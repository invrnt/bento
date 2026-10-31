from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from bento.domain.assets import (
    Asset,
    AssetKind,
    AssetMetadata,
    AssetMode,
    AssetOrigin,
    ProcessingState,
    infer_asset_kind,
    infer_asset_mode,
    supports_ocr,
)
from bento.domain.errors import DuplicateAssetError, FolderNotFoundError, UploadTooLargeError
from bento.domain.jobs import JobPriority, JobType
from bento.domain.manifest import ManifestEntityType, ManifestEventType
from bento.domain.storage import BlobKind, BlobRef
from bento.ports.blob_store import BlobStorePort
from bento.ports.jobs import JobQueuePort
from bento.ports.manifest import ManifestJournalPort
from bento.ports.repositories import AssetRepositoryPort, ClockPort, FolderRepositoryPort


@dataclass(frozen=True, slots=True)
class UploadAssetCommand:
    source_ref: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    folder_id: str | None = None
    mode: AssetMode | None = None
    taken_at: datetime | None = None
    exif: dict[str, object] | None = None
    allow_duplicate: bool = True
    ocr_enabled: bool = True
    embeddings_enabled: bool = True
    max_size_bytes: int | None = None
    folder_resolver: Callable[[AssetMode], Awaitable[str | None]] | None = None
    """Chooses the folder from the inferred mode (folder backup); called only for new, non-duplicate assets."""
    origin: AssetOrigin = AssetOrigin.DEVICE
    """Files obtained from Telegram are never sent to OCR or embeddings (Telegram API terms)."""


@dataclass(frozen=True, slots=True)
class UploadAssetResult:
    asset: Asset
    blob_ref: BlobRef | None
    duplicate: bool


class UploadAssetUseCase:
    def __init__(
        self,
        *,
        assets: AssetRepositoryPort,
        folders: FolderRepositoryPort,
        blob_store: BlobStorePort,
        jobs: JobQueuePort,
        manifest: ManifestJournalPort,
        clock: ClockPort,
    ) -> None:
        self._assets = assets
        self._folders = folders
        self._blob_store = blob_store
        self._jobs = jobs
        self._manifest = manifest
        self._clock = clock

    async def execute(self, command: UploadAssetCommand) -> UploadAssetResult:
        if command.max_size_bytes is not None and command.size_bytes > command.max_size_bytes:
            raise UploadTooLargeError(command.size_bytes, command.max_size_bytes)

        existing = await self._assets.get_by_sha256(command.sha256)
        if existing is not None and not existing.is_deleted:
            if command.allow_duplicate:
                return UploadAssetResult(asset=existing, blob_ref=None, duplicate=True)
            raise DuplicateAssetError(command.sha256)

        kind = infer_asset_kind(command.mime_type)
        mode = command.mode or infer_asset_mode(kind)
        folder_id = command.folder_id
        if command.folder_resolver is not None:
            folder_id = await command.folder_resolver(mode)
        if folder_id is not None and await self._folders.get(folder_id) is None:
            raise FolderNotFoundError(folder_id)

        now = self._clock.now()
        asset_id = await self._assets.next_id()
        metadata = AssetMetadata(
            original_filename=command.original_filename,
            mime_type=command.mime_type,
            size_bytes=command.size_bytes,
            sha256=command.sha256,
            taken_at=command.taken_at,
            exif=command.exif,
        )
        blob_ref = await self._blob_store.store(
            command.source_ref,
            asset_id=asset_id,
            kind=BlobKind.ORIGINAL,
            metadata=metadata,
        )
        initial_state = ProcessingState.THUMBNAIL_PENDING if _can_generate_media(kind) else ProcessingState.BLOB_STORED
        asset = Asset(
            id=asset_id,
            kind=kind,
            mode=mode,
            folder_id=folder_id,
            filename=command.original_filename,
            metadata=metadata,
            processing_state=ProcessingState.BLOB_STORED,
            favorite=False,
            created_at=now,
            updated_at=now,
            origin=command.origin,
        )
        if initial_state != asset.processing_state:
            asset = asset.transition_to(initial_state, now)
        index_text = command.ocr_enabled and asset.ai_indexing_allowed and supports_ocr(kind)
        embed = command.embeddings_enabled and asset.ai_indexing_allowed
        if not (_can_generate_media(kind) or index_text or embed):
            # Nothing else will touch it: it is as ready as it gets, like the copies peers receive.
            asset = asset.finish_processing(now)
        await self._assets.add(asset)
        await self._manifest.append(
            type=ManifestEventType.ASSET_CREATED,
            entity_type=ManifestEntityType.ASSET,
            entity_id=asset.id,
            payload={"filename": asset.filename, "kind": asset.kind.value},
        )
        await self._manifest.append(
            type=ManifestEventType.BLOB_STORED,
            entity_type=ManifestEntityType.BLOB,
            entity_id=blob_ref.id,
            payload={"asset_id": asset.id, "kind": blob_ref.kind.value},
        )
        if _can_generate_media(kind):
            await self._jobs.enqueue(
                type=JobType.THUMBNAIL,
                priority=int(JobPriority.THUMBNAIL),
                payload={"asset_id": asset.id},
                asset_id=asset.id,
            )
        if index_text:
            await self._jobs.enqueue(
                type=JobType.OCR,
                priority=int(JobPriority.OCR),
                payload={"asset_id": asset.id},
                asset_id=asset.id,
            )
        if embed:
            await self._jobs.enqueue(
                type=JobType.EMBEDDING,
                priority=int(JobPriority.EMBEDDING),
                payload={"asset_id": asset.id},
                asset_id=asset.id,
            )
        return UploadAssetResult(asset=asset, blob_ref=blob_ref, duplicate=False)


def _can_generate_media(kind: AssetKind) -> bool:
    return kind in {AssetKind.IMAGE, AssetKind.PDF, AssetKind.VIDEO}
