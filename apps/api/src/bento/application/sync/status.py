"""`SyncStatusProviderPort`: what the API reports from the state the worker's sync loop persisted."""

from __future__ import annotations

from bento.application.sync.ports import SyncOutboxStorePort, SyncStateStorePort
from bento.application.sync.state import (
    BOOTSTRAP,
    CAPTURE,
    LAST_PULL_AT,
    LAST_PUSH_AT,
    LOOP,
    SYNC_REQUESTED_AT,
    SyncStateValues,
    parse_timestamp,
)
from bento.domain.sync import BootstrapProgress, SyncState, SyncStatus
from bento.ports.repositories import ClockPort

_BOOTSTRAP_OVERRIDES = frozenset({SyncState.IDLE, SyncState.SYNCING})


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
        return SyncStatus(
            state=state,
            pending_ops=(await self._outbox.backlog()).count,
            last_push_at=await self._values.get_datetime(LAST_PUSH_AT),
            last_pull_at=await self._values.get_datetime(LAST_PULL_AT),
            bootstrap=bootstrap,
            waiting_until=waiting_until,
            error_code=str(error["code"]) if error and error.get("code") else None,
        )

    async def request_sync(self) -> None:
        if self._enabled:
            await self._values.set_datetime(SYNC_REQUESTED_AT, self._clock.now())


def _loop_state(value: object, *, default: SyncState) -> SyncState:
    try:
        return SyncState(str(value)) if value is not None else default
    except ValueError:
        return default


def _bootstrap(value: object) -> BootstrapProgress | None:
    if not isinstance(value, dict):
        return None
    try:
        return BootstrapProgress(done=max(0, int(value["done"])), total=max(0, int(value["total"])))
    except (KeyError, TypeError, ValueError):
        return None
