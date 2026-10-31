from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from bento.application.drive import CreateFolderCommand, DriveUseCases, MoveFolderCommand
from bento.application.jobs import JobsUseCases
from bento.application.photos import AddAlbumAssetCommand, CreateAlbumCommand, PhotosUseCases
from bento.application.upload import UploadAssetCommand, UploadAssetUseCase
from bento.domain.assets import Asset, AssetKind, AssetMetadata, AssetMode, ProcessingState
from bento.domain.drive import DriveItem
from bento.domain.errors import DuplicateAssetError, InvalidFolderMoveError, JobNotRetryableError
from bento.domain.jobs import Job, JobStatus, JobType
from bento.domain.manifest import ManifestEntityType, ManifestEvent, ManifestEventType
from bento.domain.photos import Album, TimelineGroup
from bento.domain.security import EncryptionMetadata
from bento.domain.storage import BlobKind, BlobRef, StorageBackend


NOW = datetime(2026, 1, 1, tzinfo=UTC)
SHA = "b" * 64


def test_upload_orchestration_creates_asset_blob_manifest_and_jobs() -> None:
    async def scenario() -> None:
        assets = FakeAssets()
        folders = FakeFolders()
        blob_store = FakeBlobStore()
        jobs = FakeJobs()
        manifest = FakeManifest()
        use_case = UploadAssetUseCase(
            assets=assets,
            folders=folders,
            blob_store=blob_store,
            jobs=jobs,
            manifest=manifest,
            clock=FakeClock(),
        )

        result = await use_case.execute(
            UploadAssetCommand(
                source_ref="tmp-upload-1",
                original_filename="scan.pdf",
                mime_type="application/pdf",
                size_bytes=100,
                sha256=SHA,
            )
        )

        assert result.duplicate is False
        assert result.asset.kind == AssetKind.PDF
        assert result.asset.mode == AssetMode.DRIVE
        assert result.asset.processing_state == ProcessingState.THUMBNAIL_PENDING
        assert result.blob_ref is not None
        assert [job.type for job in jobs.items] == [JobType.THUMBNAIL, JobType.OCR, JobType.EMBEDDING]
        assert [event.type for event in manifest.events] == [
            ManifestEventType.ASSET_CREATED,
            ManifestEventType.BLOB_STORED,
        ]

    asyncio.run(scenario())


def test_upload_from_telegram_never_queues_ocr_or_embeddings() -> None:
    from bento.domain.assets import AssetOrigin

    async def scenario() -> None:
        jobs = FakeJobs()
        use_case = UploadAssetUseCase(
            assets=FakeAssets(),
            folders=FakeFolders(),
            blob_store=FakeBlobStore(),
            jobs=jobs,
            manifest=FakeManifest(),
            clock=FakeClock(),
        )

        result = await use_case.execute(
            UploadAssetCommand(
                source_ref="tmp-upload-1",
                original_filename="scan.pdf",
                mime_type="application/pdf",
                size_bytes=100,
                sha256=SHA,
                origin=AssetOrigin.TELEGRAM_IMPORT,
            )
        )
        note = await use_case.execute(
            UploadAssetCommand(
                source_ref="tmp-upload-2",
                original_filename="nota.txt",
                mime_type="text/plain",
                size_bytes=10,
                sha256="e" * 64,
                origin=AssetOrigin.TELEGRAM_INBOX,
            )
        )

        assert result.asset.origin == AssetOrigin.TELEGRAM_IMPORT
        assert [job.type for job in jobs.items] == [JobType.THUMBNAIL]
        # Nothing at all is left for the text file, so it is ready immediately.
        assert note.asset.processing_state == ProcessingState.INDEXED

    asyncio.run(scenario())


