import asyncio
import logging
import os
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from bento.adapters.embeddings import SQLiteEmbeddingTextCatalog
from bento.adapters.jobs import SQLiteJobQueue
from bento.adapters.manifest import SQLiteManifestJournal
from bento.adapters.media import SQLiteBlobRefCatalog, SQLiteThumbnailCatalog
from bento.adapters.ocr import SQLitePDFPageTextCatalog
from bento.adapters.repositories import SQLiteAssetRepository
from bento.adapters.runtime.embedding_setup import WorkerEmbedding, build_worker_embedding, default_model_ports
from bento.adapters.search.sqlite_fts import SQLiteFTSSearchIndex
from bento.adapters.search.sqlite_vec import SQLiteVecSearchIndex
from bento.application.indexing.embedding import EmbeddingIndexingService
from bento.application.indexing.reindex import ReindexService
from bento.application.media import MediaProcessingService, ProcessingCompletionService
from bento.domain.smart_search import SmartSearchStatus
from bento.application.indexing import OCRIndexingService
from bento.application.ingestion import IndexingPolicy
from bento.infrastructure import services
from bento.infrastructure.db.clock import SystemClock
from bento.infrastructure.db.engine import create_app_session_factory
from bento.infrastructure.settings import Settings, get_settings
from bento.infrastructure.storage_pipeline import get_storage_pipeline
from bento.interfaces.worker.dispatch import WorkerDispatcher
from bento.interfaces.worker.handlers_models import build_model_download_handler
from bento.adapters.sync import configure_change_capture
from bento.interfaces.worker.telegram import TelegramJobHandlers, run_inbox_loop
from bento.interfaces.worker.storage_pipeline import StoragePipelineJobHandler, StoragePipelineLoop
from bento.interfaces.worker.sync_loop import (
    SyncSnapshotJobHandler,
    create_asset_index_recorder,
    start_sync_loop,
    stop_sync_loop,
)

LOGGER = logging.getLogger("bento.worker")


async def run_worker(stop_event: asyncio.Event | None = None) -> None:
    """The worker process: job loop plus Inbox, storage-pipeline housekeeping, and sync loops until `stop_event`.

    With smart search on, the worker also owns the embedding server: it starts it for the active space,
    restarts it with backoff, and stops it on shutdown (settings changes restart the worker, so turning smart
    search off or removing the model stops it too)."""
    from bento.interfaces.worker.runtime import WorkerRuntime

    settings = get_settings()
    stop = stop_event or asyncio.Event()
    embedding_runtime = _worker_embedding(settings).runtime
    supervisor = (
        asyncio.create_task(embedding_runtime.run(stop), name="bento-embedding-runtime")
        if embedding_runtime is not None
        else None
    )
    try:
        await WorkerRuntime(settings).run(stop)
    finally:
        stop.set()
        if supervisor is not None:
            await asyncio.gather(supervisor, return_exceptions=True)


