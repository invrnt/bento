"""Local-first storage pipeline: background encrypted upload of blobs that only exist on this device.

Ingestion always stores the plaintext locally first. When the vault is ready, `remote_upload` jobs move
originals (then thumbnails and previews) to the remote store; the local file stays as a cache entry. Thumbnails and
previews that are waiting together go up in albums of up to 10 (`upload_many`), one job per blob all the same.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
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
from bento.domain.telegram import ALBUM_MAX_DOCUMENTS
from bento.ports.blob_store import RemoteBlobStorePort, RemoteBlobUpload
from bento.ports.jobs import JobQueuePort
from bento.ports.repositories import ClockPort

LOGGER = logging.getLogger("bento.storage_pipeline")

REMOTE_UPLOAD_PRIORITY_ORIGINAL = 2
REMOTE_UPLOAD_PRIORITY_DERIVED = 3
REMOTE_UPLOAD_MAX_ATTEMPTS = 8
UPLOADABLE_KINDS = frozenset({BlobKind.ORIGINAL, BlobKind.THUMBNAIL, BlobKind.PREVIEW})
SMALL_BLOB_KINDS = frozenset({BlobKind.THUMBNAIL, BlobKind.PREVIEW})
"""Derived blobs: small, so several pending ones share one album request."""

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

    async def claim_pending_uploads(
        self, *, kinds: frozenset[BlobKind], worker_id: str, exclude_job_id: str, limit: int, now: datetime
    ) -> tuple[Job, ...]:
        """Claim (lock as running) due, unlocked `remote_upload` jobs of these blob kinds, in queue order."""
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


@dataclass(frozen=True, slots=True)
class BatchUploadItem:
    """Outcome of one blob of `upload_many`: a result, or the error its job should fail with."""

    blob_id: str
    result: RemoteUploadResult | None = None
    error: Exception | None = None


@dataclass(frozen=True, slots=True)
class _PreparedUpload:
    blob_ref: BlobRef
    asset_id: str
    path: Path
    metadata: AssetMetadata
    store: RemoteBlobStorePort


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
        prepared = await self._prepare(blob_id)
        if isinstance(prepared, RemoteUploadResult):
            return prepared
        blob_ref = prepared.blob_ref
        try:
            remote_ref = await prepared.store.store(
                str(prepared.path), asset_id=prepared.asset_id, kind=blob_ref.kind, metadata=prepared.metadata
            )
        except TelegramFloodWaitError as exc:
            return await self._reschedule(blob_ref, exc)
        except (VaultLockedError, VaultNotFoundError):
            return RemoteUploadResult(UploadOutcome.NOT_READY)
        except TelegramAccountError as exc:
            if exc.code == "telegram_not_authorized":
                return RemoteUploadResult(UploadOutcome.NOT_READY)
            raise
        return await self._finish(prepared, remote_ref)

    async def claim_batch_companions(self, job: Job, *, worker_id: str) -> tuple[Job, ...]:
        """Other due thumbnail/preview uploads to send in the same album as `job` (claimed for this worker)."""
        if job.type != JobType.REMOTE_UPLOAD or job.payload.get("kind") not in {kind.value for kind in SMALL_BLOB_KINDS}:
            return ()
        if self._remote() is None:
            return ()
        return await self._catalog.claim_pending_uploads(
            kinds=SMALL_BLOB_KINDS,
            worker_id=worker_id,
            exclude_job_id=job.id,
            limit=ALBUM_MAX_DOCUMENTS - 1,
            now=self._clock.now(),
        )

    async def upload_many(self, blob_ids: Sequence[str]) -> tuple[BatchUploadItem, ...]:
        """Upload several small blobs with one album request per 10 (`store_many`); a single blob uses `store`.

        If the album request fails for any reason other than a flood wait or a locked vault, every blob is retried
        on its own so one bad file never fails the others. Never raises: errors are reported per blob.
        """
        unique = tuple(dict.fromkeys(blob_ids))
        results: dict[str, RemoteUploadResult] = {}
        errors: dict[str, Exception] = {}
        pending: list[_PreparedUpload] = []
        for blob_id in unique:
            try:
                prepared = await self._prepare(blob_id)
            except Exception as exc:  # noqa: BLE001 - reported per blob
                errors[blob_id] = exc
                continue
            if isinstance(prepared, RemoteUploadResult):
                results[blob_id] = prepared
            else:
                pending.append(prepared)
        if len(pending) > 1:
            pending = await self._upload_album(pending, results, errors)
        for prepared in pending:
            try:
                results[prepared.blob_ref.id] = await self.upload(prepared.blob_ref.id)
            except Exception as exc:  # noqa: BLE001 - reported per blob
                errors[prepared.blob_ref.id] = exc
        return tuple(BatchUploadItem(blob_id, results.get(blob_id), errors.get(blob_id)) for blob_id in unique)

    async def _upload_album(
        self, pending: list[_PreparedUpload], results: dict[str, RemoteUploadResult], errors: dict[str, Exception]
    ) -> list[_PreparedUpload]:
        """Returns the uploads still to be sent one by one."""
        store = pending[0].store
        uploads = [
            RemoteBlobUpload(source_ref=str(item.path), asset_id=item.asset_id, kind=item.blob_ref.kind, metadata=item.metadata)
            for item in pending
        ]
        try:
            remote_refs = await store.store_many(uploads)
        except TelegramFloodWaitError as exc:
            for item in pending:
                results[item.blob_ref.id] = await self._reschedule(item.blob_ref, exc)
            return []
        except (VaultLockedError, VaultNotFoundError):
            results.update((item.blob_ref.id, RemoteUploadResult(UploadOutcome.NOT_READY)) for item in pending)
            return []
        except Exception as exc:  # noqa: BLE001 - fall back to one upload per blob
            if isinstance(exc, TelegramAccountError) and exc.code == "telegram_not_authorized":
                results.update((item.blob_ref.id, RemoteUploadResult(UploadOutcome.NOT_READY)) for item in pending)
                return []
            code = exc.code if isinstance(exc, DomainError) else exc.__class__.__name__
            LOGGER.warning("Album upload of %s small blobs failed (%s); uploading them one by one", len(pending), code)
            return pending
        if len(remote_refs) != len(pending):
            LOGGER.warning("Album upload returned %s refs for %s blobs; uploading them one by one", len(remote_refs), len(pending))
            return pending
        for item, remote_ref in zip(pending, remote_refs, strict=True):
            try:
                results[item.blob_ref.id] = await self._finish(item, remote_ref)
            except Exception as exc:  # noqa: BLE001 - reported per blob
                errors[item.blob_ref.id] = exc
        return []

    async def _prepare(self, blob_id: str) -> _PreparedUpload | RemoteUploadResult:
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
        return _PreparedUpload(blob_ref=blob_ref, asset_id=blob_ref.asset_id, path=path, metadata=metadata, store=store)

    async def _reschedule(self, blob_ref: BlobRef, exc: TelegramFloodWaitError) -> RemoteUploadResult:
        await self._enqueue(blob_ref, flood_wait_seconds=exc.retry_after_seconds)
        return RemoteUploadResult(UploadOutcome.RESCHEDULED, retry_after_seconds=exc.retry_after_seconds)

    async def _finish(self, prepared: _PreparedUpload, remote_ref: BlobRef) -> RemoteUploadResult:
        blob_ref, path, store = prepared.blob_ref, prepared.path, prepared.store
        if remote_ref.backend != StorageBackend.TELEGRAM or not remote_ref.parts:
            raise ValidationFailedError("Remote store returned a blob without remote parts")
        remote_ref = replace(remote_ref, asset_id=blob_ref.asset_id, kind=blob_ref.kind)
        if not await self._catalog.replace_with_remote(blob_ref.id, remote_ref):
            if await self._catalog.get(remote_ref.id) is None:
                # Purged while uploading: do not leave unreachable parts behind.
                await _delete_orphan(store, remote_ref)
                return RemoteUploadResult(UploadOutcome.MISSING)

        dropped = False
        if blob_ref.kind == BlobKind.ORIGINAL and self._sources is not None:
            source = await self._sources.find_source(prepared.asset_id, blob_ref.size_bytes)
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