def test_upload_duplicate_returns_existing_by_default_and_can_conflict() -> None:
    async def scenario() -> None:
        assets = FakeAssets()
        existing = make_asset("asset-existing", sha256=SHA)
        assets.by_id[existing.id] = existing
        use_case = UploadAssetUseCase(
            assets=assets,
            folders=FakeFolders(),
            blob_store=FakeBlobStore(),
            jobs=FakeJobs(),
            manifest=FakeManifest(),
            clock=FakeClock(),
        )

        duplicate = await use_case.execute(
            UploadAssetCommand(
                source_ref="tmp-upload-1",
                original_filename="photo.jpg",
                mime_type="image/jpeg",
                size_bytes=100,
                sha256=SHA,
            )
        )

        assert duplicate.duplicate is True
        assert duplicate.asset == existing
        with pytest.raises(DuplicateAssetError):
            await use_case.execute(
                UploadAssetCommand(
                    source_ref="tmp-upload-1",
                    original_filename="photo.jpg",
                    mime_type="image/jpeg",
                    size_bytes=100,
                    sha256=SHA,
                    allow_duplicate=False,
                )
            )

    asyncio.run(scenario())


def test_drive_operations_create_and_prevent_invalid_folder_move() -> None:
    async def scenario() -> None:
        folders = FakeFolders()
        use_cases = DriveUseCases(assets=FakeAssets(), folders=folders, manifest=FakeManifest(), clock=FakeClock())
        root = await use_cases.create_folder(CreateFolderCommand(name="Docs"))
        child = await use_cases.create_folder(CreateFolderCommand(name="Child", parent_id=root.id))
        folders.descendants[root.id] = {child.id}

        with pytest.raises(InvalidFolderMoveError):
            await use_cases.move_folder(MoveFolderCommand(folder_id=root.id, parent_id=child.id))

    asyncio.run(scenario())


def test_photos_toggle_favorite_and_album_membership() -> None:
    async def scenario() -> None:
        assets = FakeAssets()
        asset = make_asset("asset-photo", kind=AssetKind.IMAGE, mode=AssetMode.PHOTOS)
        assets.by_id[asset.id] = asset
        photos = PhotosUseCases(assets=assets, albums=FakeAlbums(), clock=FakeClock())

        favorite = await photos.toggle_favorite(asset.id)
        album = await photos.create_album(CreateAlbumCommand(title="Vacaciones"))
        album = await photos.add_asset_to_album(AddAlbumAssetCommand(album_id=album.id, asset_id=asset.id))
        album = await photos.remove_asset_from_album(AddAlbumAssetCommand(album_id=album.id, asset_id=asset.id))

        assert favorite.favorite is True
        assert album.asset_ids == frozenset()

    asyncio.run(scenario())


def test_jobs_retry_use_case_requeues_only_retryable_failed_jobs() -> None:
    async def scenario() -> None:
        failed = Job(
            id="job-1",
            type=JobType.OCR,
            status=JobStatus.FAILED,
            priority=3,
            payload={},
            attempts=1,
            max_attempts=3,
            created_at=NOW,
            updated_at=NOW,
        )
        jobs = FakeJobs(items=[failed])
        use_cases = JobsUseCases(jobs=jobs, clock=FakeClock())

        retried = await use_cases.retry_failed_job("job-1")

        assert retried.status == JobStatus.QUEUED
        assert jobs.items[0].status == JobStatus.QUEUED
        with pytest.raises(JobNotRetryableError):
            await use_cases.retry_failed_job("job-1")

    asyncio.run(scenario())


@dataclass
class FakeClock:
    def now(self) -> datetime:
        return NOW


