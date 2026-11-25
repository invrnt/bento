"""`NotifierPort` over the `Notifier` bridge (`emit(event: String, payloadJson: String)`), rate limited."""

from __future__ import annotations

import json
import logging
from typing import Any

from bento.adapters.android.bridge import BridgeError, call
from bento.adapters.device import RateLimitedNotifier
from bento.ports.device import NotifierEvent

LOGGER = logging.getLogger("bento.android.notifier")


class BridgeNotifier:
    def __init__(self, bridge: Any) -> None:
        self._bridge = bridge

    def emit(self, event: NotifierEvent) -> None:
        payload = json.dumps(event.payload, separators=(",", ":"), sort_keys=True)
        try:
            call(self._bridge, "emit", event.name, payload)
        except BridgeError as exc:
            LOGGER.debug("Notifier event %s dropped (%s)", event.name, exc.code)


def android_notifier(bridge: Any) -> RateLimitedNotifier:
    """Progress at most once per second per transfer kind (`api/android-endpoints.md` §7)."""
    return RateLimitedNotifier(BridgeNotifier(bridge), interval=1.0)
