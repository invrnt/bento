from __future__ import annotations

import asyncio
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from bento.adapters.models.http_downloader import HttpModelDownloader
from bento.application.work_budget import WorkBudgetExceeded, check_safe_boundary, work_deadline
from bento.domain.smart_search import ModelFile, ModelFileRole
from bento.ports.models import DownloadResult
from tests.fakes.model_host import (
    BLOB_SIZE,
    MIRROR_URL,
    PRIMARY_URL,
    FakeModelHost,
    running_model_host,
    sha256_hex,
)
from tests.unit.models.model_fakes import TEST_BLOCK_BYTES, fake_host_downloader


@pytest.fixture
def host() -> Iterator[FakeModelHost]:
    with running_model_host() as server:
        yield server


def model_file(host: FakeModelHost, urls: tuple[str, ...] = (PRIMARY_URL, MIRROR_URL)) -> ModelFile:
    return ModelFile(
        name="tiny-model.gguf",
        role=ModelFileRole.WEIGHTS,
        urls=urls,
        size_bytes=len(host.blob),
        sha256=sha256_hex(host.blob),
    )


def part_path(tmp_path: Path) -> Path:
    return tmp_path / "models" / "m" / "abc1234" / "tiny-model.gguf.part"


def size_of(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def never_stop() -> bool:
    return False


def test_downloads_verifies_and_renames_atomically(tmp_path: Path, host: FakeModelHost) -> None:
    part = part_path(tmp_path)
    progress: list[tuple[int, int]] = []

    outcome = fake_host_downloader(host).download_blocking(
        model_file(host), part, lambda done, total: progress.append((done, total)), never_stop
    )

    final = part.with_name("tiny-model.gguf")
    assert outcome.result is DownloadResult.COMPLETED
    assert outcome.bytes_done == BLOB_SIZE
    assert outcome.url_used == PRIMARY_URL
    assert final.read_bytes() == host.blob
    assert not part.exists()
    assert not part.with_name(part.name + ".meta").exists()
    assert progress[-1] == (BLOB_SIZE, BLOB_SIZE)
    assert all(total == BLOB_SIZE for _, total in progress)


def test_sends_only_a_generic_user_agent(tmp_path: Path, host: FakeModelHost) -> None:
    fake_host_downloader(host).download_blocking(model_file(host), part_path(tmp_path), lambda *_: None, never_stop)

    request = host.requests_for(PRIMARY_URL)[0]
    assert request.user_agent == "Bento/0.0.0-test"
    assert request.authorization is None
    assert request.cookie is None
    assert request.range is None


def test_progress_is_rate_limited(tmp_path: Path, host: FakeModelHost) -> None:
    calls: list[int] = []
    clock = iter(float(i) * 0.01 for i in range(1_000_000))
    downloader = fake_host_downloader(host, progress_interval_seconds=0.25, monotonic=lambda: next(clock))

    downloader.download_blocking(model_file(host), part_path(tmp_path), lambda done, _: calls.append(done), never_stop)

    # 48 chunks of 64 KiB, one clock tick each: about one report per 25 ticks, plus the forced first/last ones.
    assert 2 <= len(calls) <= 6
    assert calls[-1] == BLOB_SIZE


def test_resume_after_a_kill_uses_range_and_keeps_the_hash(tmp_path: Path, host: FakeModelHost) -> None:
    part = part_path(tmp_path)
    file = model_file(host, urls=(PRIMARY_URL,))
    host.behavior.drop_at = 1024 * 1024

    first = fake_host_downloader(host).download_blocking(file, part, lambda *_: None, never_stop)

    assert first.result is DownloadResult.NETWORK
    assert first.bytes_done == 1024 * 1024
    assert part.stat().st_size == 1024 * 1024

    # A new process (fresh downloader) picks up the same `.part`.
    second = fake_host_downloader(host).download_blocking(file, part, lambda *_: None, never_stop)

    assert second.result is DownloadResult.COMPLETED
    assert part.with_name("tiny-model.gguf").read_bytes() == host.blob
    resumed = host.requests_for(PRIMARY_URL)[-1]
    assert resumed.range == f"bytes={1024 * 1024}-"
    assert resumed.if_range == '"tiny-v1"'
    assert resumed.status == 206


def test_a_changed_etag_restarts_from_zero(tmp_path: Path, host: FakeModelHost) -> None:
    part = part_path(tmp_path)
    file = model_file(host, urls=(PRIMARY_URL,))
    host.behavior.drop_at = 512 * 1024
    fake_host_downloader(host).download_blocking(file, part, lambda *_: None, never_stop)
    host.behavior.etag = '"tiny-v2"'

    outcome = fake_host_downloader(host).download_blocking(file, part, lambda *_: None, never_stop)

    assert outcome.result is DownloadResult.COMPLETED
    assert host.requests_for(PRIMARY_URL)[-1].status == 200
    assert part.with_name("tiny-model.gguf").read_bytes() == host.blob


def test_a_200_when_206_was_asked_restarts_from_zero(tmp_path: Path, host: FakeModelHost) -> None:
    part = part_path(tmp_path)
    file = model_file(host, urls=(PRIMARY_URL,))
    host.behavior.drop_at = 700 * 1024
    fake_host_downloader(host).download_blocking(file, part, lambda *_: None, never_stop)
    host.behavior.ignore_range = True

    outcome = fake_host_downloader(host).download_blocking(file, part, lambda *_: None, never_stop)

    last = host.requests_for(PRIMARY_URL)[-1]
    assert last.range is not None and last.status == 200
    assert outcome.result is DownloadResult.COMPLETED
    assert part.with_name("tiny-model.gguf").read_bytes() == host.blob


def test_falls_back_to_the_mirror_when_the_primary_is_missing(tmp_path: Path, host: FakeModelHost) -> None:
    host.fail_primary()

    outcome = fake_host_downloader(host).download_blocking(
        model_file(host), part_path(tmp_path), lambda *_: None, never_stop
    )

    assert outcome.result is DownloadResult.COMPLETED
    assert outcome.url_used == MIRROR_URL
    assert host.requests_for(PRIMARY_URL)[0].status == 404
    assert host.requests_for(MIRROR_URL)[0].status == 200


def test_every_url_missing_is_a_permanent_failure(tmp_path: Path, host: FakeModelHost) -> None:
    host.fail_primary()
    host.behavior.missing.add("/mirror.bento.example/releases/download/models-tiny/tiny-model.gguf")

    outcome = fake_host_downloader(host).download_blocking(
        model_file(host), part_path(tmp_path), lambda *_: None, never_stop
    )

    assert outcome.result is DownloadResult.FAILED


def test_a_checksum_mismatch_deletes_the_part_file(tmp_path: Path, host: FakeModelHost) -> None:
    part = part_path(tmp_path)
    host.behavior.wrong_body = True

    outcome = fake_host_downloader(host).download_blocking(model_file(host), part, lambda *_: None, never_stop)

    assert outcome.result is DownloadResult.CHECKSUM
    assert not part.exists()
    assert not part.with_name("tiny-model.gguf").exists()
    assert not part.with_name(part.name + ".meta").exists()


def test_should_stop_is_polled_between_blocks_and_keeps_the_part(tmp_path: Path, host: FakeModelHost) -> None:
    part = part_path(tmp_path)
    polls: list[int] = []

    def stop_after_two_blocks() -> bool:
        polls.append(size_of(part))
        return len(polls) >= 3  # the first poll happens before the request

    outcome = fake_host_downloader(host).download_blocking(model_file(host), part, lambda *_: None, stop_after_two_blocks)

    assert outcome.result is DownloadResult.STOPPED
    assert outcome.bytes_done == 2 * TEST_BLOCK_BYTES
    assert part.stat().st_size == 2 * TEST_BLOCK_BYTES
    assert polls == [0, TEST_BLOCK_BYTES, 2 * TEST_BLOCK_BYTES]


def test_pause_and_resume_on_a_slow_link(tmp_path: Path, host: FakeModelHost) -> None:
    part = part_path(tmp_path)
    file = model_file(host, urls=(PRIMARY_URL,))
    host.behavior.trickle_delay = 0.002
    paused = {"value": False}

    def pause_once_some_bytes_arrived() -> bool:
        if size_of(part) >= 3 * TEST_BLOCK_BYTES:
            paused["value"] = True
        return paused["value"]

    stopped = fake_host_downloader(host).download_blocking(file, part, lambda *_: None, pause_once_some_bytes_arrived)
    assert stopped.result is DownloadResult.STOPPED
    kept = part.stat().st_size

    host.behavior.trickle_delay = 0.0
    resumed = fake_host_downloader(host).download_blocking(file, part, lambda *_: None, never_stop)

    assert resumed.result is DownloadResult.COMPLETED
    assert host.requests_for(PRIMARY_URL)[-1].range == f"bytes={kept}-"
    assert part.with_name("tiny-model.gguf").read_bytes() == host.blob


def test_a_complete_part_left_by_a_kill_is_verified_without_a_request(tmp_path: Path, host: FakeModelHost) -> None:
    part = part_path(tmp_path)
    part.parent.mkdir(parents=True)
    part.write_bytes(host.blob)

    outcome = fake_host_downloader(host).download_blocking(model_file(host), part, lambda *_: None, never_stop)

    assert outcome.result is DownloadResult.COMPLETED
    assert host.requests == []


def test_an_unreachable_host_is_a_network_outcome(tmp_path: Path, host: FakeModelHost) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    downloader = HttpModelDownloader(
        user_agent="Bento/0.0.0-test",
        timeout_seconds=2.0,
        rewrite_url=lambda url: f"http://127.0.0.1:{closed_port}/x",
        allow_http_loopback=True,
    )

    outcome = downloader.download_blocking(model_file(host), part_path(tmp_path), lambda *_: None, never_stop)

    assert outcome.result is DownloadResult.NETWORK


def test_plain_http_is_refused_without_the_loopback_test_seam(tmp_path: Path, host: FakeModelHost) -> None:
    downloader = HttpModelDownloader(user_agent="Bento/0.0.0-test", rewrite_url=host.rewrite)

    outcome = downloader.download_blocking(model_file(host), part_path(tmp_path), lambda *_: None, never_stop)

    assert outcome.result is DownloadResult.FAILED
    assert host.requests == []


def test_the_work_budget_stops_the_download_at_a_block_boundary(tmp_path: Path, host: FakeModelHost) -> None:
    part = part_path(tmp_path)

    polls: list[int] = []

    def should_stop() -> bool:
        polls.append(size_of(part))
        if len(polls) > 1:  # past the first block: the run's deadline has passed
            check_safe_boundary()
        return False

    async def scenario() -> None:
        downloader = fake_host_downloader(host)
        with work_deadline(0.0, clock=lambda: 1.0):
            with pytest.raises(WorkBudgetExceeded):
                await downloader.download(model_file(host), part, lambda *_: None, should_stop)

    asyncio.run(scenario())
    assert size_of(part) == TEST_BLOCK_BYTES  # the bytes received so far stay for the next run
