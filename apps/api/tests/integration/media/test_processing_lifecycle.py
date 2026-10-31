"""Asset provenance and processing lifecycle through the real worker dispatcher.

- Files from Telegram (Inbox, imports) never reach OCR or embeddings (Telegram API terms §1.5), whatever path
  queues the work; filename search keeps finding them.
- Every asset ends in a terminal processing state once nothing is left to do, so the uploader agrees with peers.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, replace
from pathlib import Path

from sqlalchemy import func, select

from bento.adapters.embeddings import MockEmbeddingProvider
from bento.adapters.jobs import SQLiteJobQueue
from bento.adapters.manifest import SQLiteManifestJournal
from bento.adapters.media import BlobSourceMaterializer, LocalBlobPathResolver, SQLiteBlobRefCatalog, SQLiteThumbnailCatalog
from bento.adapters.ocr import MockOCRAdapter
from bento.adapters.repositories import SQLiteAssetRepository, SQLiteFolderRepository
from bento.adapters.search.composite import CompositeSearchIndex
from bento.adapters.search.sqlite_fts import SQLiteFTSSearchIndex
from bento.adapters.search.sqlite_vec import SQLiteVecSearchIndex
from bento.adapters.storage.local_blob_store import LocalBlobStoreAdapter
from bento.application.indexing import OCRIndexingService
from bento.application.indexing.embedding import EmbeddingIndexingService
from bento.application.indexing.reindex import ReindexService
from bento.application.media import MediaProcessingService, ProcessingCompletionService
from bento.application.upload import UploadAssetCommand, UploadAssetUseCase
from bento.domain.assets import Asset, AssetOrigin, ProcessingState
from bento.domain.jobs import JobStatus, JobType
from bento.domain.search import SearchQuery
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AssetEmbeddingModel, JobModel, OCRBlockModel
from bento.interfaces.worker.dispatch import WorkerDispatcher
from tests.integration.db.support import FixedClock, make_asset, migrated_session_factory
from tests.integration.storage_pipeline.support import FakeMediaGenerator

MIME = {"txt": "text/plain", "jpg": "image/jpeg", "pdf": "application/pdf"}


class FailingGenerator(FakeMediaGenerator):
    async def generate(self, asset, source_path):  # type: ignore[no-untyped-def]
        raise OSError("cannot identify image file")


@dataclass
class Worker:
    tmp_path: Path
    factory: object
    clock: FixedClock
    assets: SQLiteAssetRepository
    jobs: SQLiteJobQueue
    blob_refs: SQLiteBlobRefCatalog
    upload: UploadAssetUseCase
    dispatcher: WorkerDispatcher

    async def ingest(self, name: str, *, origin: AssetOrigin = AssetOrigin.DEVICE, ai: bool = False) -> Asset:
        source = self.tmp_path / "incoming" / name
        source.parent.mkdir(parents=True, exist_ok=True)
        content = f"{name} contents".encode()
        source.write_bytes(content)
        result = await self.upload.execute(
            UploadAssetCommand(
                source_ref=str(source),
                original_filename=name,
                mime_type=MIME[name.rsplit(".", 1)[-1]],
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                ocr_enabled=ai,
                embeddings_enabled=ai,
                origin=origin,
            )
        )
        assert result.blob_ref is not None
        await self.blob_refs.add(result.blob_ref)
        return result.asset

    async def state(self, asset_id: str) -> ProcessingState:
        asset = await self.assets.get(asset_id)
        assert asset is not None
        return asset.processing_state

    async def drain(self, *, limit: int = 50) -> int:
        processed = 0
        while processed < limit and await self.dispatcher.process_one():
            processed += 1
        return processed

    def job_types(self, asset_id: str) -> list[JobType]:
        with session_scope(self.factory) as session:  # type: ignore[arg-type]
            statement = select(JobModel.type).where(JobModel.asset_id == asset_id).order_by(JobModel.priority)
            return [JobType(value) for value in session.scalars(statement)]


def _worker(tmp_path: Path, *, generator: FakeMediaGenerator | None = None) -> Worker:
    factory = migrated_session_factory(tmp_path)
    clock = FixedClock()
    assets = SQLiteAssetRepository(factory)
    jobs = SQLiteJobQueue(factory, clock)
    blob_refs = SQLiteBlobRefCatalog(factory, clock)
    storage = LocalBlobStoreAdapter(tmp_path / "uploads")
    resolver = LocalBlobPathResolver(tmp_path / "uploads")
    manifest = SQLiteManifestJournal(factory, clock, tmp_path / "journal")
    media = MediaProcessingService(
        assets=assets,
        blob_refs=blob_refs,
        thumbnails=SQLiteThumbnailCatalog(factory, clock, blob_refs),
        blob_store=storage,
        materializer=BlobSourceMaterializer(blob_store=storage, local_resolver=resolver, temp_dir=tmp_path / "sources"),
        generator=generator or FakeMediaGenerator(tmp_path / "generated"),
        manifest=manifest,
        clock=clock,
    )
    ocr = OCRIndexingService(
        assets=assets,
        blob_refs=blob_refs,
        resolver=resolver,
        provider=MockOCRAdapter(default_text="Total factura panadería"),
        index=SQLiteFTSSearchIndex(factory, clock),
        manifest=manifest,
        clock=clock,
    )
    embedding = EmbeddingIndexingService(
        assets=assets,
        blob_refs=blob_refs,
        resolver=resolver,
        provider=MockEmbeddingProvider(dimensions=8),
        index=SQLiteVecSearchIndex(factory, clock, dimensions=8),
        manifest=manifest,
        clock=clock,
    )
    dispatcher = WorkerDispatcher(
        jobs=jobs,
        media=media,
        clock=clock,
        worker_id="worker-test",
        ocr=ocr,
        embedding=embedding,
        processing=ProcessingCompletionService(assets=assets, jobs=jobs, clock=clock),
        reindex=ReindexService(assets=assets, jobs=jobs, active=jobs, ocr_enabled=True, embeddings_enabled=True),
    )
    upload = UploadAssetUseCase(
        assets=assets,
        folders=SQLiteFolderRepository(factory),
        blob_store=storage,
        jobs=jobs,
        manifest=manifest,
        clock=clock,
    )
    return Worker(tmp_path, factory, clock, assets, jobs, blob_refs, upload, dispatcher)


def _ai_rows(worker: Worker) -> tuple[int, int]:
    with session_scope(worker.factory) as session:  # type: ignore[arg-type]
        ocr = session.scalar(select(func.count()).select_from(OCRBlockModel)) or 0
        vectors = session.scalar(select(func.count()).select_from(AssetEmbeddingModel)) or 0
        return int(ocr), int(vectors)


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


def test_a_text_file_with_ai_indexing_off_is_ready_right_away(tmp_path: Path) -> None:
    async def scenario() -> None:
        worker = _worker(tmp_path)

        note = await worker.ingest("nota.txt")

        assert note.processing_state == ProcessingState.INDEXED
        assert await worker.state(note.id) == ProcessingState.INDEXED
        assert worker.job_types(note.id) == []

    run(scenario())


def test_an_image_with_ai_indexing_off_is_ready_after_its_thumbnail(tmp_path: Path) -> None:
    async def scenario() -> None:
        worker = _worker(tmp_path)

        photo = await worker.ingest("playa.jpg")
        assert photo.processing_state == ProcessingState.THUMBNAIL_PENDING
        assert worker.job_types(photo.id) == [JobType.THUMBNAIL]

        assert await worker.drain() == 1
        assert await worker.state(photo.id) == ProcessingState.INDEXED

    run(scenario())


def test_assets_wait_for_their_last_processing_job(tmp_path: Path) -> None:
    async def scenario() -> None:
        worker = _worker(tmp_path)
        photo = await worker.ingest("recibo.jpg", ai=True)
        assert worker.job_types(photo.id) == [JobType.THUMBNAIL, JobType.OCR, JobType.EMBEDDING]

        assert await worker.drain(limit=1) == 1
        assert await worker.state(photo.id) == ProcessingState.THUMBNAIL_READY  # OCR and embeddings still queued
        await worker.drain()
        assert await worker.state(photo.id) == ProcessingState.INDEXED
        assert _ai_rows(worker) == (1, 1)

    run(scenario())


def test_telegram_files_never_reach_ocr_or_embeddings_but_stay_findable_by_name(tmp_path: Path) -> None:
    async def scenario() -> None:
        worker = _worker(tmp_path)

        photo = await worker.ingest("reenviada.jpg", origin=AssetOrigin.TELEGRAM_INBOX, ai=True)
        receipt = await worker.ingest("recibo-importado.pdf", origin=AssetOrigin.TELEGRAM_IMPORT, ai=True)

        assert worker.job_types(photo.id) == [JobType.THUMBNAIL]
        assert worker.job_types(receipt.id) == [JobType.THUMBNAIL]
        await worker.drain()
        assert await worker.state(photo.id) == ProcessingState.INDEXED
        assert await worker.state(receipt.id) == ProcessingState.INDEXED

        # Work queued some other way (older jobs, retries, a reindex) is refused when it runs.
        for asset in (photo, receipt):
            await worker.jobs.enqueue(type=JobType.OCR, priority=3, payload={"asset_id": asset.id}, asset_id=asset.id)
            await worker.jobs.enqueue(type=JobType.EMBEDDING, priority=4, payload={"asset_id": asset.id}, asset_id=asset.id)
        assert await worker.drain() == 4
        assert _ai_rows(worker) == (0, 0)
        assert await worker.state(photo.id) == ProcessingState.INDEXED

        search = CompositeSearchIndex(
            worker.factory, worker.clock, text_index=SQLiteFTSSearchIndex(worker.factory, worker.clock)  # type: ignore[arg-type]
        )
        results = await search.search(SearchQuery(text="reenviada"))
        assert [item.asset_id for item in results.items] == [photo.id]
        assert results.items[0].reason

    run(scenario())


def test_a_thumbnail_that_fails_for_good_settles_as_a_partial_failure(tmp_path: Path) -> None:
    async def scenario() -> None:
        worker = _worker(tmp_path, generator=FailingGenerator(tmp_path / "generated"))
        photo = await worker.ingest("rota.jpg")
        with session_scope(worker.factory) as session:  # type: ignore[arg-type]
            job = session.scalar(select(JobModel).where(JobModel.asset_id == photo.id))
            job.max_attempts = 2

        assert await worker.drain() == 1
        assert await worker.state(photo.id) == ProcessingState.THUMBNAIL_PENDING  # retrying: not settled yet
        with session_scope(worker.factory) as session:  # type: ignore[arg-type]
            job = session.scalar(select(JobModel).where(JobModel.asset_id == photo.id))
            assert job.status == JobStatus.RETRYING.value
            job.run_after = None
        assert await worker.drain() == 1
        assert await worker.state(photo.id) == ProcessingState.FAILED_PARTIAL

    run(scenario())


def test_reindex_queues_ai_work_only_for_this_devices_own_files(tmp_path: Path) -> None:
    async def scenario() -> None:
        worker = _worker(tmp_path)
        note = await worker.ingest("nota.txt")
        photo = await worker.ingest("playa.jpg")
        forwarded = await worker.ingest("reenviada.jpg", origin=AssetOrigin.TELEGRAM_INBOX)
        await worker.drain()
        from_peer = replace(make_asset("asset_peer", sha256="c" * 64), origin=None)
        trashed = make_asset("asset_trashed", sha256="d" * 64).mark_deleted(worker.clock.now())
        await worker.assets.add(from_peer)
        await worker.assets.add(trashed)

        reindex = await worker.jobs.enqueue(type=JobType.REINDEX, priority=4, payload={"scope": "all"})
        assert await worker.drain(limit=1) == 1
        assert (await worker.jobs.get(reindex.id)).status == JobStatus.SUCCEEDED  # type: ignore[union-attr]

        assert worker.job_types(note.id) == [JobType.OCR, JobType.EMBEDDING]
        assert worker.job_types(photo.id) == [JobType.THUMBNAIL, JobType.OCR, JobType.EMBEDDING]
        assert worker.job_types(forwarded.id) == [JobType.THUMBNAIL]
        assert worker.job_types(from_peer.id) == [] and worker.job_types(trashed.id) == []

        # Running it again while that work waits queues nothing twice.
        await worker.jobs.enqueue(type=JobType.REINDEX, priority=4, payload={"scope": "all"})
        assert await worker.drain(limit=1) == 1
        assert worker.job_types(note.id) == [JobType.OCR, JobType.EMBEDDING]

    run(scenario())
