"""Local plaintext copies of remote blobs (`cache_entries`) with LRU eviction of uploaded originals.

Entries point either at the file ingestion stored under `uploads/` (kept after upload) or at a download
under `cache/blobs/`. Files are content-addressed and never modified in place; a file is only deleted
when no local blob ref and no other cache entry still points at it.
"""

from __future__ import annotations

import asyncio
import threading
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.mappers import require_aware
from bento.domain.errors import StorageUnavailableError
from bento.domain.jobs import JobStatus, JobType
from bento.domain.storage import BlobKind, BlobRef, StorageBackend
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import BlobRefModel, CacheEntryModel, JobModel
from bento.ports.repositories import ClockPort
from bento.ports.storage_maintenance import CacheReclaimResult, CacheUsage

EVICTABLE_KINDS = (BlobKind.ORIGINAL.value,)
PROCESSING_JOB_TYPES = (
    JobType.THUMBNAIL.value,
    JobType.PDF_THUMBNAIL.value,
    JobType.VIDEO_THUMBNAIL.value,
    JobType.METADATA.value,
    JobType.OCR.value,
    JobType.EMBEDDING.value,
)
_ACTIVE_JOB_STATUSES = (JobStatus.QUEUED.value, JobStatus.RUNNING.value, JobStatus.RETRYING.value)


