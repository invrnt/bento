"""Trash: deleted assets and folders stay restorable until purged (manually or after retention).

Purging deletes every remote part, the local copies, and the catalog rows (sync publishes `purge` ops).
Items whose remote parts cannot be deleted right now stay in the trash and are retried by a job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bento.application.storage_pipeline import LocalBlobFilesPort, RemoteStoreProvider
from bento.domain.errors import (
    DomainError,
    StorageUnavailableError,
    TelegramAccountError,
    TelegramFloodWaitError,
    VaultLockedError,
    VaultNotFoundError,
)
from bento.domain.jobs import JobType
from bento.domain.storage import BlobRef, StorageBackend
from bento.domain.trash import TrashItem
from bento.ports.jobs import JobQueuePort
from bento.ports.repositories import ClockPort
from bento.ports.search import SearchIndexPort

LOGGER = logging.getLogger("bento.trash")
TRASH_PURGE_PRIORITY = 7
TRASH_PURGE_MAX_ATTEMPTS = 10
_REMOTE_UNAVAILABLE = (
    StorageUnavailableError,
    TelegramFloodWaitError,
    TelegramAccountError,
    VaultLockedError,
    VaultNotFoundError,
)


@dataclass(frozen=True, slots=True)
class PurgeScope:
    top_level_ids: tuple[str, ...]
    asset_ids: tuple[str, ...]
    folder_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PurgeBlob:
    blob_ref: BlobRef
    remote_deleted: bool


@dataclass(frozen=True, slots=True)
class TrashEntry:
    item: TrashItem
    has_thumbnail: bool


@dataclass(frozen=True, slots=True)
class PurgeResult:
    purged: int
    deferred: tuple[str, ...] = ()


class TrashCatalogPort(Protocol):
    async def list(self, *, cursor: str | None = None, limit: int = 50) -> tuple[tuple[TrashItem, ...], str | None]: ...

    async def restore(self, ids: tuple[str, ...]) -> int: ...

    async def expired(self, *, now, limit: int = 100) -> tuple[TrashItem, ...]: ...  # type: ignore[no-untyped-def]

    async def purge(self, ids: tuple[str, ...]) -> int: ...

    async def trashed_ids(self, *, limit: int = 500) -> tuple[str, ...]: ...

    async def expand(self, ids: tuple[str, ...]) -> PurgeScope: ...

    async def purge_blobs(self, asset_ids: tuple[str, ...]) -> tuple[PurgeBlob, ...]: ...

    async def mark_remote_deleted(self, blob_ids: tuple[str, ...]) -> None: ...

    async def thumbnail_asset_ids(self, asset_ids: tuple[str, ...]) -> set[str]: ...


class TrashCachePort(Protocol):
    async def remove(self, blob_ids: tuple[str, ...]) -> int: ...

    async def release_local_copy(self, path: Path, *, exclude_blob_ids: tuple[str, ...] = ()) -> bool: ...


class TrashService:
    def __init__(
        self,
        *,
        catalog: TrashCatalogPort,
        cache: TrashCachePort,
        local_files: LocalBlobFilesPort,
        remote: RemoteStoreProvider,
        jobs: JobQueuePort,
        clock: ClockPort,
        search_indexes: tuple[SearchIndexPort, ...] = (),
    ) -> None:
        self._catalog = catalog
        self._cache = cache
        self._local_files = local_files
        self._remote = remote
        self._jobs = jobs
        self._clock = clock
        self._search_indexes = search_indexes

    async def list(self, *, cursor: str | None = None, limit: int = 50) -> tuple[tuple[TrashEntry, ...], str | None]:
        items, next_cursor = await self._catalog.list(cursor=cursor, limit=limit)
        with_thumbnails = await self._catalog.thumbnail_asset_ids(
            tuple(item.id for item in items if item.type.value == "asset")
        )
        return tuple(TrashEntry(item=item, has_thumbnail=item.id in with_thumbnails) for item in items), next_cursor

    async def restore(self, ids: tuple[str, ...]) -> int:
        return await self._catalog.restore(_unique(ids))

    async def purge(self, ids: tuple[str, ...], *, retry_later: bool = True) -> PurgeResult:
        purged = 0
        deferred: list[str] = []
        for item_id in _unique(ids):
            scope = await self._catalog.expand((item_id,))
            if not scope.top_level_ids:
                continue
            blobs = await self._catalog.purge_blobs(scope.asset_ids)
            if not await self._delete_remote(blobs):
                deferred.append(item_id)
                continue
            purged += await self._catalog.purge((item_id,))
            await self._cleanup_local(blobs)
            await self._unindex(scope.asset_ids)
        if deferred and retry_later:
            await self._jobs.enqueue(
                type=JobType.TRASH_PURGE,
                priority=TRASH_PURGE_PRIORITY,
                payload={"ids": deferred},
                max_attempts=TRASH_PURGE_MAX_ATTEMPTS,
            )
        return PurgeResult(purged=purged, deferred=tuple(deferred))

    async def empty(self) -> PurgeResult:
        purged = 0
        deferred: list[str] = []
        attempted: set[str] = set()
        while True:
            ids = tuple(item_id for item_id in await self._catalog.trashed_ids(limit=500) if item_id not in attempted)
            if not ids:
                break
            attempted.update(ids)
            result = await self.purge(ids, retry_later=False)
            purged += result.purged
            deferred.extend(result.deferred)
        if deferred:
            await self._jobs.enqueue(
                type=JobType.TRASH_PURGE,
                priority=TRASH_PURGE_PRIORITY,
                payload={"ids": deferred},
                max_attempts=TRASH_PURGE_MAX_ATTEMPTS,
            )
        return PurgeResult(purged=purged, deferred=tuple(deferred))

    async def purge_expired(self, *, limit: int = 100) -> PurgeResult:
        items = await self._catalog.expired(now=self._clock.now(), limit=limit)
        if not items:
            return PurgeResult(purged=0)
        return await self.purge(tuple(item.id for item in items), retry_later=False)

    async def _delete_remote(self, blobs: tuple[PurgeBlob, ...]) -> bool:
        pending = [
            blob.blob_ref
            for blob in blobs
            if blob.blob_ref.backend == StorageBackend.TELEGRAM and blob.blob_ref.parts and not blob.remote_deleted
        ]
        if not pending:
            return True
        store = self._remote()
        if store is None:
            return False
        for blob_ref in pending:
            try:
                await store.delete_ref(blob_ref)
            except _REMOTE_UNAVAILABLE as exc:
                LOGGER.info("Remote deletion of %s postponed: %s", blob_ref.id, exc.code)
                return False
            await self._catalog.mark_remote_deleted((blob_ref.id,))
        return True

    async def _cleanup_local(self, blobs: tuple[PurgeBlob, ...]) -> None:
        blob_ids = tuple(blob.blob_ref.id for blob in blobs)
        await self._cache.remove(blob_ids)
        for blob in blobs:
            if blob.blob_ref.backend != StorageBackend.LOCAL:
                continue
            try:
                path = self._local_files.resolve(blob.blob_ref)
            except DomainError:
                continue
            await self._cache.release_local_copy(path, exclude_blob_ids=blob_ids)

    async def _unindex(self, asset_ids: tuple[str, ...]) -> None:
        for index in self._search_indexes:
            for asset_id in asset_ids:
                try:
                    await index.remove_asset(asset_id)
                except Exception as exc:  # search indexes are rebuildable; never block a purge
                    LOGGER.warning("Could not remove %s from a search index: %s", asset_id, exc.__class__.__name__)


def _unique(ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in ids if item))
