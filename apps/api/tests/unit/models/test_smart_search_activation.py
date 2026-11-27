from __future__ import annotations

import asyncio
import math
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from bento.application.smart_search.activation import (
    MODEL_DOWNLOAD_MAX_ATTEMPTS,
    DownloadJobResult,
    InstallState,
    ModelDownloadRetryLater,
    SmartSearchNoSpaceError,
    SmartSearchStateConflictError,
)
from bento.domain.errors import SettingsSourceLockedError
from bento.domain.jobs import JobType
from bento.domain.smart_search import (
    InvalidModelSpecError,
    SmartSearchErrorCode,
    SmartSearchState,
    SmartSearchStatus,
    space_id_for,
)
from tests.fakes.model_host import BLOB_SIZE, MIRROR_URL, PRIMARY_URL, FakeModelHost, running_model_host
from tests.unit.models.model_fakes import (
    DEFAULT_MODEL_ID,
    LimitedSpaceStore,
    ServiceKit,
    files_under,
    make_kit,
    tiny_catalog,
)


@pytest.fixture
def host() -> Iterator[FakeModelHost]:
    with running_model_host() as server:
        yield server


def run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


async def wait_for_bytes(kit: ServiceKit, minimum: int = 1, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while (await kit.repository.load()).bytes_done < minimum:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("the download made no progress")
        await asyncio.sleep(0.005)


def models_root(kit: ServiceKit) -> Path:
    return kit.store.root


def test_activate_downloads_verifies_and_hands_over_at_starting(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)

    async def scenario() -> None:
        view = await kit.service.activate()
        assert view.status.state is SmartSearchState.DOWNLOADING
        assert view.status.space_id == kit.spec.space().id
        assert view.status.bytes_total == BLOB_SIZE
        assert view.dims == 768  # D9
        assert view.body()["model"]["download_host"] == "primary.bento.example"
        assert kit.switch.value == "managed"
        job = kit.jobs.jobs[-1]
        assert job.type is JobType.MODEL_DOWNLOAD
        assert job.max_attempts == MODEL_DOWNLOAD_MAX_ATTEMPTS
        assert job.payload == {
            "model_id": DEFAULT_MODEL_ID,
            "revision": kit.spec.revision,
            "space_id": kit.spec.space().id,
            "purpose": "activate",
        }

        assert await kit.run_last_job() is DownloadJobResult.STARTING

        status = await kit.repository.load()
        assert status.state is SmartSearchState.STARTING
        assert status.bytes_done == BLOB_SIZE
        weights = kit.store.path_for(kit.spec, kit.spec.weights)
        assert kit.hooks.started == [(kit.spec.space().id, weights)]
        assert weights.read_bytes() == host.blob
        assert (weights.parent / "LICENSE").read_text().startswith("Apache License")
        record = (await kit.repository.installs())[0]
        assert record.state is InstallState.INSTALLED
        assert record.bytes_done == BLOB_SIZE

    run(scenario())


def test_activate_validates_model_dims_lock_and_state(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)

    async def scenario() -> None:
        with pytest.raises(InvalidModelSpecError):
            await kit.service.activate("no-such-model")
        with pytest.raises(InvalidModelSpecError) as dims_error:
            await kit.service.activate(None, 300)
        assert dims_error.value.code == "invalid_model_spec"

        kit.switch.is_locked = True
        with pytest.raises(SettingsSourceLockedError):
            await kit.service.activate()
        kit.switch.is_locked = False

        view = await kit.service.activate(DEFAULT_MODEL_ID, 256)
        assert view.status.space_id == space_id_for(DEFAULT_MODEL_ID, kit.spec.revision, 256)
        with pytest.raises(SmartSearchStateConflictError) as conflict:
            await kit.service.activate()
        assert conflict.value.code == "smart_search_state_conflict"
        assert conflict.value.details == {"state": "downloading", "event": "activate"}

    run(scenario())


def test_free_space_precheck_refuses_without_changing_anything(tmp_path: Path, host: FakeModelHost) -> None:
    required = BLOB_SIZE + math.ceil(BLOB_SIZE * 0.10)
    kit = make_kit(tmp_path, host, free_bytes=required - 1)

    async def scenario() -> None:
        with pytest.raises(SmartSearchNoSpaceError) as error:
            await kit.service.activate()
        assert error.value.code == "smart_search_no_space"
        assert error.value.details == {"required_bytes": required, "free_bytes": required - 1}
        assert (await kit.repository.load()).state is SmartSearchState.OFF
        assert kit.jobs.jobs == []
        assert kit.switch.changes == []

        assert isinstance(kit.store, LimitedSpaceStore)
        kit.store.free = required
        assert (await kit.service.activate()).status.state is SmartSearchState.DOWNLOADING

    run(scenario())


def test_disk_filling_before_the_job_runs_is_an_error_space(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host, free_bytes=10 * BLOB_SIZE)

    async def scenario() -> None:
        await kit.service.activate()
        assert isinstance(kit.store, LimitedSpaceStore)
        kit.store.free = 1024

        assert await kit.run_last_job() is DownloadJobResult.FAILED
        status = await kit.repository.load()
        assert status.state is SmartSearchState.ERROR
        assert status.error_code is SmartSearchErrorCode.SPACE
        assert status.failed_step is SmartSearchState.DOWNLOADING

    run(scenario())


def test_pause_mid_download_then_resume_continues_from_the_part_file(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)
    host.behavior.trickle_delay = 0.004

    async def scenario() -> None:
        await kit.service.activate()
        job = asyncio.create_task(kit.run_last_job())
        await wait_for_bytes(kit)

        paused = await kit.service.pause()
        assert paused.status.state is SmartSearchState.PAUSED
        assert await asyncio.wait_for(job, 10) is DownloadJobResult.STOPPED

        status = await kit.repository.load()
        part = kit.store.part_path_for(kit.spec, kit.spec.weights)
        assert status.state is SmartSearchState.PAUSED
        assert 0 < status.bytes_done < BLOB_SIZE
        assert part.stat().st_size == status.bytes_done
        assert (await kit.repository.installs())[0].state is InstallState.PAUSED

        host.behavior.trickle_delay = 0.0
        resumed = await kit.service.resume()
        assert resumed.status.state is SmartSearchState.DOWNLOADING
        assert resumed.status.bytes_done == status.bytes_done
        assert len(kit.jobs.jobs) == 2

        assert await kit.run_last_job() is DownloadJobResult.STARTING
        assert host.requests_for(PRIMARY_URL)[-1].range == f"bytes={status.bytes_done}-"
        assert (await kit.repository.load()).state is SmartSearchState.STARTING

    run(scenario())


def test_a_job_queued_before_a_pause_does_nothing(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)

    async def scenario() -> None:
        await kit.service.activate()
        await kit.service.pause()

        assert await kit.run_last_job() is DownloadJobResult.SKIPPED
        assert host.requests == []

    run(scenario())


def test_resume_after_a_kill_picks_up_the_partial_file(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host, retry_delays=())
    host.behavior.drop_at = 1024 * 1024
    host.fail_primary()  # one URL in play keeps the request log simple

    async def scenario() -> None:
        await kit.service.activate()
        with pytest.raises(ModelDownloadRetryLater):
            await kit.run_last_job()

        status = await kit.repository.load()
        assert status.state is SmartSearchState.DOWNLOADING
        assert status.waiting_network is True
        assert status.bytes_done == 1024 * 1024

        # The worker process dies and a new one (new service, same disk and database) retries the job.
        reborn = make_kit(tmp_path, host)
        reborn.service.repository = kit.repository  # type: ignore[misc]
        assert await reborn.service.run_download_job(kit.jobs.last_payload(), final_attempt=False) is (
            DownloadJobResult.STARTING
        )
        final = await kit.repository.load()
        assert final.state is SmartSearchState.STARTING
        assert final.waiting_network is False
        assert host.requests_for(MIRROR_URL)[-1].range == f"bytes={1024 * 1024}-"

    run(scenario())


def test_a_drop_inside_the_job_is_retried_and_clears_waiting_network(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host, retry_delays=(0.0, 0.0))
    host.behavior.drop_at = 512 * 1024

    async def scenario() -> None:
        await kit.service.activate()

        assert await kit.run_last_job() is DownloadJobResult.STARTING
        status = await kit.repository.load()
        assert status.state is SmartSearchState.STARTING
        assert status.waiting_network is False

    run(scenario())


def test_drops_with_progress_in_between_do_not_use_up_the_in_job_waits(tmp_path: Path, host: FakeModelHost) -> None:
    # One in-job wait, four separate drops: each attempt gets bytes before it drops, so the job never gives up.
    kit = make_kit(tmp_path, host, retry_delays=(0.0,))
    host.fail_primary()
    host.behavior.drop_at = 512 * 1024
    host.behavior.next_drops = [1024 * 1024, 1536 * 1024, 2048 * 1024]
    host.behavior.reset = True

    async def scenario() -> None:
        await kit.service.activate()

        assert await kit.run_last_job() is DownloadJobResult.STARTING
        requests = host.requests_for(MIRROR_URL)
        assert len(requests) == 5
        assert requests[0].range is None
        starts = [int(request.range.removeprefix("bytes=").rstrip("-")) for request in requests[1:] if request.range]
        assert len(starts) == 4 and starts == sorted(set(starts))  # every retry resumed further on
        assert (await kit.repository.load()).waiting_network is False

    run(scenario())


def test_an_outage_with_no_progress_still_ends_the_in_job_waits(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host, retry_delays=(0.0, 0.0))
    host.fail_primary()
    host.behavior.drop_at = 512 * 1024
    host.behavior.drop_once = False  # the link is down from this byte on: no progress after the first attempt

    async def scenario() -> None:
        await kit.service.activate()

        with pytest.raises(ModelDownloadRetryLater):
            await kit.run_last_job()
        # One request per wait plus the first: the waits are not reset when no byte arrives.
        assert len(host.requests_for(MIRROR_URL)) == 3
        status = await kit.repository.load()
        assert status.waiting_network is True
        assert status.bytes_done == 512 * 1024

    run(scenario())


def test_the_last_attempt_without_network_is_error_download(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host, retry_delays=(), rewrite_url=lambda url: "http://127.0.0.1:9/unreachable")

    async def scenario() -> None:
        await kit.service.activate()

        assert await kit.run_last_job(final_attempt=True) is DownloadJobResult.FAILED
        status = await kit.repository.load()
        assert status.state is SmartSearchState.ERROR
        assert status.error_code is SmartSearchErrorCode.DOWNLOAD
        assert status.failed_step is SmartSearchState.DOWNLOADING

        retried = await kit.service.retry()
        assert retried.status.state is SmartSearchState.DOWNLOADING
        assert len(kit.jobs.jobs) == 2

    run(scenario())


def test_mirror_fallback_when_the_primary_is_gone(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)
    host.fail_primary()

    async def scenario() -> None:
        await kit.service.activate()

        assert await kit.run_last_job() is DownloadJobResult.STARTING
        assert host.requests_for(PRIMARY_URL)[0].status == 404
        assert host.requests_for(MIRROR_URL)[0].status == 200

    run(scenario())


def test_checksum_mismatch_deletes_the_part_and_retry_restarts_from_zero(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)
    host.behavior.wrong_body = True

    async def scenario() -> None:
        await kit.service.activate()

        assert await kit.run_last_job() is DownloadJobResult.FAILED
        status = await kit.repository.load()
        assert status.state is SmartSearchState.ERROR
        assert status.error_code is SmartSearchErrorCode.CHECKSUM
        assert status.failed_step is SmartSearchState.VERIFYING
        assert files_under(models_root(kit)) == []

        host.behavior.wrong_body = False
        retried = await kit.service.retry()
        assert retried.status.state is SmartSearchState.DOWNLOADING
        assert retried.status.bytes_done == 0
        assert await kit.run_last_job() is DownloadJobResult.STARTING

    run(scenario())


def test_cancel_mid_download_leaves_nothing_behind(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)
    host.behavior.trickle_delay = 0.004

    async def scenario() -> None:
        await kit.service.activate()
        job = asyncio.create_task(kit.run_last_job())
        await wait_for_bytes(kit)

        cancelled = await kit.service.cancel()
        assert cancelled.status == SmartSearchStatus()
        assert await asyncio.wait_for(job, 10) is DownloadJobResult.STOPPED

        assert files_under(models_root(kit)) == []
        assert await kit.repository.installs() == ()
        assert kit.switch.value == "disabled"
        assert kit.hooks.stopped_spaces == [kit.spec.space().id]

    run(scenario())


def test_cancel_and_remove_are_state_checked(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)

    async def scenario() -> None:
        for action in (kit.service.cancel, kit.service.remove, kit.service.pause, kit.service.resume, kit.service.retry):
            with pytest.raises(SmartSearchStateConflictError) as error:
                await action()
            assert error.value.details["state"] == "off"

    run(scenario())


def test_remove_frees_the_model_bytes(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)

    async def scenario() -> None:
        await kit.service.activate()
        await kit.run_last_job()
        used = sum(path.stat().st_size for path in files_under(models_root(kit)))
        assert used >= BLOB_SIZE

        view, freed = await kit.service.remove()

        assert view.status.state is SmartSearchState.OFF
        assert freed == used
        assert files_under(models_root(kit)) == []
        assert kit.switch.value == "disabled"

    run(scenario())


def test_runtime_owner_drives_starting_to_ready_and_runtime_errors_retry_at_starting(
    tmp_path: Path, host: FakeModelHost
) -> None:
    kit = make_kit(tmp_path, host)

    async def scenario() -> None:
        await kit.service.activate()
        await kit.run_last_job()
        space_id = kit.spec.space().id

        assert (await kit.service.runtime_ready(space_id)).state is SmartSearchState.INDEXING  # type: ignore[union-attr]
        assert await kit.service.index_progress(space_id, 5, 20)
        view = await kit.service.status()
        assert view.body()["indexing"] == {"done": 5, "total": 20}
        assert view.status.search_available is True
        assert (await kit.service.indexed(space_id)).state is SmartSearchState.READY  # type: ignore[union-attr]
        assert await kit.service.runtime_ready("other@abc1234/512") is None

        failed = await kit.service.runtime_failed(space_id)
        assert failed is not None and failed.failed_step is SmartSearchState.STARTING
        retried = await kit.service.retry()
        assert retried.status.state is SmartSearchState.STARTING
        assert len(kit.hooks.started) == 2

    run(scenario())


def test_update_downloads_the_new_revision_without_leaving_ready(tmp_path: Path, host: FakeModelHost) -> None:
    catalog = tiny_catalog(host.blob, revision="bbbbbbb2")
    kit = make_kit(tmp_path, host, catalog=catalog)
    old_space = space_id_for(DEFAULT_MODEL_ID, "aaaaaaa1", 512)
    kit.repository.status = SmartSearchStatus(state=SmartSearchState.READY, space_id=old_space)

    async def scenario() -> None:
        view = await kit.service.status()
        assert view.body()["update_available"] == {"revision": "bbbbbbb2", "size_bytes": BLOB_SIZE, "progress": None}

        await kit.service.update()
        assert kit.jobs.last_payload()["purpose"] == "update"
        assert kit.jobs.last_payload()["space_id"] == space_id_for(DEFAULT_MODEL_ID, "bbbbbbb2", 512)
        await kit.service.update()  # idempotent while it downloads
        assert len(kit.jobs.jobs) == 1

        assert await kit.run_last_job() is DownloadJobResult.UPDATE_READY
        assert (await kit.repository.load()).state is SmartSearchState.READY
        assert kit.hooks.updates == [space_id_for(DEFAULT_MODEL_ID, "bbbbbbb2", 512)]
        record = (await kit.repository.installs())[0]
        assert (record.revision, record.state) == ("bbbbbbb2", InstallState.INSTALLED)

        view, freed = await kit.service.remove()
        assert freed >= BLOB_SIZE
        assert files_under(models_root(kit)) == []

    run(scenario())


def test_update_is_refused_when_nothing_newer_or_not_ready(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)

    async def scenario() -> None:
        with pytest.raises(SmartSearchStateConflictError) as error:
            await kit.service.update()
        assert error.value.details == {"state": "off", "event": "update"}

        kit.repository.status = replace(SmartSearchStatus(), state=SmartSearchState.READY, space_id=kit.spec.space().id)
        assert (await kit.service.status()).update is None
        with pytest.raises(SmartSearchStateConflictError):
            await kit.service.update()

    run(scenario())


def test_an_existing_512_install_keeps_its_space_while_new_activations_use_768(
    tmp_path: Path, host: FakeModelHost
) -> None:
    """D9 moved the default to 768 (2026-11-27). Another dimension is another space: a device activated at 512
    keeps serving its 512 space (no table is rewritten); only a fresh activation gets 768."""
    kit = make_kit(tmp_path, host)
    old_space = kit.spec.space(512).id
    kit.repository.status = SmartSearchStatus(state=SmartSearchState.READY, space_id=old_space)

    async def scenario() -> None:
        view = await kit.service.status()
        assert view.dims == 512 and view.status.space_id == old_space
        assert kit.jobs.jobs == []  # nothing is queued just because the default changed

        await kit.service.remove()
        fresh = await kit.service.activate()
        assert fresh.dims == 768 and fresh.status.space_id == kit.spec.space().id != old_space

    run(scenario())
