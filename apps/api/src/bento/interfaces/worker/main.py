import asyncio
import logging
import os
import signal
from pathlib import Path

from bento.adapters.embeddings import (
    DisabledEmbeddingProvider,
    JinaOmniNanoGgufAdapter,
    MockEmbeddingProvider,
    SQLiteEmbeddingTextCatalog,
)
from bento.adapters.jobs import SQLiteJobQueue
from bento.adapters.manifest import SQLiteManifestJournal
from bento.adapters.backup.watcher import WatchdogFolderWatcher
from bento.adapters.media import LocalMediaGenerator, SQLiteBlobRefCatalog, SQLiteThumbnailCatalog
from bento.adapters.ocr import DisabledOCRAdapter, MockOCRAdapter, Pypdfium2PDFPageRenderer, RapidOCRAdapter, SQLitePDFPageTextCatalog
from bento.adapters.repositories import SQLiteAssetRepository
from bento.adapters.search.sqlite_fts import SQLiteFTSSearchIndex
from bento.adapters.search.sqlite_vec import SQLiteVecSearchIndex
from bento.application.indexing.embedding import EmbeddingIndexingService
from bento.application.media import MediaProcessingService
from bento.application.indexing import OCRIndexingService
from bento.infrastructure.db.clock import SystemClock
from bento.infrastructure.db.engine import create_app_session_factory
from bento.infrastructure.settings import Settings, get_settings
from bento.infrastructure.storage_pipeline import get_storage_pipeline
from bento.interfaces.worker.dispatch import WorkerDispatcher
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
    settings = get_settings()
    LOGGER.info(
        "Worker started in %s mode with concurrency=%s",
        settings.storage_backend,
        settings.worker_concurrency,
    )
    event = stop_event or asyncio.Event()
    configure_change_capture(settings.storage_backend != "local")
    dispatcher = _create_dispatcher(worker_id=f"worker-{os.getpid()}", settings=settings)
    inbox_loop = asyncio.create_task(run_inbox_loop(settings, event))
    pipeline_loop = asyncio.create_task(
        StoragePipelineLoop(get_storage_pipeline(settings), watcher=WatchdogFolderWatcher()).run(event)
    )
    sync_task = start_sync_loop(settings, event)
    try:
        while not event.is_set():
            processed = await dispatcher.process_one()
            if processed:
                continue
            try:
                await asyncio.wait_for(event.wait(), timeout=1.0)
            except TimeoutError:
                continue
    finally:
        event.set()
        await asyncio.gather(inbox_loop, return_exceptions=True)
        await pipeline_loop
        await stop_sync_loop(sync_task)


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
        generator=LocalMediaGenerator(data_dir / "cache" / "media"),
        manifest=manifest,
        clock=clock,
        remote_uploads=pipeline.pipeline,
    )
    if settings.ocr_provider == "rapidocr":
        provider = RapidOCRAdapter()
    elif settings.ocr_provider == "mock":
        provider = MockOCRAdapter()
    else:
        provider = DisabledOCRAdapter()
    ocr = OCRIndexingService(
        assets=assets,
        blob_refs=blob_refs,
        resolver=resolver,
        provider=provider,
        index=SQLiteFTSSearchIndex(session_factory, clock),
        manifest=manifest,
        clock=clock,
        pdf_renderer=Pypdfium2PDFPageRenderer(data_dir / "cache" / "ocr" / "pdf-pages"),
        pdf_pages=SQLitePDFPageTextCatalog(session_factory, clock),
        index_recorder=create_asset_index_recorder(settings, session_factory),
    )
    embedding = EmbeddingIndexingService(
        assets=assets,
        blob_refs=blob_refs,
        resolver=resolver,
        provider=_embedding_provider(data_dir, settings),
        index=SQLiteVecSearchIndex(session_factory, clock, dimensions=settings.embedding_dimensions),
        manifest=manifest,
        clock=clock,
        text_catalog=SQLiteEmbeddingTextCatalog(session_factory),
        index_recorder=create_asset_index_recorder(settings, session_factory),
    )
    return WorkerDispatcher(
        jobs=jobs,
        media=media,
        clock=clock,
        worker_id=worker_id,
        ocr=ocr,
        embedding=embedding,
        telegram=TelegramJobHandlers(settings),
        storage_pipeline=StoragePipelineJobHandler(pipeline),
        sync_snapshot=SyncSnapshotJobHandler(session_factory),
    )


def _embedding_provider(data_dir: Path, settings: Settings) -> DisabledEmbeddingProvider | MockEmbeddingProvider | JinaOmniNanoGgufAdapter:
    provider = settings.embeddings_provider
    if provider == "mock":
        return MockEmbeddingProvider(dimensions=settings.embedding_dimensions)
    if provider == "jina":
        model_path = Path(settings.jina_model_path)
        if not model_path.is_absolute():
            model_path = (data_dir.parent / model_path).resolve()
        return JinaOmniNanoGgufAdapter(
            model_path=model_path,
            endpoint_url=settings.embedding_server_url,
            dimensions=settings.embedding_dimensions,
        )
    return DisabledEmbeddingProvider()


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
