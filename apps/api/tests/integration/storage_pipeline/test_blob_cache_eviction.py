from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from bento.adapters.jobs import SQLiteJobQueue
from bento.adapters.media import SQLiteBlobRefCatalog
from bento.adapters.repositories import SQLiteAssetRepository
from bento.adapters.storage.cache import SQLiteBlobCache
from bento.adapters.storage.maintenance import LocalEphemeralCache, SQLiteStorageInventory
from bento.application.storage_maintenance import StorageMaintenanceService
from bento.domain.jobs import JobType
from bento.domain.storage import BlobKind, BlobPart, BlobRef, StorageBackend
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import CacheEntryModel
from tests.integration.db.support import NOW, FixedClock, make_asset, migrated_session_factory
from tests.integration.storage_pipeline.support import run

MB = 1024 * 1024


class Library:
    def __init__(self, tmp_path: Path) -> None:
        self.data_dir = tmp_path / "data"
        self.factory = migrated_session_factory(tmp_path)
        self.clock = FixedClock()
        self.refs = SQLiteBlobRefCatalog(self.factory, self.clock)
        self.assets = SQLiteAssetRepository(self.factory)
        self.cache = SQLiteBlobCache(self.factory, self.clock, data_dir=self.data_dir, recent_grace_seconds=600)
        self.count = 0

    async def cached(
        self,
        *,
        kind: BlobKind = BlobKind.ORIGINAL,
        backend: StorageBackend = StorageBackend.TELEGRAM,
        size: int = MB,
        accessed_minutes_ago: int = 60,
        path: Path | None = None,
    ) -> tuple[str, Path]:
        self.count += 1
        asset_id = f"asset_{self.count}"
        await self.assets.add(make_asset(asset_id, sha256=f"{self.count:064x}"))
        blob_id = f"tg_{self.count}"
        await self.refs.add(
            BlobRef(
                id=blob_id,
                asset_id=asset_id,
                backend=backend,
                kind=kind,
                object_key=f"vault/{blob_id}",
                size_bytes=size,
                sha256=f"{self.count:064x}",
                parts=(BlobPart(index=0, channel_id="-1001", message_id=str(self.count), size_bytes=size + 52),),
            )
        )
        file_path = path or self.cache.path_for(blob_id)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if not file_path.exists():
            file_path.write_bytes(b"x" * size)
        self.clock.current = NOW - timedelta(minutes=accessed_minutes_ago)
        await self.cache.register(blob_id, file_path, size)
        self.clock.current = NOW
        return blob_id, file_path


def test_lru_eviction_frees_oldest_uploaded_originals_down_to_the_budget(tmp_path: Path) -> None:
    async def scenario() -> None:
        library = Library(tmp_path)
        oldest = await library.cached(accessed_minutes_ago=300)
        middle = await library.cached(accessed_minutes_ago=200)
        newest = await library.cached(accessed_minutes_ago=100)

        assert (await library.cache.evictable_usage()).bytes == 3 * MB
        assert await library.cache.over_budget(2 * MB)

        result = await library.cache.evict(max_bytes=2 * MB)

        assert (result.freed_bytes, result.deleted_files) == (MB, 1)
        assert not oldest[1].exists() and middle[1].exists() and newest[1].exists()
        assert result.retained.bytes == 2 * MB
        assert await library.cache.lookup(oldest[0]) is None
        assert await library.cache.lookup(middle[0]) == middle[1].resolve()

    run(scenario())


def test_eviction_never_touches_thumbnails_recent_leased_busy_or_shared_files(tmp_path: Path) -> None:
    async def scenario() -> None:
        library = Library(tmp_path)
        thumbnail = await library.cached(kind=BlobKind.THUMBNAIL, accessed_minutes_ago=999)
        preview = await library.cached(kind=BlobKind.PREVIEW, accessed_minutes_ago=999)
        recent = await library.cached(accessed_minutes_ago=1)
        leased = await library.cached(accessed_minutes_ago=999)
        busy = await library.cached(accessed_minutes_ago=999)
        await SQLiteJobQueue(library.factory, library.clock).enqueue(
            type=JobType.OCR, priority=3, payload={}, asset_id="asset_5"
        )
        uploads = library.data_dir / "uploads"
        shared_path = uploads / "blobs" / "original" / "ab" / "cd" / ("ab" * 32)
        shared = await library.cached(accessed_minutes_ago=999, path=shared_path)
        await library.refs.add(
            BlobRef(
                id="local_original_" + "ab" * 32,
                asset_id="asset_1",
                backend=StorageBackend.LOCAL,
                kind=BlobKind.ORIGINAL,
                object_key=shared_path.relative_to(uploads).as_posix(),
                size_bytes=MB,
                sha256="ab" * 32,
            )
        )
        evictable = await library.cached(accessed_minutes_ago=999)

        with library.cache.lease(leased[0]):
            result = await library.cache.evict(max_bytes=0)

        assert result.deleted_files == 1 and result.skipped_recent_files == 1
        assert not evictable[1].exists()
        for kept in (thumbnail, preview, recent, leased, busy, shared):
            assert kept[1].exists(), kept
        with session_scope(library.factory) as session:
            remaining = set(session.scalars(select(CacheEntryModel.blob_ref_id)))
        assert remaining == {thumbnail[0], preview[0], recent[0], leased[0], busy[0], shared[0]}

    run(scenario())


def test_local_only_blobs_and_orphans(tmp_path: Path) -> None:
    async def scenario() -> None:
        library = Library(tmp_path)
        local_only = await library.cached(backend=StorageBackend.LOCAL, accessed_minutes_ago=999)
        orphan_path = library.cache.path_for("tg_gone")
        orphan_path.parent.mkdir(parents=True, exist_ok=True)
        orphan_path.write_bytes(b"gone")
        await library.cache.register("tg_gone", orphan_path, 4)

        result = await library.cache.evict(max_bytes=0)

        assert local_only[1].exists()
        assert not orphan_path.exists()
        assert result.deleted_files == 0
        assert (await library.cache.evictable_usage()).bytes == 0

    run(scenario())


def test_paths_outside_the_data_directory_are_never_registered_or_deleted(tmp_path: Path) -> None:
    async def scenario() -> None:
        library = Library(tmp_path)
        outside = tmp_path / "user-file.txt"
        outside.write_bytes(b"keep me")
        try:
            await library.cache.register("tg_x", outside, 7)
        except ValueError:
            pass
        else:  # pragma: no cover - defensive
            raise AssertionError("outside path was registered")
        assert await library.cache.release_local_copy(outside) is False
        assert outside.exists()

    run(scenario())


def test_liberar_espacio_evicts_cached_originals_with_temp_files(tmp_path: Path) -> None:
    async def scenario() -> None:
        library = Library(tmp_path)
        blob_id, path = await library.cached(accessed_minutes_ago=999)

        class Connected:
            async def probe(self) -> bool:
                return True

        service = StorageMaintenanceService(
            storage_backend=StorageBackend.TELEGRAM,
            remote_store=lambda: Connected(),
            inventory=SQLiteStorageInventory(library.factory),
            cache=LocalEphemeralCache(library.data_dir),
            blob_cache=library.cache,
        )
        status = await service.status()
        assert status.reclaimable_bytes == MB and status.reclaimable_files == 1 and status.can_reclaim

        result = await service.reclaim()

        assert result.freed_bytes == MB and result.deleted_files == 1
        assert not path.exists()
        assert await library.cache.lookup(blob_id) is None

    run(scenario())