def _create_dispatcher(worker_id: str, settings: Settings | None = None) -> WorkerDispatcher:
    settings = settings or get_settings()
    data_dir = Path(settings.data_dir)
    clock = SystemClock()
    session_factory = create_app_session_factory(settings)
    jobs = SQLiteJobQueue(session_factory, clock)
    assets = SQLiteAssetRepository(session_factory)
    blob_refs = SQLiteBlobRefCatalog(session_factory, clock)
    thumbnails = SQLiteThumbnailCatalog(session_factory, clock, blob_refs)
    manifest = SQLiteManifestJournal(session_factory, clock, data_dir / "journal")
    pipeline = get_storage_pipeline(settings)
    resolver = pipeline.resolver
    media = MediaProcessingService(
        assets=assets,
        blob_refs=blob_refs,
        thumbnails=thumbnails,
        blob_store=pipeline.local_store,
        materializer=pipeline.materializer,
        generator=services.get_media_generator(settings, data_dir / "cache" / "media"),
        manifest=manifest,
        clock=clock,
        remote_uploads=pipeline.pipeline,
    )
    provider = services.get_ocr_provider(settings)
    ocr = OCRIndexingService(
        assets=assets,
        blob_refs=blob_refs,
        resolver=resolver,
        provider=provider,
        index=SQLiteFTSSearchIndex(session_factory, clock),
        manifest=manifest,
        clock=clock,
        pdf_renderer=services.get_pdf_page_renderer(settings, data_dir / "cache" / "ocr" / "pdf-pages"),
        pdf_pages=SQLitePDFPageTextCatalog(session_factory, clock),
        index_recorder=create_asset_index_recorder(settings, session_factory),
    )
    worker_embedding = _worker_embedding(settings)
    embedding = EmbeddingIndexingService(
        assets=assets,
        blob_refs=blob_refs,
        resolver=resolver,
        provider=worker_embedding.provider,
        index=SQLiteVecSearchIndex(session_factory, clock, dimensions=worker_embedding.dimensions),
        manifest=manifest,
        clock=clock,
        text_catalog=SQLiteEmbeddingTextCatalog(session_factory),
        index_recorder=create_asset_index_recorder(settings, session_factory),
        chunk_tokens=worker_embedding.chunk_tokens,
    )
    model_download = build_model_download_handler(
        data_dir=data_dir,
        session_factory=session_factory,
        clock=clock,
        jobs=jobs,
        app_version=settings.app_version,
        hooks=worker_embedding.hooks,
    )
    if worker_embedding.runtime is not None:
        worker_embedding.runtime.attach_status(model_download.activation)
    indexing = IndexingPolicy.from_providers(
        ocr_provider=settings.ocr_provider, embeddings_provider=settings.embeddings_provider
    )
    return WorkerDispatcher(
        jobs=jobs,
        media=media,
        clock=clock,
        worker_id=worker_id,
        ocr=ocr,
        embedding=embedding,
        model_download=model_download,
        telegram=TelegramJobHandlers(settings),
        storage_pipeline=StoragePipelineJobHandler(pipeline),
        sync_snapshot=SyncSnapshotJobHandler(session_factory),
        processing=ProcessingCompletionService(assets=assets, jobs=jobs, clock=clock),
        reindex=ReindexService(
            assets=assets,
            jobs=jobs,
            active=jobs,
            ocr_enabled=indexing.ocr,
            embeddings_enabled=indexing.embeddings,
        ),
    )


_WORKER_EMBEDDINGS: dict[tuple[str, ...], WorkerEmbedding] = {}


def _worker_embedding(settings: Settings) -> WorkerEmbedding:
    """One provider + runtime per profile, shared by the dispatcher and the runtime supervisor."""
    key = (
        str(Path(settings.data_dir).expanduser().resolve()),
        str(settings.embeddings_provider),
        str(getattr(settings, "smart_search_model", "")),
        str(settings.embedding_dimensions),
        str(getattr(settings, "custom_model_path", "")),
        str(settings.embedding_server_url),
    )
    cached = _WORKER_EMBEDDINGS.get(key)
    if cached is None:
        catalog, store = (
            default_model_ports(settings) if settings.embeddings_provider == "managed" else (None, None)
        )
        cached = build_worker_embedding(
            settings, catalog=catalog, store=store, load_status=_status_loader(settings)
        )
        _WORKER_EMBEDDINGS[key] = cached
    return cached


def _status_loader(settings: Settings) -> Callable[[], Awaitable[SmartSearchStatus]]:
    """The persisted smart search status decides which space the worker serves (`StatusRuntimeTargets`)."""
    repository: Any = None

    async def load() -> SmartSearchStatus:
        nonlocal repository
        if repository is None:
            from bento.adapters.models.sqlite_status import SQLiteSmartSearchStatusRepository

            repository = SQLiteSmartSearchStatusRepository(create_app_session_factory(settings), SystemClock())
        status: SmartSearchStatus = await repository.load()
        return status

    return load


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    stop_event = asyncio.Event()

    for signal_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, signal_name, None)
        if sig is not None:
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass

    try:
        loop.run_until_complete(run_worker(stop_event))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