class SQLiteBlobCache:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        clock: ClockPort,
        *,
        data_dir: Path | str,
        recent_grace_seconds: int = 600,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._uploads_dir = (Path(data_dir) / "uploads").resolve()
        self._cache_dir = (Path(data_dir) / "cache" / "blobs").resolve()
        self._grace = timedelta(seconds=recent_grace_seconds)
        self._leases: Counter[str] = Counter()
        self._leases_lock = threading.Lock()

    @property
    def directory(self) -> Path:
        return self._cache_dir

    def path_for(self, blob_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in blob_id).lstrip(".") or "blob"
        return self._cache_dir / safe

    async def register(self, blob_id: str, path: Path, size_bytes: int) -> None:
        resolved = Path(path).resolve()
        if not self._is_managed(resolved):
            raise ValueError("Cache entries must live inside the data directory")
        with session_scope(self._session_factory) as session:
            session.merge(
                CacheEntryModel(
                    blob_ref_id=blob_id,
                    path=str(resolved),
                    size_bytes=size_bytes,
                    last_accessed_at=self._clock.now(),
                )
            )

    async def lookup(self, blob_id: str) -> Path | None:
        """Cached path of a blob (records the access), dropping entries whose file disappeared."""
        return self.lookup_sync(blob_id, touch=True)

    def lookup_sync(self, blob_id: str, *, touch: bool = True) -> Path | None:
        with session_scope(self._session_factory) as session:
            entry = session.get(CacheEntryModel, blob_id)
            if entry is None:
                return None
            path = Path(entry.path)
            if not self._is_managed(path) or not path.is_file():
                session.delete(entry)
                return None
            if touch:
                entry.last_accessed_at = self._clock.now()
            return path

    async def touch(self, blob_id: str) -> None:
        with session_scope(self._session_factory) as session:
            entry = session.get(CacheEntryModel, blob_id)
            if entry is not None:
                entry.last_accessed_at = self._clock.now()

    @contextmanager
    def lease(self, blob_id: str) -> Iterator[None]:
        """Protect a blob being read in this process from eviction."""
        with self._leases_lock:
            self._leases[blob_id] += 1
        try:
            yield
        finally:
            with self._leases_lock:
                self._leases[blob_id] -= 1
                if self._leases[blob_id] <= 0:
                    del self._leases[blob_id]

    async def release_local_copy(self, path: Path, *, exclude_blob_ids: tuple[str, ...] = ()) -> bool:
        resolved = Path(path).resolve()
        with session_scope(self._session_factory) as session:
            if not self._is_managed(resolved) or self._path_in_use(session, resolved, exclude_blob_ids):
                return False
        return await asyncio.to_thread(_unlink, resolved)

    async def remove(self, blob_ids: tuple[str, ...]) -> int:
        """Forget cache entries (purge) and delete their files when nothing else uses them."""
        if not blob_ids:
            return 0
        freed = 0
        with session_scope(self._session_factory) as session:
            entries = list(session.scalars(select(CacheEntryModel).where(CacheEntryModel.blob_ref_id.in_(blob_ids))))
            paths = [Path(entry.path) for entry in entries]
            for entry in entries:
                session.delete(entry)
            session.flush()
            deletable = [
                path for path in paths if self._is_managed(path) and not self._path_in_use(session, path, blob_ids)
            ]
        for path in deletable:
            freed += int(await asyncio.to_thread(_unlink, path))
        return freed

    async def evictable_usage(self) -> CacheUsage:
        with session_scope(self._session_factory) as session:
            row = session.execute(
                select(func.coalesce(func.sum(CacheEntryModel.size_bytes), 0), func.count())
                .select_from(CacheEntryModel)
                .join(BlobRefModel, BlobRefModel.id == CacheEntryModel.blob_ref_id)
                .where(BlobRefModel.kind.in_(EVICTABLE_KINDS), BlobRefModel.backend == StorageBackend.TELEGRAM.value)
            ).one()
        return CacheUsage(bytes=int(row[0]), files=int(row[1]))

    async def over_budget(self, max_bytes: int) -> bool:
        return (await self.evictable_usage()).bytes > max_bytes

    async def evict(self, *, max_bytes: int | None) -> CacheReclaimResult:
        """LRU-evict uploaded originals until their total is at most `max_bytes` (None evicts all eligible).

        Never touches thumbnails/previews, blobs not uploaded yet, recently read or leased files, or originals
        whose asset still has local processing pending. Orphaned entries are always cleaned up.
        """
        now = self._clock.now()
        cutoff = now - self._grace
        freed = 0
        deleted = 0
        skipped_recent = 0
        to_delete: list[Path] = []
        with session_scope(self._session_factory) as session:
            orphans = list(
                session.scalars(
                    select(CacheEntryModel).where(
                        CacheEntryModel.blob_ref_id.not_in(select(BlobRefModel.id))
                    )
                )
            )
            for entry in orphans:
                session.delete(entry)
            session.flush()
            for entry in orphans:
                path = Path(entry.path)
                if self._is_managed(path) and not self._path_in_use(session, path, (entry.blob_ref_id,)):
                    to_delete.append(path)

            rows = list(
                session.execute(
                    select(CacheEntryModel, BlobRefModel.asset_id)
                    .join(BlobRefModel, BlobRefModel.id == CacheEntryModel.blob_ref_id)
                    .where(BlobRefModel.kind.in_(EVICTABLE_KINDS), BlobRefModel.backend == StorageBackend.TELEGRAM.value)
                    .order_by(CacheEntryModel.last_accessed_at.asc(), CacheEntryModel.blob_ref_id.asc())
                )
            )
            total = sum(entry.size_bytes for entry, _ in rows)
            busy_assets = self._assets_with_pending_processing(session)
            for entry, asset_id in rows:
                if max_bytes is not None and total <= max_bytes:
                    break
                if require_aware(entry.last_accessed_at) > cutoff:
                    skipped_recent += 1
                    continue
                if self._is_leased(entry.blob_ref_id) or (asset_id is not None and asset_id in busy_assets):
                    continue
                path = Path(entry.path)
                if not self._is_managed(path):
                    continue
                if self._path_in_use(session, path, (entry.blob_ref_id,)):
                    continue
                session.delete(entry)
                total -= entry.size_bytes
                freed += entry.size_bytes
                deleted += 1
                to_delete.append(path)
        for path in to_delete:
            await asyncio.to_thread(_unlink, path)
        return CacheReclaimResult(
            freed_bytes=freed,
            deleted_files=deleted,
            retained=await self.evictable_usage(),
            skipped_recent_files=skipped_recent,
        )

    def _is_managed(self, path: Path) -> bool:
        resolved = Path(path).resolve()
        return resolved.is_relative_to(self._uploads_dir) or resolved.is_relative_to(self._cache_dir)

    def _path_in_use(self, session: Session, path: Path, exclude_blob_ids: tuple[str, ...]) -> bool:
        resolved = Path(path).resolve()
        entries = select(func.count()).select_from(CacheEntryModel).where(CacheEntryModel.path == str(resolved))
        if exclude_blob_ids:
            entries = entries.where(CacheEntryModel.blob_ref_id.not_in(exclude_blob_ids))
        if session.scalar(entries):
            return True
        if not resolved.is_relative_to(self._uploads_dir):
            return False
        object_key = resolved.relative_to(self._uploads_dir).as_posix()
        local_refs = (
            select(func.count())
            .select_from(BlobRefModel)
            .where(BlobRefModel.backend == StorageBackend.LOCAL.value, BlobRefModel.object_key == object_key)
        )
        if exclude_blob_ids:
            local_refs = local_refs.where(BlobRefModel.id.not_in(exclude_blob_ids))
        return bool(session.scalar(local_refs))

    def _assets_with_pending_processing(self, session: Session) -> set[str]:
        return {
            asset_id
            for asset_id in session.scalars(
                select(JobModel.asset_id).where(
                    JobModel.type.in_(PROCESSING_JOB_TYPES),
                    JobModel.status.in_(_ACTIVE_JOB_STATUSES),
                    JobModel.asset_id.is_not(None),
                )
            )
            if asset_id is not None
        }

    def _is_leased(self, blob_id: str) -> bool:
        with self._leases_lock:
            return self._leases.get(blob_id, 0) > 0


