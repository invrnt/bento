"""Desktop/headless device adapters: permissive conditions, no-op notifier, no content imports."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from bento.domain.device import PERMISSIVE_CONDITIONS, DeviceConditions
from bento.ports.device import ContentDescription, ContentHandleError, NotifierEvent, NotifierPort


class PermissiveDeviceConditions:
    """Always online, unmetered, and charging: no job is ever deferred."""

    def snapshot(self) -> DeviceConditions:
        return PERMISSIVE_CONDITIONS

    def subscribe(self, callback: Callable[[DeviceConditions], None]) -> Callable[[], None]:
        return lambda: None


class NullNotifier:
    def emit(self, event: NotifierEvent) -> None:
        return None


class UnavailableContentImports:
    def describe(self, handle: int) -> ContentDescription:
        raise ContentHandleError("Content imports are not available on this host")

    def adopt(self, handle: int) -> int:
        raise ContentHandleError("Content imports are not available on this host")


class RateLimitedNotifier:
    """Coalesces `transfer_progress` per transfer kind to at most one event per `interval` seconds.

    The latest progress inside a window is kept and sent when the window closes on the next emit or `flush`;
    every other event (and the closing `transfer_finished`) is delivered immediately, after any pending progress
    of the same kind. Exceptions from the wrapped notifier are swallowed: notifications are best effort.
    """

    def __init__(
        self, inner: NotifierPort, *, interval: float = 1.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._inner = inner
        self._interval = interval
        self._clock = clock
        self._lock = threading.Lock()
        self._last_sent: dict[str, float] = {}
        self._pending: dict[str, NotifierEvent] = {}

    def emit(self, event: NotifierEvent) -> None:
        to_send: list[NotifierEvent] = []
        with self._lock:
            now = self._clock()
            if event.name == "transfer_progress":
                kind = str(event.payload.get("kind", ""))
                last = self._last_sent.get(kind)
                if last is not None and now - last < self._interval:
                    self._pending[kind] = event
                    return
                self._pending.pop(kind, None)
                self._last_sent[kind] = now
                to_send.append(event)
            else:
                kind = str(event.payload.get("kind", "")) if event.name == "transfer_finished" else ""
                if kind and kind in self._pending:
                    to_send.append(self._pending.pop(kind))
                if kind:
                    self._last_sent.pop(kind, None)
                to_send.append(event)
        self._deliver(to_send)

    def flush(self) -> None:
        """Send pending progress whose window has closed."""
        with self._lock:
            now = self._clock()
            ready = [
                kind for kind in self._pending if now - self._last_sent.get(kind, float("-inf")) >= self._interval
            ]
            to_send = [self._pending.pop(kind) for kind in ready]
            for kind in ready:
                self._last_sent[kind] = now
        self._deliver(to_send)

    def _deliver(self, events: list[NotifierEvent]) -> None:
        for event in events:
            try:
                self._inner.emit(event)
            except Exception:  # noqa: BLE001 - a notification failure never affects backend work
                continue
