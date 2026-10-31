"""Composition of the storage pipeline, content/cache, folder backup, trash, and activity services.

One instance per data directory and process (API and worker each build their own). Every service reads
the remote store, vault, and sync status through the factories in `infrastructure.services`, treating a
missing implementation or a not-ready vault as "local only".
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.backup.activity import SQLiteActivitySource
from bento.adapters.backup.pipeline import SQLitePipelineCatalog
from bento.adapters.backup.repositories import (
    BANDWIDTH_SETTING,
    PAUSE_ON_BATTERY_SETTING,
    SQLiteBackupFileRepository,
    SQLiteBackupJobs,
    SQLiteBackupPolicyRepository,
    SQLiteBackupSourceLocator,
    SQLiteBackupSourceRepository,
    SQLiteFolderLookup,
)
from bento.adapters.backup.scanner import LocalFolderScanner
from bento.adapters.backup.suggestions import OsBackupSuggestions
from bento.adapters.backup.trash import SQLiteTrashRepository
from bento.adapters.jobs import SQLiteJobQueue
from bento.adapters.manifest import SQLiteManifestJournal
from bento.adapters.media import LocalBlobPathResolver, LocalUploadMetadataExtractor, SQLiteBlobRefCatalog
from bento.adapters.repositories import SQLiteAssetRepository, SQLiteFolderRepository
from bento.adapters.repositories.ids import new_id
from bento.adapters.search.sqlite_fts import SQLiteFTSSearchIndex
from bento.adapters.search.sqlite_vec import SQLiteVecSearchIndex
from bento.adapters.storage.cache import CachedBlobPathResolver, CachedBlobSourceMaterializer, SQLiteBlobCache
from bento.adapters.storage.local_blob_store import LocalBlobStoreAdapter
from bento.adapters.storage.maintenance import LocalEphemeralCache, SQLiteStorageInventory
from bento.application.activity import ActivityService
from bento.application.backup import BackupService
from bento.application.content import FULL_FETCH_THRESHOLD_BYTES, AssetContentService
from bento.application.drive import DriveUseCases
from bento.application.ingestion import AssetFileQueryService, AssetIngestionService
from bento.application.storage_maintenance import StorageMaintenanceService
from bento.application.storage_pipeline import RemoteStoreProvider, StoragePipelineService
from bento.application.trash import TrashService
from bento.application.upload import UploadAssetUseCase
from bento.domain.errors import DomainError
from bento.domain.jobs import JobType
from bento.domain.settings import SettingSource
from bento.domain.storage import StorageBackend
from bento.domain.sync import SyncStatus
from bento.domain.vault import VaultStatus
from bento.infrastructure.db.clock import SystemClock
from bento.infrastructure.db.engine import create_app_session_factory
from bento.infrastructure.settings import Settings
from bento.ports.blob_store import RemoteBlobStorePort

GIB = 1024**3


@dataclass(frozen=True, slots=True)
class StoragePipelineComponents:
    settings: Settings
    data_dir: Path
    session_factory: sessionmaker[Session]
    clock: SystemClock
    jobs: SQLiteJobQueue
    assets: SQLiteAssetRepository
    manifest: SQLiteManifestJournal
    blob_refs: SQLiteBlobRefCatalog
    local_store: LocalBlobStoreAdapter
    local_resolver: LocalBlobPathResolver
    cache: SQLiteBlobCache
    cache_max_bytes: int
    resolver: CachedBlobPathResolver
    materializer: CachedBlobSourceMaterializer
    remote: RemoteStoreProvider
    pipeline: StoragePipelineService
    content: AssetContentService
    ingestion: AssetIngestionService
    files: AssetFileQueryService
    drive: DriveUseCases
    backup: BackupService
    backup_jobs: SQLiteBackupJobs
    trash: TrashService
    activity: ActivityService
    maintenance: StorageMaintenanceService

    async def request_cache_eviction(self) -> bool:
        """Enqueue `cache_evict` when cached originals exceed `cache_max_gb`."""
        if not await self.cache.over_budget(self.cache_max_bytes):
            return False
        if await self.backup_jobs.has_waiting(JobType.CACHE_EVICT):
            return False
        await self.jobs.enqueue(type=JobType.CACHE_EVICT, priority=7, payload={})
        return True


_lock = threading.Lock()
_components: dict[tuple[str, str], StoragePipelineComponents] = {}


def get_storage_pipeline(settings: Settings) -> StoragePipelineComponents:
    key = (str(Path(settings.data_dir).resolve()), settings.storage_backend)
    with _lock:
        cached = _components.get(key)
        if cached is None:
            cached = _components[key] = build_storage_pipeline(settings)
        return cached


def reset_storage_pipeline() -> None:
    with _lock:
        _components.clear()


def remote_store_provider(settings: Settings) -> RemoteStoreProvider:
    def provide() -> RemoteBlobStorePort | None:
        if settings.storage_backend == StorageBackend.LOCAL.value:
            return None
        from bento.infrastructure.services import get_remote_blob_store

        try:
            return get_remote_blob_store(settings)
        except (NotImplementedError, DomainError):
            return None

    return provide


def build_storage_pipeline(
    settings: Settings,
    *,
    remote: RemoteStoreProvider | None = None,
    session_factory: sessionmaker[Session] | None = None,
    full_fetch_threshold: int = FULL_FETCH_THRESHOLD_BYTES,
    cache_grace_seconds: int = 600,
) -> StoragePipelineComponents:
    data_dir = Path(settings.data_dir)
    factory = session_factory or create_app_session_factory(settings)
    clock = SystemClock()
    remote = remote or remote_store_provider(settings)
    jobs = SQLiteJobQueue(factory, clock)
    assets = SQLiteAssetRepository(factory)
    folders = SQLiteFolderRepository(factory)
    blob_refs = SQLiteBlobRefCatalog(factory, clock)
    manifest = SQLiteManifestJournal(factory, clock, data_dir / "journal")
    local_store = LocalBlobStoreAdapter(data_dir / "uploads")
    local_resolver = LocalBlobPathResolver(data_dir / "uploads")
    cache = SQLiteBlobCache(factory, clock, data_dir=data_dir, recent_grace_seconds=cache_grace_seconds)
    sources = SQLiteBackupSourceLocator(factory)
    backup_jobs = SQLiteBackupJobs(factory)
    cache_max_bytes = int(settings.cache_max_gb * GIB)
    pipeline = StoragePipelineService(
        catalog=SQLitePipelineCatalog(factory),
        jobs=jobs,
        remote=remote,
        local_files=local_resolver,
        cache=cache,
        clock=clock,
        sources=sources,
    )
    holder: dict[str, StoragePipelineComponents] = {}

    async def on_cache_growth() -> None:
        await holder["components"].request_cache_eviction()

    content = AssetContentService(
        assets=assets,
        blob_refs=blob_refs,
        cache=cache,
        local_files=local_resolver,
        remote=remote,
        sources=sources,
        on_cache_growth=on_cache_growth,
        full_fetch_threshold=full_fetch_threshold,
    )
    resolver = CachedBlobPathResolver(local=local_resolver, cache=cache, sources=sources)
    ingestion = AssetIngestionService(
        upload=UploadAssetUseCase(
            assets=assets,
            folders=folders,
            blob_store=local_store,
            jobs=jobs,
            manifest=manifest,
            clock=clock,
        ),
        blob_refs=blob_refs,
        metadata_extractor=LocalUploadMetadataExtractor(),
        remote_uploads=pipeline,
    )
    drive = DriveUseCases(assets=assets, folders=folders, manifest=manifest, clock=clock)
    policy = SQLiteBackupPolicyRepository(factory, clock, locked=_locked_backup_settings(settings))
    backup = BackupService(
        sources=SQLiteBackupSourceRepository(factory),
        files=SQLiteBackupFileRepository(factory),
        policy=policy,
        suggestions=OsBackupSuggestions(),
        scanner=LocalFolderScanner(),
        jobs=jobs,
        job_state=backup_jobs,
        clock=clock,
        data_dir=data_dir,
        new_id=lambda: new_id("bsrc"),
        ingestion=ingestion,
        folders=SQLiteFolderLookup(factory),
        folder_creator=drive,
    )
    trash = TrashService(
        catalog=SQLiteTrashRepository(factory, clock, retention_days=settings.trash_retention_days),
        cache=cache,
        local_files=local_resolver,
        remote=remote,
        jobs=jobs,
        clock=clock,
        search_indexes=(
            SQLiteFTSSearchIndex(factory, clock),
            SQLiteVecSearchIndex(factory, clock, dimensions=settings.embedding_dimensions),
        ),
    )
    activity = ActivityService(
        source=SQLiteActivitySource(factory),
        policy=policy,
        clock=clock,
        downloads=content.tracker,
        sync_status=_sync_status(settings),
        vault_status=_vault_status(settings),
    )

    maintenance = StorageMaintenanceService(
        storage_backend=StorageBackend(settings.storage_backend),
        remote_store=remote,
        inventory=SQLiteStorageInventory(factory),
        cache=LocalEphemeralCache(data_dir),
        blob_cache=cache,
    )
    components = StoragePipelineComponents(
        settings=settings,
        data_dir=data_dir,
        session_factory=factory,
        clock=clock,
        jobs=jobs,
        assets=assets,
        manifest=manifest,
        blob_refs=blob_refs,
        local_store=local_store,
        local_resolver=local_resolver,
        cache=cache,
        cache_max_bytes=cache_max_bytes,
        resolver=resolver,
        materializer=CachedBlobSourceMaterializer(resolver=resolver, cache=cache, fetch=content.blob_path),
        remote=remote,
        pipeline=pipeline,
        content=content,
        ingestion=ingestion,
        files=AssetFileQueryService(assets=assets, blob_refs=blob_refs, manifest=manifest, clock=clock),
        drive=drive,
        backup=backup,
        backup_jobs=backup_jobs,
        trash=trash,
        activity=activity,
        maintenance=maintenance,
    )
    holder["components"] = components
    return components


def _locked_backup_settings(settings: Settings) -> dict[str, object]:
    snapshot = settings.effective_snapshot
    if snapshot is None:
        return {}
    locked: dict[str, object] = {}
    for key in (PAUSE_ON_BATTERY_SETTING, BANDWIDTH_SETTING):
        item = snapshot.values.get(key)
        if item is not None and item.source in {SettingSource.ENVIRONMENT, SettingSource.POLICY}:
            locked[key] = item.value
    return locked


def _sync_status(settings: Settings) -> Callable[[], Any]:
    async def status() -> SyncStatus | None:
        if settings.storage_backend == StorageBackend.LOCAL.value:
            return None
        from bento.infrastructure.services import get_sync_status_provider

        try:
            provider = get_sync_status_provider(settings)
        except NotImplementedError:
            return None
        return await provider.status()

    return status


def _vault_status(settings: Settings) -> Callable[[], Any]:
    async def status() -> VaultStatus | None:
        if settings.storage_backend == StorageBackend.LOCAL.value:
            return None
        from bento.infrastructure.services import get_vault_session

        try:
            session = get_vault_session(settings)
        except NotImplementedError:
            return None
        return await session.status()

    return status