class LocalPathResolverPort(Protocol):
    def resolve(self, blob_ref: BlobRef) -> Path: ...


class SyncSourceLocatorPort(Protocol):
    def find_sync(self, asset_id: str, size_bytes: int) -> Path | None: ...


class CachedBlobPathResolver:
    """`BlobPathResolverPort` that also resolves uploaded blobs through the cache or the backup source file."""

    def __init__(
        self,
        *,
        local: LocalPathResolverPort,
        cache: SQLiteBlobCache,
        sources: SyncSourceLocatorPort | None = None,
    ) -> None:
        self._local = local
        self._cache = cache
        self._sources = sources

    def resolve(self, blob_ref: BlobRef) -> Path:
        if blob_ref.backend == StorageBackend.LOCAL:
            return self._local.resolve(blob_ref)
        cached = self._cache.lookup_sync(blob_ref.id)
        if cached is not None:
            return cached
        if blob_ref.kind == BlobKind.ORIGINAL and blob_ref.asset_id is not None and self._sources is not None:
            source = self._sources.find_sync(blob_ref.asset_id, blob_ref.size_bytes)
            if source is not None:
                return source
        raise StorageUnavailableError(blob_ref.backend.value)


class CachedBlobSourceMaterializer:
    """`BlobSourceMaterializerPort` that serves local copies and downloads remote-only blobs into the cache."""

    def __init__(
        self,
        *,
        resolver: CachedBlobPathResolver,
        cache: SQLiteBlobCache,
        fetch: Callable[[BlobRef], Awaitable[Path]],
    ) -> None:
        self._resolver = resolver
        self._cache = cache
        self._fetch = fetch

    @asynccontextmanager
    async def materialize(self, blob_ref: BlobRef) -> AsyncIterator[Path]:
        with self._cache.lease(blob_ref.id):
            try:
                path = self._resolver.resolve(blob_ref)
            except StorageUnavailableError:
                if blob_ref.backend == StorageBackend.LOCAL:
                    raise
                path = await self._fetch(blob_ref)
            yield path


def _unlink(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False

