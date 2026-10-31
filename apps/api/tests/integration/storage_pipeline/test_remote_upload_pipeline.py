from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from bento.adapters.media import SQLiteThumbnailCatalog
from bento.application.ingestion import UploadedAssetFile
from bento.application.jobs import JobsUseCases
from bento.application.media import MediaProcessingService
from bento.application.storage_pipeline import UploadOutcome
from bento.domain.errors import StorageUnavailableError, TelegramFloodWaitError, VaultLockedError
from bento.domain.jobs import JobStatus, JobType
from bento.domain.storage import BlobKind, StorageBackend
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import BlobRefModel, CacheEntryModel, JobModel, ThumbnailModel
from tests.integration.storage_pipeline.support import (
    FakeMediaGenerator,
    JobRunner,
    RemoteSwitch,
    migrated_data_dir,
    pipeline_for,
    run,
    vault_remote_store,
)


def _jobs(components, job_type: JobType = JobType.REMOTE_UPLOAD) -> list[JobModel]:
    with session_scope(components.session_factory) as session:
        return list(session.scalars(select(JobModel).where(JobModel.type == job_type.value).order_by(JobModel.created_at)))


async def _ingest(components, tmp_path: Path, name: str, content: bytes):
    source = tmp_path / "incoming" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(content)
    return await components.ingestion.upload_file(UploadedAssetFile(source_path=source, original_filename=name))


