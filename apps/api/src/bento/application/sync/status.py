"""`SyncStatusProviderPort`: what the API reports from the state the worker's sync loop persisted."""

from __future__ import annotations

from bento.application.sync.ports import SyncOutboxStorePort, SyncStateStorePort
from bento.application.sync.state import (
    BOOTSTRAP,
    CAPTURE,
    CLOCK_SKEW,
    DEVICE_REMOVED,
    LAST_PULL_AT,
    LAST_PUSH_AT,
    LOOP,
    SYNC_REQUESTED_AT,
    SyncStateValues,
    parse_timestamp,
)
from bento.domain.sync import MAX_CLOCK_SKEW_MS, BootstrapProgress, SyncState, SyncStatus
from bento.ports.repositories import ClockPort

_BOOTSTRAP_OVERRIDES = frozenset({SyncState.IDLE, SyncState.SYNCING})
DEVICE_REMOVED_CODE = "device_removed"
CLOCK_SKEW_CODE = "clock_skew"


class SyncStatusService:
    """Reads local state only (no Telegram calls), so the UI can poll it cheaply from the API process."""

    def __init__(
        self, *, enabled: bool, state: SyncStateStorePort, outbox: SyncOutboxStorePort, clock: ClockPort
    ) -> None:
        self._enabled = enabled
        self._state = state
        self._values = SyncStateValues(state)
        self._outbox = outbox
        self._clock = clock

    async def status(self) -> SyncStatus:
        if not self._enabled:
            return SyncStatus(state=SyncState.DISABLED)
        loop = await self._values.get_json(LOOP)
        loop = loop if isinstance(loop, dict) else {}
        attached = await self._state.get_value(CAPTURE) is not None
        state = _loop_state(loop.get("state"), default=SyncState.IDLE if attached else SyncState.DISABLED)
        bootstrap = _bootstrap(await self._values.get_json(BOOTSTRAP))
        if bootstrap is not None and state in _BOOTSTRAP_OVERRIDES:
            state = SyncState.BOOTSTRAPPING
        waiting_until = parse_timestamp(loop.get("waiting_until")) if state == SyncState.WAITING else None
        error = loop.get("error") if isinstance(loop.get("error"), dict) else None
        if await self._state.get_value(DEVICE_REMOVED) is not None:
            # Another device rotated the vault keys without this one: nothing syncs until it joins again.
            return SyncStatus(
                state=SyncState.PAUSED,
                pending_ops=(await self._outbox.backlog()).count,
                last_push_at=await self._values.get_datetime(LAST_PUSH_AT),
                last_pull_at=await self._values.get_datetime(LAST_PULL_AT),
                error_code=DEVICE_REMOVED_CODE,
            )
        skew = _clock_skew(await self._values.get_json(CLOCK_SKEW))
        code = str(error["code"]) if error and error.get("code") else None
        return SyncStatus(
            state=state,
            pending_ops=(await self._outbox.backlog()).count,
            last_push_at=await self._values.get_datetime(LAST_PUSH_AT),
            last_pull_at=await self._values.get_datetime(LAST_PULL_AT),
            bootstrap=bootstrap,
            waiting_until=waiting_until,
            # Sync keeps running with a skewed clock; a failure of the loop itself is reported first.
            error_code=code if code is not None else (CLOCK_SKEW_CODE if skew is not None else None),
            clock_skew_ms=skew,
        )

    async def request_sync(self) -> None:
        if self._enabled:
            await self._values.set_datetime(SYNC_REQUESTED_AT, self._clock.now())


def _loop_state(value: object, *, default: SyncState) -> SyncState:
    try:
        return SyncState(str(value)) if value is not None else default
    except ValueError:
        return default


def _clock_skew(value: object) -> int | None:
    if not isinstance(value, dict):
        return None
    skew = value.get("skew_ms")
    if not isinstance(skew, int) or isinstance(skew, bool) or abs(skew) <= MAX_CLOCK_SKEW_MS:
        return None
    return skew


def _bootstrap(value: object) -> BootstrapProgress | None:
    if not isinstance(value, dict):
        return None
    try:
        return BootstrapProgress(done=max(0, int(value["done"])), total=max(0, int(value["total"])))
    except (KeyError, TypeError, ValueError):
        return None
