"""Local-first storage pipeline: background encrypted upload of blobs that only exist on this device.

Ingestion always stores the plaintext locally first. When the vault is ready, `remote_upload` jobs move
originals (then thumbnails and previews) to the remote store; the local file stays as a cache entry.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from bento.domain.assets import AssetMetadata
from bento.domain.errors import (
    DomainError,
    TelegramAccountError,
    TelegramFloodWaitError,
    ValidationFailedError,
    VaultLockedError,
    VaultNotFoundError,
)
from bento.domain.jobs import Job, JobStatus, JobType
from bento.domain.storage import BlobKind, BlobRef, StorageBackend
from bento.ports.blob_store import RemoteBlobStorePort
from bento.ports.jobs import JobQueuePort
from bento.ports.repositories import ClockPort

LOGGER = logging.getLogger("bento.storage_pipeline")

REMOTE_UPLOAD_PRIORITY_ORIGINAL = 2
REMOTE_UPLOAD_PRIORITY_DERIVED = 3
REMOTE_UPLOAD_MAX_ATTEMPTS = 8
UPLOADABLE_KINDS = frozenset({BlobKind.ORIGINAL, BlobKind.THUMBNAIL, BlobKind.PREVIEW})

RemoteStoreProvider = Callable[[], RemoteBlobStorePort | None]
"""Returns the remote store when the vault is ready on this device, otherwise None. Never raises."""


class PipelineCatalogPort(Protocol):
    async def get(self, blob_id: str) -> BlobRef | None: ...

    async def asset_metadata(self, asset_id: str) -> tuple[AssetMetadata, bool] | None:
        """(metadata, is_deleted) of an asset, including trashed ones."""
        ...

    async def replace_with_remote(self, local_blob_id: str, remote: BlobRef) -> bool:
        """Atomically swap a local ref for its remote ref (thumbnails repointed). False when the local ref is gone."""
        ...

    async def has_active_upload(self, blob_id: str) -> bool: ...

    async def unscheduled_local_blobs(self, *, limit: int) -> tuple[BlobRef, ...]:
        """Local blobs of non-trashed assets without a queued, running, retrying, or failed upload job; originals first."""
        ...


class LocalBlobFilesPort(Protocol):
    def resolve(self, blob_ref: BlobRef) -> Path: ...


class PipelineCachePort(Protocol):
    async def register(self, blob_id: str, path: Path, size_bytes: int) -> None: ...

    async def release_local_copy(self, path: Path, *, exclude_blob_ids: tuple[str, ...] = ()) -> bool:
        """Delete a local plaintext copy unless another local ref or cache entry still uses it."""
        ...


class SourceFilesPort(Protocol):
    async def find_source(self, asset_id: str, size_bytes: int) -> Path | None:
        """The user's backed-up source file when its size and mtime still match the backup record."""
        ...


class UploadOutcome(StrEnum):
    UPLOADED = "uploaded"
    ALREADY_REMOTE = "already_remote"
    MISSING = "missing"
    NOT_READY = "not_ready"
    DEFERRED = "deferred"
    RESCHEDULED = "rescheduled"


@dataclass(frozen=True, slots=True)
class RemoteUploadResult:
    outcome: UploadOutcome
    remote_ref: BlobRef | None = None
    retry_after_seconds: int | None = None
    dropped_local_copy: bool = False