def test_ingestion_is_local_first_and_the_job_uploads_encrypted_parts(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = await vault_remote_store(tmp_path, part_size=8192)
        components = pipeline_for(migrated_data_dir(tmp_path), RemoteSwitch(store))
        content = b"factura confidencial " * 2000

        result = await _ingest(components, tmp_path, "factura.txt", content)

        assert result.blob_ref is not None and result.blob_ref.backend == StorageBackend.LOCAL
        assert store.stored == []
        queued = _jobs(components)
        assert [(job.status, job.payload_json["blob_id"], job.priority) for job in queued] == [
            ("queued", result.blob_ref.id, 2)
        ]
        local_path = components.local_resolver.resolve(result.blob_ref)

        assert await JobRunner(components).run_all() == 1

        remote = await components.blob_refs.latest_for_asset(result.asset.id, BlobKind.ORIGINAL)
        assert remote is not None and remote.backend == StorageBackend.TELEGRAM
        assert remote.encryption.format_version == 2 and len(remote.parts) > 1
        assert remote.sha256 == result.asset.metadata.sha256
        assert (await components.pipeline.upload(result.blob_ref.id)).outcome == UploadOutcome.MISSING
        with session_scope(components.session_factory) as session:
            assert session.get(BlobRefModel, result.blob_ref.id) is None
            entry = session.get(CacheEntryModel, remote.id)
            assert entry is not None and Path(entry.path) == local_path.resolve()
        assert local_path.read_bytes() == content
        for document in (path for path in store.cloud_dir.rglob("*") if path.is_file()):
            assert b"factura confidencial" not in document.read_bytes()
        assert await components.content.materialize_original(result.asset.id) == local_path.resolve()
        assert store.downloads == []

    run(scenario())


def test_vault_ready_backfill_enqueues_every_local_only_blob_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        switch = RemoteSwitch(None)
        components = pipeline_for(migrated_data_dir(tmp_path), switch)
        first = await _ingest(components, tmp_path, "a.txt", b"alpha")
        second = await _ingest(components, tmp_path, "b.txt", b"beta")
        trashed = await _ingest(components, tmp_path, "c.txt", b"gamma")
        await components.files.delete_asset(trashed.asset.id)

        assert _jobs(components) == []
        assert await components.pipeline.backfill() == 0

        switch.store = await vault_remote_store(tmp_path)
        assert await components.pipeline.backfill() == 2
        assert await components.pipeline.backfill() == 0
        assert {job.payload_json["blob_id"] for job in _jobs(components)} == {
            first.blob_ref.id,
            second.blob_ref.id,
        }

        await JobRunner(components).run_all()
        for result in (first, second):
            ref = await components.blob_refs.latest_for_asset(result.asset.id, BlobKind.ORIGINAL)
            assert ref.backend == StorageBackend.TELEGRAM
        trashed_ref = await components.blob_refs.latest_for_asset(trashed.asset.id, BlobKind.ORIGINAL)
        assert trashed_ref.backend == StorageBackend.LOCAL

    run(scenario())


def test_vault_not_ready_at_run_time_skips_and_backfill_retries(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = await vault_remote_store(tmp_path)
        switch = RemoteSwitch(store)
        components = pipeline_for(migrated_data_dir(tmp_path), switch)
        result = await _ingest(components, tmp_path, "a.txt", b"alpha")

        switch.store = None
        assert await components.pipeline.upload(result.blob_ref.id) == _outcome(UploadOutcome.NOT_READY)
        store.failures.append(VaultLockedError())
        switch.store = store
        assert await components.pipeline.upload(result.blob_ref.id) == _outcome(UploadOutcome.NOT_READY)
        assert await components.pipeline.upload("local_original_" + "0" * 64) == _outcome(UploadOutcome.MISSING)

    run(scenario())


def test_originals_upload_before_thumbnails_and_thumbnail_rows_follow_the_remote_ref(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = await vault_remote_store(tmp_path)
        components = pipeline_for(migrated_data_dir(tmp_path), RemoteSwitch(store))
        media = MediaProcessingService(
            assets=components.assets,
            blob_refs=components.blob_refs,
            thumbnails=SQLiteThumbnailCatalog(components.session_factory, components.clock, components.blob_refs),
            blob_store=components.local_store,
            materializer=components.materializer,
            generator=FakeMediaGenerator(tmp_path / "generated"),
            manifest=components.manifest,
            clock=components.clock,
            remote_uploads=components.pipeline,
        )
        result = await _ingest(components, tmp_path, "playa.jpg", b"\xff\xd8\xff" + b"jpeg" * 100)
        await media.process_asset_media(result.asset.id)

        kinds = [job.payload_json["kind"] for job in _jobs(components)]
        assert sorted(kinds) == ["original", "preview", "thumbnail"]
        await JobRunner(components).run_all()

        assert store.stored[0].kind == BlobKind.ORIGINAL
        assert {ref.kind for ref in store.stored} == {BlobKind.ORIGINAL, BlobKind.THUMBNAIL, BlobKind.PREVIEW}
        with session_scope(components.session_factory) as session:
            assert session.scalars(select(BlobRefModel).where(BlobRefModel.backend == "local")).all() == []
            thumbnail = session.scalar(select(ThumbnailModel).where(ThumbnailModel.asset_id == result.asset.id))
            remote_thumb = session.get(BlobRefModel, thumbnail.blob_ref_id)
            assert remote_thumb.backend == "telegram" and remote_thumb.kind == "thumbnail"

    run(scenario())


def test_failures_retry_with_backoff_and_exhausted_uploads_stay_retryable(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = await vault_remote_store(tmp_path)
        components = pipeline_for(migrated_data_dir(tmp_path), RemoteSwitch(store))
        result = await _ingest(components, tmp_path, "a.txt", b"alpha")
        store.failures.extend([RuntimeError("upload rejected")] * 2)

        await JobRunner(components).run_all()
        [job] = _jobs(components)
        assert job.status == JobStatus.RETRYING.value and job.attempts == 1
        assert job.run_after is not None

        # Jump to the last attempt: the failure is parked as a FAILED job the user can retry.
        await components.jobs.save(
            replace(await components.jobs.get(job.id), attempts=job.max_attempts - 1, run_after=None)
        )
        await JobRunner(components).run_all()
        jobs = {item.id: item for item in _jobs(components)}
        assert jobs[job.id].status == JobStatus.SUCCEEDED.value
        [parked] = [item for item in jobs.values() if item.status == JobStatus.FAILED.value]
        assert parked.attempts == 0 and parked.error
        activity = await components.activity.current()
        assert [(item.kind.value, item.params["job_id"], item.action.value) for item in activity.attention] == [
            ("upload_failed", parked.id, "retry")
        ]
        assert activity.attention[0].title_key == "activity.attention.upload_failed"
        assert await components.pipeline.backfill() == 0

        await JobsUseCases(jobs=components.jobs, clock=components.clock).retry_failed_job(parked.id)
        await JobRunner(components).run_all()
        ref = await components.blob_refs.latest_for_asset(result.asset.id, BlobKind.ORIGINAL)
        assert ref.backend == StorageBackend.TELEGRAM
        assert (await components.activity.current()).attention == ()

    run(scenario())


def test_offline_uploads_wait_for_the_network_without_consuming_attempts(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = await vault_remote_store(tmp_path)
        components = pipeline_for(migrated_data_dir(tmp_path), RemoteSwitch(store))
        result = await _ingest(components, tmp_path, "a.txt", b"alpha")
        store.failures.extend([StorageUnavailableError("telegram")] * 3)

        for _ in range(3):
            await JobRunner(components).run_all()
            waiting = [job for job in _jobs(components) if job.status in {JobStatus.QUEUED.value, JobStatus.RETRYING.value}]
            assert waiting and all(job.attempts == 0 for job in waiting)
            assert all(job.run_after is not None for job in waiting)
            for job in waiting:
                await components.jobs.save(replace(await components.jobs.get(job.id), run_after=None))
        assert not [job for job in _jobs(components) if job.status == JobStatus.FAILED.value]

        await JobRunner(components).run_all()
        ref = await components.blob_refs.latest_for_asset(result.asset.id, BlobKind.ORIGINAL)
        assert ref.backend == StorageBackend.TELEGRAM

    run(scenario())


def test_flood_wait_reschedules_without_consuming_an_attempt(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = await vault_remote_store(tmp_path)
        components = pipeline_for(migrated_data_dir(tmp_path), RemoteSwitch(store))
        await _ingest(components, tmp_path, "a.txt", b"alpha")
        store.failures.append(TelegramFloodWaitError(600))
        before = datetime.now(UTC)

        await JobRunner(components).run_all()

        first, rescheduled = _jobs(components)
        assert first.status == JobStatus.SUCCEEDED.value
        assert rescheduled.status == JobStatus.QUEUED.value and rescheduled.attempts == 0
        run_after = rescheduled.run_after.replace(tzinfo=UTC)
        assert before + timedelta(seconds=600) <= run_after <= datetime.now(UTC) + timedelta(seconds=606)
        assert rescheduled.payload_json["retry_after_seconds"] == 600
        activity = await components.activity.current()
        assert activity.summary.value == "attention"
        [item] = activity.attention
        assert item.kind.value == "flood_wait" and item.title_key == "activity.attention.flood_wait"
        assert 595 <= item.params["retry_after_seconds"] <= 606
        assert await JobRunner(components).run_all() == 0  # not due yet

    run(scenario())


def test_long_waits_reported_by_the_telegram_client_reach_activity(tmp_path: Path) -> None:
    from bento.adapters.sync.store import SQLiteSyncStateStore
    from bento.application.account import FLOOD_WAIT_UNTIL_KEY

    async def scenario() -> None:
        components = pipeline_for(migrated_data_dir(tmp_path), RemoteSwitch(None))
        state = SQLiteSyncStateStore(components.session_factory)

        await state.set_value(FLOOD_WAIT_UNTIL_KEY, (datetime.now(UTC) + timedelta(minutes=12)).isoformat())
        [item] = (await components.activity.current()).attention
        assert item.kind.value == "flood_wait" and item.params["retry_after_minutes"] == 12
        assert 710 <= item.params["retry_after_seconds"] <= 720

        await state.set_value(FLOOD_WAIT_UNTIL_KEY, (datetime.now(UTC) - timedelta(minutes=1)).isoformat())
        assert (await components.activity.current()).attention == ()
        await state.set_value(FLOOD_WAIT_UNTIL_KEY, "not a time")
        assert (await components.activity.current()).attention == ()

    run(scenario())


def test_trashed_assets_are_deferred_and_purged_refs_are_skipped(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = await vault_remote_store(tmp_path)
        components = pipeline_for(migrated_data_dir(tmp_path), RemoteSwitch(store))
        result = await _ingest(components, tmp_path, "a.txt", b"alpha")
        await components.files.delete_asset(result.asset.id)

        assert (await components.pipeline.upload(result.blob_ref.id)).outcome == UploadOutcome.DEFERRED
        await components.trash.purge((result.asset.id,))
        assert (await components.pipeline.upload(result.blob_ref.id)).outcome == UploadOutcome.MISSING
        assert store.stored == []

    run(scenario())


def _outcome(outcome: UploadOutcome):  # type: ignore[no-untyped-def]
    from bento.application.storage_pipeline import RemoteUploadResult

    return RemoteUploadResult(outcome)


def test_refs_purged_during_upload_leave_no_remote_parts(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = await vault_remote_store(tmp_path)
        components = pipeline_for(migrated_data_dir(tmp_path), RemoteSwitch(store))
        result = await _ingest(components, tmp_path, "a.txt", b"alpha")
        original_store = store.store

        async def store_then_purge(*args, **kwargs):  # type: ignore[no-untyped-def]
            remote = await original_store(*args, **kwargs)
            await components.files.delete_asset(result.asset.id)
            await components.trash.purge((result.asset.id,))
            return remote

        store.store = store_then_purge  # type: ignore[method-assign]
        outcome = await components.pipeline.upload(result.blob_ref.id)

        assert outcome.outcome == UploadOutcome.MISSING
        assert store.deleted == [store.stored[0].id]
        assert not any(store.remote_exists(part) for part in store.stored[0].parts)

    run(scenario())
