"""The Android adapters built from the bridge instances `engine.configure` receives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from bento.adapters.android.conditions import BridgeDeviceConditions
from bento.adapters.android.content_imports import BridgeContentImports
from bento.adapters.android.media_store import BridgeMediaLibrary, MediaStoreSuggestions, MediaStoreWatcher
from bento.adapters.android.notifier import android_notifier
from bento.adapters.device import RateLimitedNotifier

BRIDGE_KEYS = ("media_tools", "ocr", "media_store", "conditions", "notifier", "content_imports")


@dataclass(frozen=True, slots=True)
class AndroidHost:
    bridges: Mapping[str, Any]
    conditions: BridgeDeviceConditions | None
    notifier: RateLimitedNotifier | None
    content_imports: BridgeContentImports | None
    media_library: BridgeMediaLibrary | None
    suggestions: MediaStoreSuggestions | None
    watcher: MediaStoreWatcher

    @classmethod
    def from_bridges(cls, bridges: Mapping[str, Any]) -> AndroidHost:
        unknown = sorted(set(bridges) - set(BRIDGE_KEYS))
        if unknown:
            raise ValueError(f"Unknown bridges: {unknown}")
        library = BridgeMediaLibrary(bridges["media_store"]) if bridges.get("media_store") is not None else None
        return cls(
            bridges=dict(bridges),
            conditions=BridgeDeviceConditions(bridges["conditions"]) if bridges.get("conditions") is not None else None,
            notifier=android_notifier(bridges["notifier"]) if bridges.get("notifier") is not None else None,
            content_imports=(
                BridgeContentImports(bridges["content_imports"]) if bridges.get("content_imports") is not None else None
            ),
            media_library=library,
            suggestions=MediaStoreSuggestions(library) if library is not None else None,
            watcher=MediaStoreWatcher(),
        )

    def bridge(self, key: str) -> Any | None:
        return self.bridges.get(key)