class StoragePipelineService:
    def __init__(
        self,
        *,
        catalog: PipelineCatalogPort,
        jobs: JobQueuePort,
        remote: RemoteStoreProvider,
        local_files: LocalBlobFilesPort,
        cache: PipelineCachePort,
        clock: ClockPort,
        sources: SourceFilesPort | None = None,
        jitter_seconds: Callable[[], float] = lambda: random.uniform(1.0, 5.0),
    ) -> None:
        self._catalog = catalog
        self._jobs = jobs
        self._remote = remote
        self._local_files = local_files
        self._cache = cache
        self._clock = clock
        self._sources = sources
        self._jitter = jitter_seconds

    def remote_available(self) -> bool:
        return self._remote() is not None

    async def schedule(self, blob_ref: BlobRef) -> bool:
        """Enqueue `remote_upload` for a freshly stored local blob when the vault is ready."""
        if not _uploadable(blob_ref) or self._remote() is None:
            return False
        if await self._catalog.has_active_upload(blob_ref.id):
            return False
        await self._enqueue(blob_ref)
        return True

    async def schedule_many(self, blob_refs: tuple[BlobRef, ...]) -> int:
        scheduled = 0
        for blob_ref in sorted(blob_refs, key=lambda ref: ref.kind != BlobKind.ORIGINAL):
            scheduled += int(await self.schedule(blob_ref))
        return scheduled

    async def backfill(self, *, limit: int = 500) -> int:
        """Enqueue uploads for every local-only blob (vault became ready, skipped or lost jobs)."""
        if self._remote() is None:
            return 0
        refs = await self._catalog.unscheduled_local_blobs(limit=limit)
        for blob_ref in refs:
            await self._enqueue(blob_ref)
        return len(refs)

    async def upload(self, blob_id: str) -> RemoteUploadResult:
        blob_ref = await self._catalog.get(blob_id)
        if blob_ref is None:
            return RemoteUploadResult(UploadOutcome.MISSING)
        if blob_ref.backend != StorageBackend.LOCAL:
            return RemoteUploadResult(UploadOutcome.ALREADY_REMOTE)
        if blob_ref.asset_id is None:
            return RemoteUploadResult(UploadOutcome.MISSING)
        asset = await self._catalog.asset_metadata(blob_ref.asset_id)
        if asset is None:
            return RemoteUploadResult(UploadOutcome.MISSING)
        if asset[1]:
            # Trashed before upload: restoring it lets the backfill pick it up again.
            return RemoteUploadResult(UploadOutcome.DEFERRED)
        store = self._remote()
        if store is None:
            return RemoteUploadResult(UploadOutcome.NOT_READY)

        path = self._local_files.resolve(blob_ref)
        metadata = await _upload_metadata(blob_ref, asset[0], path)
        try:
            remote_ref = await store.store(str(path), asset_id=blob_ref.asset_id, kind=blob_ref.kind, metadata=metadata)
        except TelegramFloodWaitError as exc:
            await self._enqueue(blob_ref, flood_wait_seconds=exc.retry_after_seconds)
            return RemoteUploadResult(UploadOutcome.RESCHEDULED, retry_after_seconds=exc.retry_after_seconds)
        except (VaultLockedError, VaultNotFoundError):
            return RemoteUploadResult(UploadOutcome.NOT_READY)
        except TelegramAccountError as exc:
            if exc.code == "telegram_not_authorized":
                return RemoteUploadResult(UploadOutcome.NOT_READY)
            raise

        if remote_ref.backend != StorageBackend.TELEGRAM or not remote_ref.parts:
            raise ValidationFailedError("Remote store returned a blob without remote parts")
        remote_ref = replace(remote_ref, asset_id=blob_ref.asset_id, kind=blob_ref.kind)
        if not await self._catalog.replace_with_remote(blob_ref.id, remote_ref):
            await _delete_orphan(store, remote_ref)
            return RemoteUploadResult(UploadOutcome.MISSING)

        dropped = False
        if blob_ref.kind == BlobKind.ORIGINAL and self._sources is not None:
            source = await self._sources.find_source(blob_ref.asset_id, blob_ref.size_bytes)
            if source is not None:
                dropped = await self._cache.release_local_copy(path, exclude_blob_ids=(blob_ref.id, remote_ref.id))
        if not dropped:
            await self._cache.register(remote_ref.id, path, blob_ref.size_bytes)
        return RemoteUploadResult(UploadOutcome.UPLOADED, remote_ref=remote_ref, dropped_local_copy=dropped)

    async def park_failure(self, blob_id: str, error: str) -> Job | None:
        """Record an upload that exhausted its retries as a FAILED job the user can retry (`POST /jobs/{id}/retry`)."""
        blob_ref = await self._catalog.get(blob_id)
        if blob_ref is None or blob_ref.backend != StorageBackend.LOCAL:
            return None
        job = await self._enqueue(blob_ref)
        parked = replace(job, status=JobStatus.FAILED, attempts=0, error=error[:500], updated_at=self._clock.now())
        await self._jobs.save(parked)
        return parked

    async def _enqueue(self, blob_ref: BlobRef, *, flood_wait_seconds: int | None = None) -> Job:
        payload: dict[str, object] = {
            "blob_id": blob_ref.id,
            "kind": blob_ref.kind.value,
            "size_bytes": blob_ref.size_bytes,
        }
        run_after = None
        if flood_wait_seconds is not None:
            run_after = self._clock.now() + timedelta(seconds=max(flood_wait_seconds, 0) + self._jitter())
            payload["flood_wait_until"] = run_after.isoformat()
            payload["retry_after_seconds"] = flood_wait_seconds
        job = await self._jobs.enqueue(
            type=JobType.REMOTE_UPLOAD,
            priority=REMOTE_UPLOAD_PRIORITY_ORIGINAL if blob_ref.kind == BlobKind.ORIGINAL else REMOTE_UPLOAD_PRIORITY_DERIVED,
            payload=payload,
            asset_id=blob_ref.asset_id,
            max_attempts=REMOTE_UPLOAD_MAX_ATTEMPTS,
        )
        if run_after is not None:
            job = replace(job, run_after=run_after)
            await self._jobs.save(job)
        return job


def _uploadable(blob_ref: BlobRef) -> bool:
    return blob_ref.backend == StorageBackend.LOCAL and blob_ref.kind in UPLOADABLE_KINDS and blob_ref.asset_id is not None


async def _upload_metadata(blob_ref: BlobRef, asset: AssetMetadata, path: Path) -> AssetMetadata:
    sha256 = blob_ref.sha256 or await asyncio.to_thread(_sha256_file, path)
    if blob_ref.kind == BlobKind.ORIGINAL:
        return replace(asset, size_bytes=blob_ref.size_bytes, sha256=sha256)
    return AssetMetadata(
        original_filename=f"{blob_ref.kind.value}.jpg",
        mime_type="image/jpeg",
        size_bytes=blob_ref.size_bytes,
        sha256=sha256,
    )


async def _delete_orphan(store: RemoteBlobStorePort, remote_ref: BlobRef) -> None:
    try:
        await store.delete_ref(remote_ref)
    except DomainError as exc:
        LOGGER.warning("Could not delete orphaned remote blob %s: %s", remote_ref.id, exc.code)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
