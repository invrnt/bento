from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from bento.domain.errors import DomainError, StorageUnavailableError
from bento.domain.storage import StorageBackend
from bento.ports.blob_store import BlobStorePort
from bento.ports.storage_maintenance import CacheReclaimResult, CacheUsage, EphemeralCachePort, StorageInventoryPort


@dataclass(frozen=True, slots=True)
class StorageMaintenanceStatus:
    connection_state: str
    can_reclaim: bool
    fully_remote: bool
    reclaimable_bytes: int
    reclaimable_files: int
    local_blob_count: int
    telegram_blob_count: int


@dataclass(frozen=True, slots=True)
class StorageReclaimResult:
    freed_bytes: int
    deleted_files: int
    retained_bytes: int
    retained_files: int
    skipped_recent_files: int


class BlobCacheMaintenancePort(Protocol):
    """Local copies of uploaded originals (`cache_entries`), evictable because they can be downloaded again."""

    async def evictable_usage(self) -> CacheUsage: ...

    async def evict(self, *, max_bytes: int | None) -> CacheReclaimResult: ...


class StorageMaintenanceService:
    """"Liberar espacio": drops reproducible temp files and cached copies of originals already in the vault.

    Blobs that exist only on this device are never touched, so reclaiming no longer requires every blob to be
    remote; it requires a reachable remote store so evicted originals can be fetched again.
    """

    def __init__(
        self,
        *,
        storage_backend: StorageBackend,
        remote_store: Callable[[], BlobStorePort | None],
        inventory: StorageInventoryPort,
        cache: EphemeralCachePort,
        blob_cache: BlobCacheMaintenancePort | None = None,
    ) -> None:
        self._storage_backend = storage_backend
        self._remote_store = remote_store
        self._inventory = inventory
        self._cache = cache
        self._blob_cache = blob_cache

    async def status(self) -> StorageMaintenanceStatus:
        inventory = await self._inventory.summarize()
        usage = await self._cache.usage()
        cached = await self._blob_cache.evictable_usage() if self._blob_cache is not None else CacheUsage(bytes=0, files=0)
        connection_state = await self._connection_state()
        return StorageMaintenanceStatus(
            connection_state=connection_state,
            can_reclaim=connection_state == "connected",
            fully_remote=inventory.local_blobs == 0 and inventory.telegram_blobs == inventory.total_blobs,
            reclaimable_bytes=usage.bytes + cached.bytes,
            reclaimable_files=usage.files + cached.files,
            local_blob_count=inventory.local_blobs,
            telegram_blob_count=inventory.telegram_blobs,
        )

    async def reclaim(self) -> StorageReclaimResult:
        if await self._connection_state() != "connected":
            raise StorageUnavailableError(StorageBackend.TELEGRAM.value)
        temp = await self._cache.reclaim()
        cached = (
            await self._blob_cache.evict(max_bytes=None)
            if self._blob_cache is not None
            else CacheReclaimResult(freed_bytes=0, deleted_files=0, retained=CacheUsage(bytes=0, files=0), skipped_recent_files=0)
        )
        return StorageReclaimResult(
            freed_bytes=temp.freed_bytes + cached.freed_bytes,
            deleted_files=temp.deleted_files + cached.deleted_files,
            retained_bytes=temp.retained.bytes + cached.retained.bytes,
            retained_files=temp.retained.files + cached.retained.files,
            skipped_recent_files=temp.skipped_recent_files + cached.skipped_recent_files,
        )

    async def _connection_state(self) -> str:
        if self._storage_backend == StorageBackend.LOCAL:
            return "not_configured"
        store = self._remote_store()
        if store is None:
            return "unavailable"
        try:
            return "connected" if await store.probe() else "unavailable"
        except DomainError:
            return "unavailable"
