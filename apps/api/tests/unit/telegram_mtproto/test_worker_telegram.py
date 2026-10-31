from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from bento.domain.errors import TelegramFloodWaitError
from bento.domain.jobs import Job, JobStatus, JobType
from bento.infrastructure.settings import Settings
from bento.interfaces.worker import telegram as worker_telegram
from bento.interfaces.worker.telegram import TelegramJobHandlers, run_inbox_loop

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _job(job_type: JobType) -> Job:
    return Job(
        id="job_1", type=job_type, status=JobStatus.RUNNING, priority=0, payload={}, attempts=0, max_attempts=1,
        created_at=NOW, updated_at=NOW,
    )


class StubInbox:
    def __init__(self, stop: asyncio.Event, failures: list[Exception]) -> None:
        self.stop = stop
        self.failures = failures
        self.scans = 0

    async def scan(self) -> int:
        self.scans += 1
        if self.failures:
            raise self.failures.pop(0)
        self.stop.set()
        return 0

    async def cleanup(self) -> int:
        return 0


def test_handlers_claim_only_telegram_jobs(tmp_path: Path) -> None:
    handlers = TelegramJobHandlers(Settings(data_dir=str(tmp_path), storage_backend="local"))
    assert handlers.handles(_job(JobType.ACCOUNT_RELOAD))
    assert handlers.handles(_job(JobType.TELEGRAM_IMPORT)) and handlers.handles(_job(JobType.INBOX_IMPORT))
    assert not handlers.handles(_job(JobType.THUMBNAIL))
    asyncio.run(handlers.handle(_job(JobType.ACCOUNT_RELOAD)))  # local mode: nothing to reload


def test_inbox_loop_is_off_in_local_mode_and_survives_failures(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def scenario() -> int:
        stop = asyncio.Event()
        await run_inbox_loop(Settings(data_dir=str(tmp_path), storage_backend="local"), stop)
        sleeps: list[float] = []

        async def no_sleep(_stop: asyncio.Event, seconds: float) -> None:
            sleeps.append(seconds)

        async def no_wait(_settings: Settings, _stop: asyncio.Event) -> None:
            return None

        monkeypatch.setattr(worker_telegram, "_sleep", no_sleep)
        monkeypatch.setattr(worker_telegram, "_wait_for_activity", no_wait)
        inbox = StubInbox(stop, [TelegramFloodWaitError(42), RuntimeError("bug")])
        await run_inbox_loop(Settings(data_dir=str(tmp_path), storage_backend="fake"), stop, service=inbox)  # type: ignore[arg-type]
        assert sleeps == [42.0, 10.0]
        return inbox.scans

    assert asyncio.run(scenario()) == 3


def test_waiting_for_inbox_activity_ends_quietly_when_the_worker_stops(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from types import SimpleNamespace

    from bento.infrastructure.mtproto import wiring

    class Session:
        async def current(self) -> object:
            return SimpleNamespace(layout="layout")

    class Transport:
        async def wait_for_activity(self, layout: object, timeout_seconds: float) -> bool:
            await asyncio.sleep(timeout_seconds)
            return False

    monkeypatch.setattr(wiring, "vault_session", lambda settings: Session())
    monkeypatch.setattr(wiring, "telegram_runtime", lambda settings: SimpleNamespace(transport=Transport()))

    async def scenario() -> None:
        stop = asyncio.Event()
        asyncio.get_running_loop().call_later(0.05, stop.set)
        await asyncio.wait_for(
            worker_telegram._wait_for_activity(Settings(data_dir=str(tmp_path), storage_backend="fake"), stop), 5
        )

    asyncio.run(scenario())
