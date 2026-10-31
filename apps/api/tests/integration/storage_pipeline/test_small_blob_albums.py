"""Thumbnails and previews that wait together are uploaded in albums of up to 10 (`store_many`)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from bento.adapters.media import SQLiteThumbnailCatalog
from bento.application.ingestion import UploadedAssetFile
from bento.application.media import MediaProcessingService
from bento.domain.errors import StorageUnavailableError, TelegramFloodWaitError
from bento.domain.jobs import JobStatus, JobType
from bento.domain.storage import BlobKind, StorageBackend
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import BlobRefModel, JobModel, ThumbnailModel
from tests.integration.storage_pipeline.support import (
    FakeMediaGenerator,
    JobRunner,
    RemoteSwitch,
    migrated_data_dir,
    pipeline_for,
    run,
    vault_remote_store,
)


class ThumbnailOnlyGenerator(FakeMediaGenerator):
    async def generate(self, asset, source_path):  # type: ignore[no-untyped-def]
        return tuple(item for item in await super().generate(asset, source_path) if item.kind == BlobKind.THUMBNAIL)


async def _library(tmp_path: Path, count: int, *, generator: FakeMediaGenerator | None = None):  # type: ignore[no-untyped-def]
    store = await vault_remote_store(tmp_path)
    components = pipeline_for(migrated_data_dir(tmp_path), RemoteSwitch(store))
    media = MediaProcessingService(
        assets=components.assets,
        blob_refs=components.blob_refs,
        thumbnails=SQLiteThumbnailCatalog(components.session_factory, components.clock, components.blob_refs),
        blob_store=components.local_store,
        materializer=components.materializer,
        generator=generator or FakeMediaGenerator(tmp_path / "generated"),
        manifest=components.manifest,
        clock=components.clock,
        remote_uploads=components.pipeline,
    )
    assets = []
    for index in range(count):
        source = tmp_path / "incoming" / f"foto-{index}.jpg"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"\xff\xd8\xff" + f"jpeg {index}".encode() * 50)
        result = await components.ingestion.upload_file(UploadedAssetFile(source_path=source, original_filename=source.name))
        await media.process_asset_media(result.asset.id)
        assets.append(result.asset)
    # Thumbnails were generated above; drain their (no-op here) jobs so only remote uploads remain.
    await JobRunner(components).run_all(types={JobType.THUMBNAIL.value})
    return store, components, assets


def _upload_jobs(components) -> list[JobModel]:  # type: ignore[no-untyped-def]
    with session_scope(components.session_factory) as session:
        statement = select(JobModel).where(JobModel.type == JobType.REMOTE_UPLOAD.value).order_by(JobModel.created_at)
        return list(session.scalars(statement))


def _derived(jobs: list[JobModel]) -> list[JobModel]:
    return [job for job in jobs if job.payload_json["kind"] != "original"]


def test_pending_thumbnails_and_previews_share_albums_of_ten(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, components, assets = await _library(tmp_path, 6)
        assert len(_derived(_upload_jobs(components))) == 12

        processed = await JobRunner(components).run_all()

        # 6 originals one by one, then the 12 derived blobs in two album requests (10 + 2).
        assert processed == 6 + 2
        assert [len(album) for album in store.albums] == [10, 2]
        assert all(kind in {BlobKind.THUMBNAIL, BlobKind.PREVIEW} for album in store.albums for kind in album)
        assert {job.status for job in _upload_jobs(components)} == {JobStatus.SUCCEEDED.value}
        with session_scope(components.session_factory) as session:
            assert session.scalars(select(BlobRefModel).where(BlobRefModel.backend == "local")).all() == []
            for asset in assets:
                thumbnail = session.scalar(select(ThumbnailModel).where(ThumbnailModel.asset_id == asset.id))
                assert session.get(BlobRefModel, thumbnail.blob_ref_id).backend == StorageBackend.TELEGRAM.value
                assert session.scalars(select(JobModel).where(JobModel.locked_by.is_not(None))).all() == []

    run(scenario())


def test_a_single_pending_small_blob_uses_store(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, components, [asset] = await _library(tmp_path, 1, generator=ThumbnailOnlyGenerator(tmp_path / "generated"))

        await JobRunner(components).run_all()

        assert store.albums == []
        assert [ref.kind for ref in store.stored] == [BlobKind.ORIGINAL, BlobKind.THUMBNAIL]
        thumbnail = await components.blob_refs.latest_for_asset(asset.id, BlobKind.THUMBNAIL)
        assert thumbnail is not None and thumbnail.backend == StorageBackend.TELEGRAM

    run(scenario())


def test_a_failed_album_falls_back_to_one_upload_per_blob(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, components, _ = await _library(tmp_path, 2)
        await JobRunner(components).run_all(types={"remote_upload"}, max_jobs=2)  # the originals
        store.album_failures.append(RuntimeError("album rejected"))
        store.failures.extend([None, ConnectionError("network vanished")])  # the first companion fails on its own

        assert await JobRunner(components).run_all(max_jobs=1) == 1

        assert store.albums == []
        derived = _derived(_upload_jobs(components))
        statuses = sorted(job.status for job in derived)
        assert statuses == [JobStatus.RETRYING.value] + [JobStatus.SUCCEEDED.value] * 3
        [retrying] = [job for job in derived if job.status == JobStatus.RETRYING.value]
        assert retrying.attempts == 1 and retrying.locked_by is None and "network vanished" in (retrying.error or "")
        assert retrying.run_after is not None

    run(scenario())


def test_a_flood_wait_reschedules_the_whole_album(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, components, _ = await _library(tmp_path, 2)
        await JobRunner(components).run_all(types={"remote_upload"}, max_jobs=2)
        store.album_failures.append(TelegramFloodWaitError(600))

        await JobRunner(components).run_all()

        derived = _derived(_upload_jobs(components))
        done = [job for job in derived if job.status == JobStatus.SUCCEEDED.value]
        waiting = [job for job in derived if job.status == JobStatus.QUEUED.value]
        assert len(done) == 4 and len(waiting) == 4
        assert {job.payload_json["blob_id"] for job in done} == {job.payload_json["blob_id"] for job in waiting}
        assert all(job.run_after is not None and job.attempts == 0 for job in waiting)
        [item] = (await components.activity.current()).attention
        assert item.kind.value == "flood_wait"

    run(scenario())
