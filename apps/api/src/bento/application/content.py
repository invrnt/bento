"""Plaintext access to asset content from the local cache, the backup source, or the remote store."""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import os
import threading
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bento.application.storage_pipeline import LocalBlobFilesPort, RemoteStoreProvider, SourceFilesPort
from bento.domain.activity import TransferStats
from bento.domain.assets import Asset
from bento.domain.errors import AssetNotFoundError, IntegrityError, StorageUnavailableError
from bento.domain.storage import BlobKind, BlobRef, StorageBackend
from bento.ports.blob_store import RemoteBlobStorePort

FULL_FETCH_THRESHOLD_BYTES = 32 * 1024 * 1024
"""Remote originals up to this size are downloaded whole on first open; larger ones stream by range."""


class ContentAssetsPort(Protocol):
    async def get(self, asset_id: str) -> Asset | None: ...


class ContentBlobCatalogPort(Protocol):
    async def latest_for_asset(self, asset_id: str, kind: BlobKind) -> BlobRef | None: ...


class ContentCachePort(Protocol):
    async def lookup(self, blob_id: str) -> Path | None: ...

    async def touch(self, blob_id: str) -> None: ...

    async def register(self, blob_id: str, path: Path, size_bytes: int) -> None: ...

    def path_for(self, blob_id: str) -> Path: ...

    def lease(self, blob_id: str) -> AbstractContextManager[None]: ...


@dataclass(frozen=True, slots=True)
class ContentSource:
    asset: Asset
    blob_ref: BlobRef
    size_bytes: int
    path: Path | None
    """Local plaintext file when available; otherwise ranges are fetched from the remote store."""


class TransferTracker:
    """In-process transfer progress (downloads served by this API process)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._active: dict[int, list[int]] = {}

    def start(self, total_bytes: int) -> int:
        with self._lock:
            token = next(self._ids)
            self._active[token] = [max(total_bytes, 0), 0]
            return token

    def advance(self, token: int, size: int) -> None:
        with self._lock:
            if token in self._active:
                self._active[token][1] += size

    def finish(self, token: int) -> None:
        with self._lock:
            self._active.pop(token, None)

    def snapshot(self) -> TransferStats:
        with self._lock:
            values = list(self._active.values())
        return TransferStats(
            active=len(values),
            queued=0,
            bytes_total=sum(total for total, _ in values),
            bytes_done=sum(min(done, total) for total, done in values),
        )


class AssetContentService:
    """`AssetContentPort` implementation shared by downloads, streaming, thumbnails, sharing, and media jobs."""

    def __init__(
        self,
        *,
        assets: ContentAssetsPort,
        blob_refs: ContentBlobCatalogPort,
        cache: ContentCachePort,
        local_files: LocalBlobFilesPort,
        remote: RemoteStoreProvider,
        sources: SourceFilesPort | None = None,
        tracker: TransferTracker | None = None,
        on_cache_growth: Callable[[], Awaitable[None]] | None = None,
        full_fetch_threshold: int = FULL_FETCH_THRESHOLD_BYTES,
    ) -> None:
        self._assets = assets
        self._blob_refs = blob_refs
        self._cache = cache
        self._local_files = local_files
        self._remote = remote
        self._sources = sources
        self._tracker = tracker or TransferTracker()
        self._on_cache_growth = on_cache_growth
        self._full_fetch_threshold = full_fetch_threshold
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def tracker(self) -> TransferTracker:
        return self._tracker

    async def materialize_original(self, asset_id: str) -> Path:
        _, blob_ref = await self._original(asset_id)
        return await self.blob_path(blob_ref)

    async def read_range(self, asset_id: str, start: int, length: int) -> bytes:
        return await self.read_source_range(await self.open_original(asset_id), start, length)

    async def open_original(self, asset_id: str) -> ContentSource:
        asset, blob_ref = await self._original(asset_id)
        path = await self.local_path(blob_ref)
        if path is None and blob_ref.size_bytes <= self._full_fetch_threshold:
            path = await self.blob_path(blob_ref)
        return ContentSource(asset=asset, blob_ref=blob_ref, size_bytes=blob_ref.size_bytes, path=path)

    async def read_source_range(self, source: ContentSource, start: int, length: int) -> bytes:
        if start < 0 or length < 0:
            raise ValueError("Range start and length cannot be negative")
        length = max(0, min(length, source.size_bytes - start))
        if length == 0:
            return b""
        if source.path is not None:
            with self._cache.lease(source.blob_ref.id):
                return await asyncio.to_thread(_read_file_range, source.path, start, length)
        store = self._require_remote()
        token = self._tracker.start(length)
        try:
            data = await store.read_range(source.blob_ref, start, length)
            self._tracker.advance(token, len(data))
        finally:
            self._tracker.finish(token)
        await self._cache.touch(source.blob_ref.id)
        return data

    async def local_path(self, blob_ref: BlobRef) -> Path | None:
        """Local plaintext path without network access, or None."""
        if blob_ref.backend == StorageBackend.LOCAL:
            return self._local_files.resolve(blob_ref)
        cached = await self._cache.lookup(blob_ref.id)
        if cached is not None:
            return cached
        if blob_ref.kind == BlobKind.ORIGINAL and blob_ref.asset_id is not None and self._sources is not None:
            return await self._sources.find_source(blob_ref.asset_id, blob_ref.size_bytes)
        return None

    async def blob_path(self, blob_ref: BlobRef) -> Path:
        """Local plaintext path of any blob, downloading a remote-only blob into the cache."""
        path = await self.local_path(blob_ref)
        if path is not None:
            return path
        lock = self._locks.setdefault(blob_ref.id, asyncio.Lock())
        try:
            async with lock:
                path = await self.local_path(blob_ref)
                if path is not None:
                    return path
                path = await self._download(blob_ref)
        finally:
            if not lock.locked():
                self._locks.pop(blob_ref.id, None)
        if self._on_cache_growth is not None:
            await self._on_cache_growth()
        return path

    async def _download(self, blob_ref: BlobRef) -> Path:
        store = self._require_remote()
        destination = self._cache.path_for(blob_ref.id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.partial")
        token = self._tracker.start(blob_ref.size_bytes)
        try:
            downloaded = Path(await store.download(blob_ref, partial))
            size, sha256 = await asyncio.to_thread(_size_and_sha256, downloaded)
            if size != blob_ref.size_bytes or (blob_ref.sha256 is not None and sha256 != blob_ref.sha256):
                raise IntegrityError("blob")
            self._tracker.advance(token, size)
            await asyncio.to_thread(os.replace, downloaded, destination)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        finally:
            self._tracker.finish(token)
        await self._cache.register(blob_ref.id, destination, blob_ref.size_bytes)
        return destination

    async def _original(self, asset_id: str) -> tuple[Asset, BlobRef]:
        asset = await self._assets.get(asset_id)
        if asset is None:
            raise AssetNotFoundError(asset_id)
        blob_ref = await self._blob_refs.latest_for_asset(asset.id, BlobKind.ORIGINAL)
        if blob_ref is None:
            raise AssetNotFoundError(asset_id)
        return asset, blob_ref

    def _require_remote(self) -> RemoteBlobStorePort:
        store = self._remote()
        if store is None:
            raise StorageUnavailableError(StorageBackend.TELEGRAM.value)
        return store


def _read_file_range(path: Path, start: int, length: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(start)
        return handle.read(length)


def _size_and_sha256(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()
