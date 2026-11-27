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
from bento.application.indexing.text import TextExtractionService
from bento.application.media import MediaProcessingService, ProcessingCompletionService
from bento.application.smart_search.reembed import ReembedService
from bento.domain.settings_registry import embeddings_provider_choices
from bento.domain.smart_search import SmartSearchStatus, follows_smart_search_status, legacy_space_id
from bento.application.indexing import OCRIndexingService
from bento.application.ingestion import IndexingPolicy
from bento.infrastructure import services
from bento.infrastructure.db.clock import SystemClock
from bento.infrastructure.db.engine import create_app_session_factory
from bento.infrastructure.settings import Settings, get_settings, live_embeddings_provider, setting_locked
from bento.infrastructure.storage_pipeline import get_storage_pipeline
from bento.interfaces.worker.dispatch import WorkerDispatcher
from bento.interfaces.worker.handlers_models import build_model_download_handler
from bento.interfaces.worker.smart_search import (
    ReembedStatusObserver,
    RuntimeStatusRelay,
    SmartSearchSpaceJanitor,
    WorkerSmartSearchHooks,
)
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

    The worker also owns the embedding server. Unless `embeddings_provider` is pinned elsewhere (`custom`, `mock`,
    or `disabled` from the environment), the runtime supervisor runs from the start and follows the persisted
    smart search status every tick: activation starts the server and removal stops it, with no restart."""
    from bento.interfaces.worker.runtime import WorkerRuntime

    settings = get_settings()
    stop = stop_event or asyncio.Event()
    worker = WorkerRuntime(settings)
    worker.dispatcher  # noqa: B018 - built first: it attaches the status relay before the supervisor's first tick
    embedding_runtime = _worker_embedding(settings).runtime
    background: list[asyncio.Task[None]] = []
    if embedding_runtime is not None:
        background.append(asyncio.create_task(embedding_runtime.run(stop), name="bento-embedding-runtime"))
    # Cancel/remove run in the API process: once the status is `off`, drop the removed spaces' vectors here.
    background.append(asyncio.create_task(_space_janitor(settings).run(stop), name="bento-smart-search-janitor"))
    try:
        await worker.run(stop)
    finally:
        stop.set()
        await asyncio.gather(*background, return_exceptions=True)


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
    text_index = SQLiteFTSSearchIndex(session_factory, clock)
    pdf_pages = SQLitePDFPageTextCatalog(session_factory, clock)
    ocr = OCRIndexingService(
        assets=assets,
        blob_refs=blob_refs,
        resolver=resolver,
        provider=provider,
        index=text_index,
        manifest=manifest,
        clock=clock,
        pdf_renderer=services.get_pdf_page_renderer(settings, data_dir / "cache" / "ocr" / "pdf-pages"),
        pdf_pages=pdf_pages,
        index_recorder=create_asset_index_recorder(settings, session_factory),
        document_text=text_index,
    )
    ocr_on = str(settings.ocr_provider) != "disabled"
    embeddings_provider = live_embeddings_provider(settings)
    text = TextExtractionService(
        assets=assets,
        blob_refs=blob_refs,
        resolver=resolver,
        extractor=services.get_text_extractor(settings),
        store=text_index,
        ocr_enabled=lambda: ocr_on,
        embeddings_enabled=lambda: embeddings_provider() != "disabled",
        jobs=jobs,
        active=jobs,
        pdf_pages=pdf_pages,
        index_recorder=create_asset_index_recorder(settings, session_factory),
    )
    worker_embedding = _worker_embedding(settings)
    vec_index = SQLiteVecSearchIndex(session_factory, clock, dimensions=worker_embedding.dimensions)
    embedding = EmbeddingIndexingService(
        assets=assets,
        blob_refs=blob_refs,
        resolver=resolver,
        provider=worker_embedding.provider,
        index=vec_index,
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
        hooks=WorkerSmartSearchHooks(runtime=worker_embedding.hooks, spaces=vec_index),
    )
    activation = model_download.activation
    catalog, store = default_model_ports(settings)
    reembed = ReembedService(
        assets=assets,
        spaces=vec_index,
        vectors=vec_index,
        jobs=jobs,
        active=jobs,
        clock=clock,
        catalog=catalog,
        store=store,
        observer=ReembedStatusObserver(activation),
    )
    if worker_embedding.runtime is not None:
        runtime = worker_embedding.runtime
        runtime.attach_status(
            RuntimeStatusRelay(
                activation=activation,
                spaces=vec_index,
                reembed=reembed,
                load_status=activation.repository.load,
                served_model=runtime.current_model,
                jobs=jobs,
            )
        )
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
            spaces=vec_index,
            vectors=vec_index,
        ),
        reembed=reembed,
        text=text,
    )


def _space_janitor(settings: Settings) -> SmartSearchSpaceJanitor:
    clock = SystemClock()
    return SmartSearchSpaceJanitor(
        load_status=_status_loader(settings),
        spaces=SQLiteVecSearchIndex(create_app_session_factory(settings), clock),
    )


def worker_space_id(settings: Settings) -> str | None:
    """The embedding space this worker writes: the served (or configured) smart search space, the legacy space
    of pre-space providers (`mock`), or None when embeddings are off. Used for peer vectors in sync."""
    provider = _worker_embedding(settings).provider
    space = getattr(provider, "space", None)
    if space is not None:
        return str(space.id)
    if str(settings.embeddings_provider) == "mock":
        return legacy_space_id("mock", int(settings.embedding_dimensions))
    return None


_WORKER_EMBEDDINGS: dict[tuple[str, ...], WorkerEmbedding] = {}


def _worker_embedding(settings: Settings) -> WorkerEmbedding:
    """One provider + runtime per profile, shared by the dispatcher and the runtime supervisor.

    When the worker follows the smart search status (`follows_smart_search_status`), it is wired as `managed`
    even if it started with `disabled`: the supervisor and the provider then read the status, which is `off`
    until the person activates the feature (no server, embedding jobs are no-ops)."""
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
        provider = str(settings.embeddings_provider)
        catalog, store = None, None
        if follows_smart_search_status(
            provider,
            locked=setting_locked(settings, "embeddings_provider"),
            offered=embeddings_provider_choices(str(settings.platform)),
        ):
            catalog, store = default_model_ports(settings)
            if catalog is not None and store is not None:
                provider = "managed"
        cached = build_worker_embedding(
            settings, catalog=catalog, store=store, load_status=_status_loader(settings), provider=provider
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
