"""`DeviceConditionsPort` over the `DeviceConditions` bridge (`snapshot(): String`)."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from bento.adapters.android.bridge import BridgeError, call_json
from bento.domain.device import PERMISSIVE_CONDITIONS, DeviceConditions

LOGGER = logging.getLogger("bento.android.conditions")
SNAPSHOT_TTL_SECONDS = 5.0


class BridgeDeviceConditions:
    """Snapshots are cached for a few seconds; Kotlin pushes changes through `engine.on_event("conditions")`,
    which calls `update` with the new snapshot and notifies subscribers. A failing bridge reports the last known
    (initially permissive) conditions rather than stalling every job."""

    def __init__(self, bridge: Any, *, ttl: float = SNAPSHOT_TTL_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self._bridge = bridge
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._current: DeviceConditions | None = None
        self._read_at = float("-inf")
        self._subscribers: list[Callable[[DeviceConditions], None]] = []

    def snapshot(self) -> DeviceConditions:
        with self._lock:
            if self._current is not None and self._clock() - self._read_at < self._ttl:
                return self._current
        try:
            data = call_json(self._bridge, "snapshot")
            fresh = DeviceConditions.from_mapping(data if isinstance(data, dict) else {})
        except BridgeError as exc:
            LOGGER.warning("Device conditions unavailable (%s)", exc.code)
            with self._lock:
                return self._current or PERMISSIVE_CONDITIONS
        self._store(fresh)
        return fresh

    def subscribe(self, callback: Callable[[DeviceConditions], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def update(self, payload_json: str | None) -> DeviceConditions:
        """A pushed snapshot (`on_event("conditions", json)`); an empty payload forces a fresh bridge read."""
        if payload_json:
            try:
                data = json.loads(payload_json)
            except ValueError:
                data = None
            if isinstance(data, dict):
                conditions = DeviceConditions.from_mapping(data)
                self._store(conditions)
                return conditions
        with self._lock:
            self._read_at = float("-inf")
        return self.snapshot()

    def _store(self, conditions: DeviceConditions) -> None:
        with self._lock:
            changed = conditions != self._current
            self._current = conditions
            self._read_at = self._clock()
            subscribers = list(self._subscribers) if changed else []
        for callback in subscribers:
            try:
                callback(conditions)
            except Exception:  # noqa: BLE001 - one subscriber never breaks the others
                LOGGER.warning("Conditions subscriber failed", exc_info=True)