@dataclass
class FakeAssets:
    by_id: dict[str, Asset] = field(default_factory=dict)

    async def next_id(self) -> str:
        return f"asset-{len(self.by_id) + 1}"

    async def get(self, asset_id: str) -> Asset | None:
        return self.by_id.get(asset_id)

    async def get_by_sha256(self, sha256: str) -> Asset | None:
        return next((asset for asset in self.by_id.values() if asset.metadata.sha256 == sha256), None)

    async def add(self, asset: Asset) -> None:
        self.by_id[asset.id] = asset

    async def save(self, asset: Asset) -> None:
        self.by_id[asset.id] = asset

    async def list_photos_timeline(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[tuple[TimelineGroup, ...], str | None]:
        return (), None


@dataclass
class FakeFolders:
    by_id: dict[str, Any] = field(default_factory=dict)
    descendants: dict[str, set[str]] = field(default_factory=dict)

    async def next_id(self) -> str:
        return f"folder-{len(self.by_id) + 1}"

    async def get(self, folder_id: str):
        return self.by_id.get(folder_id)

    async def add(self, folder: Any) -> None:
        self.by_id[folder.id] = folder

    async def save(self, folder: Any) -> None:
        self.by_id[folder.id] = folder

    async def descendant_ids(self, folder_id: str) -> set[str]:
        return self.descendants.get(folder_id, set())

    async def list_items(
        self,
        *,
        folder_id: str | None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[tuple[DriveItem, ...], str | None]:
        return (), None


@dataclass
class FakeAlbums:
    by_id: dict[str, Album] = field(default_factory=dict)

    async def next_id(self) -> str:
        return f"album-{len(self.by_id) + 1}"

    async def get(self, album_id: str) -> Album | None:
        return self.by_id.get(album_id)

    async def add(self, album: Album) -> None:
        self.by_id[album.id] = album

    async def save(self, album: Album) -> None:
        self.by_id[album.id] = album

    async def list(self, *, cursor: str | None = None, limit: int = 50) -> tuple[tuple[Album, ...], str | None]:
        return tuple(self.by_id.values()), None


@dataclass
class FakeBlobStore:
    async def store(
        self,
        source_ref: str,
        *,
        asset_id: str | None,
        kind: BlobKind,
        metadata: AssetMetadata,
        encryption: EncryptionMetadata | None = None,
    ) -> BlobRef:
        return BlobRef(
            id="blob-1",
            asset_id=asset_id,
            backend=StorageBackend.LOCAL,
            kind=kind,
            object_key=source_ref,
            size_bytes=metadata.size_bytes,
            sha256=metadata.sha256,
        )

    async def get(self, blob_id: str) -> BlobRef | None:
        return None

    async def delete(self, blob_id: str) -> None:
        return None


@dataclass
class FakeJobs:
    items: list[Job] = field(default_factory=list)

    async def enqueue(
        self,
        *,
        type: JobType,
        priority: int,
        payload: dict[str, object],
        asset_id: str | None = None,
        max_attempts: int = 3,
    ) -> Job:
        job = Job(
            id=f"job-{len(self.items) + 1}",
            type=type,
            status=JobStatus.QUEUED,
            priority=priority,
            payload=payload,
            attempts=0,
            max_attempts=max_attempts,
            asset_id=asset_id,
            created_at=NOW,
            updated_at=NOW,
        )
        self.items.append(job)
        return job

    async def get(self, job_id: str) -> Job | None:
        return next((job for job in self.items if job.id == job_id), None)

    async def save(self, job: Job) -> None:
        self.items = [job if item.id == job.id else item for item in self.items]

    async def list(self, *, cursor: str | None = None, limit: int = 50) -> tuple[tuple[Job, ...], str | None]:
        return tuple(self.items), None

    async def claim_next(self, worker_id: str) -> Job | None:
        return None


@dataclass
class FakeManifest:
    events: list[ManifestEvent] = field(default_factory=list)

    async def next_id(self) -> str:
        return f"event-{len(self.events) + 1}"

    async def append(
        self,
        *,
        type: ManifestEventType,
        entity_type: ManifestEntityType,
        entity_id: str,
        payload: dict[str, object],
    ) -> ManifestEvent:
        event = ManifestEvent(
            id=await self.next_id(),
            type=type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            created_at=NOW,
        )
        self.events.append(event)
        return event

    async def export_jsonl(self) -> None:
        return None


def make_asset(
    asset_id: str,
    *,
    sha256: str = "c" * 64,
    kind: AssetKind = AssetKind.IMAGE,
    mode: AssetMode = AssetMode.PHOTOS,
) -> Asset:
    return Asset(
        id=asset_id,
        kind=kind,
        mode=mode,
        folder_id=None,
        filename="photo.jpg",
        metadata=AssetMetadata(
            original_filename="photo.jpg",
            mime_type="image/jpeg",
            size_bytes=100,
            sha256=sha256,
        ),
        processing_state=ProcessingState.THUMBNAIL_PENDING,
        favorite=False,
        created_at=NOW,
        updated_at=NOW,
    )
