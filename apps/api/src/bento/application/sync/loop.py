"""Worker sync loop: flush → pull → snapshot check → wait for activity, with backoff and status reporting."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from bento.application.sync.engine import SyncEngine
from bento.application.sync.ports import SyncStateStorePort
from bento.application.sync.state import LOOP, SYNC_REQUESTED_AT, SyncStateValues, format_timestamp
from bento.domain.errors import (
    DomainError,
    StorageUnavailableError,
    TelegramAccountError,
    TelegramFloodWaitError,
    VaultLockedError,
    VaultNotFoundError,
)
from bento.domain.sync import SyncState
from bento.domain.vault import VaultState
from bento.ports.repositories import ClockPort
from bento.ports.telegram import VaultTransportPort
from bento.ports.vault import VaultContext, VaultSessionPort

LOGGER = logging.getLogger("bento.sync.loop")

_PAUSED_ACCOUNT_CODES = frozenset({"telegram_not_authorized", "telegram_login_expired", "telegram_session_too_new"})


@dataclass(frozen=True, slots=True)
class SyncLoopPolicy:
    activity_timeout_seconds: float = 30.0
    tick_seconds: float = 1.0
    """How often the loop checks the cross-process "sync now" marker and the outbox thresholds."""
    not_ready_poll_seconds: float = 5.0
    backoff_initial_seconds: float = 2.0
    backoff_max_seconds: float = 120.0
    flood_wait_jitter_seconds: float = 1.0
    heartbeat_seconds: float = 60.0


class SyncLoop:
    def __init__(
        self,
        *,
        engine: SyncEngine,
        vault: VaultSessionPort,
        transport: VaultTransportPort,
        state: SyncStateStorePort,
        clock: ClockPort,
        policy: SyncLoopPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._engine = engine
        self._vault = vault
        self._transport = transport
        self._state = state
        self._values = SyncStateValues(state)
        self._clock = clock
        self._policy = policy or SyncLoopPolicy()
        self._sleep = sleep
        self._jitter = jitter
        self._reported: tuple[str, str | None, str | None] | None = None
        self._reported_at: datetime | None = None

    async def run(self, stop: asyncio.Event) -> None:
        backoff = self._policy.backoff_initial_seconds
        while not stop.is_set():
            try:
                context = await self._vault.current()
                if context is None:
                    await self._report(await self._not_ready_state())
                    await self._idle(stop, self._policy.not_ready_poll_seconds)
                    continue
                await self.run_cycle(context)
                backoff = self._policy.backoff_initial_seconds
                await self._wait_for_work(stop, context)
            except asyncio.CancelledError:
                raise
            except TelegramFloodWaitError as exc:
                seconds = max(0, exc.retry_after_seconds)
                until = self._clock.now() + timedelta(seconds=seconds)
                LOGGER.info("Telegram asked the sync loop to wait %s s", seconds)
                await self._report(SyncState.WAITING, waiting_until=until, error=exc)
                await self._idle(stop, seconds + self._jitter() * self._policy.flood_wait_jitter_seconds, wake_on_request=False)
            except Exception as exc:  # noqa: BLE001 - the loop must survive any failure and report it
                state = classify_failure(exc)
                if state == SyncState.ERROR:
                    LOGGER.warning("Sync cycle failed: %s", _safe(exc))
                await self._report(state, error=exc)
                await self._idle(stop, backoff if state != SyncState.PAUSED else self._policy.not_ready_poll_seconds)
                backoff = min(backoff * 2, self._policy.backoff_max_seconds)

    async def run_cycle(self, context: VaultContext) -> VaultContext:
        await self._report(SyncState.SYNCING)
        requested = await self._take_request()
        context = await self._engine.prepare(context)
        await self._engine.flush(context, force=requested)
        context, _ = await self._engine.pull(context)
        await self._engine.maybe_snapshot(context)
        await self._report(SyncState.IDLE)
        return context

    async def _wait_for_work(self, stop: asyncio.Event, context: VaultContext) -> None:
        activity = asyncio.ensure_future(
            self._transport.wait_for_activity(context.layout, self._policy.activity_timeout_seconds)
        )
        try:
            while True:
                done, _ = await asyncio.wait({activity}, timeout=self._policy.tick_seconds)
                if done:
                    activity.result()
                    return
                if stop.is_set() or await self._requested() or await self._engine.flush_due():
                    return
                if await self._engine.snapshot_due():
                    return
                await self._heartbeat()
        finally:
            if not activity.done():
                activity.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await activity

    async def _idle(self, stop: asyncio.Event, seconds: float, *, wake_on_request: bool = True) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, seconds)
        while not stop.is_set():
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=min(self._policy.tick_seconds, remaining))
            if wake_on_request and await self._requested():
                return

    async def _requested(self) -> bool:
        return await self._state.get_value(SYNC_REQUESTED_AT) is not None

    async def _take_request(self) -> bool:
        if not await self._requested():
            return False
        await self._values.delete(SYNC_REQUESTED_AT)
        return True

    async def _not_ready_state(self) -> SyncState:
        try:
            status = await self._vault.status()
        except Exception:  # noqa: BLE001 - status is best effort while the vault is unavailable
            return SyncState.PAUSED
        if status.state in {VaultState.LOCAL_ONLY, VaultState.NO_VAULT}:
            return SyncState.DISABLED
        return SyncState.PAUSED

    async def _report(
        self, state: SyncState, *, waiting_until: datetime | None = None, error: Exception | None = None
    ) -> None:
        code = _error_code(error) if error is not None else None
        until = format_timestamp(waiting_until) if waiting_until is not None else None
        signature = (state.value, until, code)
        if signature == self._reported:
            return
        await self._write(state, until, code, _safe(error) if error is not None else None)
        self._reported = signature

    async def _heartbeat(self) -> None:
        if self._reported is None or self._reported_at is None:
            return
        if self._clock.now() - self._reported_at < timedelta(seconds=self._policy.heartbeat_seconds):
            return
        state, until, code = self._reported
        await self._write(SyncState(state), until, code, None)

    async def _write(self, state: SyncState, until: str | None, code: str | None, message: str | None) -> None:
        now = self._clock.now()
        await self._values.set_json(
            LOOP,
            {
                "state": state.value,
                "waiting_until": until,
                "error": None if code is None else {"code": code, "message": message or code},
                "updated_at": format_timestamp(now),
            },
        )
        self._reported_at = now


def classify_failure(exc: Exception) -> SyncState:
    if isinstance(exc, TelegramFloodWaitError):
        return SyncState.WAITING
    if isinstance(exc, TelegramAccountError):
        if exc.code == "telegram_network":
            return SyncState.OFFLINE
        return SyncState.PAUSED if exc.code in _PAUSED_ACCOUNT_CODES else SyncState.ERROR
    if isinstance(exc, (VaultLockedError, VaultNotFoundError)):
        return SyncState.PAUSED
    if isinstance(exc, (StorageUnavailableError, ConnectionError, TimeoutError)):
        return SyncState.OFFLINE
    return SyncState.ERROR


def _error_code(exc: Exception) -> str:
    if isinstance(exc, DomainError):
        return exc.code
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return "telegram_network"
    return "sync_failed"


def _safe(exc: Exception | None) -> str:
    if exc is None:
        return ""
    if isinstance(exc, DomainError):
        return exc.message
    return exc.__class__.__name__
