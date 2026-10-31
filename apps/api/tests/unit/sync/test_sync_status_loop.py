"""Status semantics and the worker loop with in-memory doubles (no SQLite, no Telegram)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from bento.application.sync import SyncLoop, SyncLoopPolicy, SyncStatusService, classify_failure
from bento.application.sync.ports import OutboxBacklog
from bento.domain.errors import (
    StorageUnavailableError,
    TelegramAccountError,
    TelegramFloodWaitError,
    ValidationFailedError,
    VaultLockedError,
)
from bento.domain.sync import SyncState
from bento.domain.vault import VaultLayout, VaultState, VaultStatus

NOW = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
LAYOUT = VaultLayout(vault_id="vlt_1", files_channel_id=1, sync_channel_id=2, inbox_channel_id=3)


@dataclass(frozen=True)
class Context:
    layout: VaultLayout = LAYOUT


CONTEXT = Context()


class MemoryState:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.loop_states: list[str] = []

    async def get_value(self, key: str) -> str | None:
        return self.values.get(key)

    async def set_value(self, key: str, value: str) -> None:
        self.values[key] = value
        if key == "loop":
            self.loop_states.append(json.loads(value)["state"])

    async def delete_value(self, key: str) -> None:
        self.values.pop(key, None)

    async def is_batch_applied(self, batch_id: str) -> bool:
        return False


@dataclass
class MemoryOutbox:
    count: int = 0

    async def backlog(self, *, after_seq: int = 0) -> OutboxBacklog:
        return OutboxBacklog(count=self.count, oldest_age_ms=0, total_bytes=0, max_seq=self.count)


class Clock:
    def now(self) -> datetime:
        return NOW


def status_of(state: MemoryState, *, enabled: bool = True, pending: int = 0) -> Any:
    service = SyncStatusService(enabled=enabled, state=state, outbox=MemoryOutbox(pending), clock=Clock())  # type: ignore[arg-type]
    return asyncio.run(service.status())


def test_status_is_disabled_for_local_storage_and_idle_once_attached() -> None:
    state = MemoryState()
    assert status_of(state, enabled=False).state == SyncState.DISABLED
    assert status_of(state).state == SyncState.DISABLED  # worker never attached a vault
    state.values["capture"] = json.dumps({"vault_id": "vlt_1", "device_id": "dev_a"})
    assert status_of(state, pending=3).state == SyncState.IDLE
    assert status_of(state, pending=3).pending_ops == 3


def test_status_reports_bootstrap_progress_waiting_and_errors() -> None:
    state = MemoryState()
    state.values["capture"] = json.dumps({"vault_id": "vlt_1", "device_id": "dev_a"})
    state.values["loop"] = json.dumps({"state": "syncing", "waiting_until": None, "error": None})
    state.values["bootstrap"] = json.dumps({"done": 40, "total": 100})
    state.values["last_pull_at"] = NOW.isoformat()
    status = status_of(state)
    assert status.state == SyncState.BOOTSTRAPPING and (status.bootstrap.done, status.bootstrap.total) == (40, 100)
    assert status.last_pull_at == NOW

    state.values["loop"] = json.dumps(
        {"state": "waiting", "waiting_until": "2026-05-01T09:05:00+00:00", "error": {"code": "telegram_flood_wait", "message": "x"}}
    )
    status = status_of(state)
    assert status.state == SyncState.WAITING and status.waiting_until == datetime(2026, 5, 1, 9, 5, tzinfo=UTC)
    assert status.error_code == "telegram_flood_wait"


def test_request_sync_writes_the_cross_process_marker_only_when_enabled() -> None:
    state = MemoryState()
    asyncio.run(SyncStatusService(enabled=False, state=state, outbox=MemoryOutbox(), clock=Clock()).request_sync())  # type: ignore[arg-type]
    assert "sync_requested_at" not in state.values
    asyncio.run(SyncStatusService(enabled=True, state=state, outbox=MemoryOutbox(), clock=Clock()).request_sync())  # type: ignore[arg-type]
    assert state.values["sync_requested_at"] == NOW.isoformat()


def test_failures_map_to_status_states() -> None:
    assert classify_failure(TelegramFloodWaitError(30)) == SyncState.WAITING
    assert classify_failure(TelegramAccountError("telegram_network", "x")) == SyncState.OFFLINE
    assert classify_failure(StorageUnavailableError("telegram")) == SyncState.OFFLINE
    assert classify_failure(ConnectionResetError()) == SyncState.OFFLINE
    assert classify_failure(TelegramAccountError("telegram_not_authorized", "x")) == SyncState.PAUSED
    assert classify_failure(VaultLockedError()) == SyncState.PAUSED
    assert classify_failure(ValidationFailedError("boom")) == SyncState.ERROR


@dataclass
class FakeEngine:
    failures: list[Exception] = field(default_factory=list)
    cycles: int = 0
    forced: list[bool] = field(default_factory=list)

    async def prepare(self, context: Any) -> Any:
        if self.failures:
            raise self.failures.pop(0)
        return context

    async def flush(self, context: Any, *, force: bool = False) -> int:
        self.forced.append(force)
        return 0

    async def pull(self, context: Any) -> tuple[Any, Any]:
        self.cycles += 1
        return context, None

    async def maybe_snapshot(self, context: Any, *, force: bool = False) -> bool:
        return False

    async def flush_due(self) -> bool:
        return False

    async def snapshot_due(self) -> bool:
        return False


class FakeVault:
    def __init__(self, context: Any) -> None:
        self.context = context

    async def current(self) -> Any:
        return self.context

    async def status(self) -> VaultStatus:
        return VaultStatus(state=VaultState.NO_VAULT)


class FakeTransport:
    async def wait_for_activity(self, layout: VaultLayout, timeout_seconds: float) -> bool:
        await asyncio.sleep(timeout_seconds)
        return False


def run_loop(engine: FakeEngine, vault: FakeVault, state: MemoryState, *, until: Any, seconds: float = 3.0) -> list[str]:
    async def scenario() -> None:
        stop = asyncio.Event()
        loop = SyncLoop(
            engine=engine,  # type: ignore[arg-type]
            vault=vault,  # type: ignore[arg-type]
            transport=FakeTransport(),  # type: ignore[arg-type]
            state=state,  # type: ignore[arg-type]
            clock=Clock(),
            policy=SyncLoopPolicy(
                activity_timeout_seconds=0.2, tick_seconds=0.01, not_ready_poll_seconds=0.02,
                backoff_initial_seconds=0.01, backoff_max_seconds=0.02, flood_wait_jitter_seconds=0,
            ),
        )
        task = asyncio.create_task(loop.run(stop))
        deadline = asyncio.get_running_loop().time() + seconds
        while asyncio.get_running_loop().time() < deadline and not until():
            await asyncio.sleep(0.005)
        stop.set()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())
    return state.loop_states


def test_loop_reports_offline_then_recovers_and_honours_flood_waits() -> None:
    engine = FakeEngine(failures=[TelegramAccountError("telegram_network", "down"), TelegramFloodWaitError(0)])
    state = MemoryState()
    seen = run_loop(engine, FakeVault(CONTEXT), state, until=lambda: engine.cycles >= 2)
    assert engine.cycles >= 2
    assert seen[:4] == ["syncing", "offline", "syncing", "waiting"]
    assert seen[-1] == "idle" and "error" not in seen


def test_loop_reports_disabled_without_a_vault_and_wakes_on_sync_now() -> None:
    state = MemoryState()
    vault = FakeVault(None)
    assert run_loop(FakeEngine(), vault, state, until=lambda: "loop" in state.values) == ["disabled"]

    engine = FakeEngine()
    vault.context = CONTEXT
    state.values["sync_requested_at"] = NOW.isoformat()
    run_loop(engine, vault, state, until=lambda: engine.cycles >= 1)
    assert engine.forced[0] is True and "sync_requested_at" not in state.values
