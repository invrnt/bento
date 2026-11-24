"""TEMPORARY monkeypatches (Stage 19 spike, docs/dev/android-spike.md "Required backend changes").

Applied only when `bento.interfaces.android.engine` does not exist. Each one is replaced by agent 35:
1. watchdog stub (lazy watcher import / MediaStore watcher by platform),
2. migrations location (migrations inside the package or passed by the engine),
3. MediaTools bridge for image thumbnails (thumbnailer port + `adapters/android/media_tools.py`).
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

applied: list[str] = []
bridge_calls = 0


def install_import_stubs() -> None:
    """Needed before `bento.interfaces.worker.main` can be imported (warm-up)."""
    if "watchdog_stub" in applied:
        return
    try:
        import watchdog  # noqa: F401

        return
    except ImportError:
        pass
    root = types.ModuleType("watchdog")
    events = types.ModuleType("watchdog.events")
    observers = types.ModuleType("watchdog.observers")

    class FileSystemEventHandler:  # shape-compatible stub
        pass

    class Observer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("folder watching is not available on Android (MediaStoreSource replaces it)")

    events.FileSystemEventHandler = FileSystemEventHandler  # type: ignore[attr-defined]
    observers.Observer = Observer  # type: ignore[attr-defined]
    root.events = events  # type: ignore[attr-defined]
    root.observers = observers  # type: ignore[attr-defined]
    sys.modules.update({"watchdog": root, "watchdog.events": events, "watchdog.observers": observers})
    applied.append("watchdog_stub")


def apply(bridges: Any) -> None:
    install_import_stubs()
    if "launcher_bundle_root" not in applied:
        _bundle_root_for_migrations()
    media_tools = _get(bridges, "media_tools")
    if media_tools is not None:
        _media_tools_bridge(media_tools)


def _get(bridges: Any, key: str) -> Any:
    try:
        return bridges[key]
    except (KeyError, TypeError):
        return None


def _bundle_root_for_migrations() -> None:
    import bento_migrations
    from bento.interfaces.desktop import launcher

    root = Path(bento_migrations.__file__).resolve().parent
    launcher._bundle_root = lambda: root  # type: ignore[assignment]
    applied.append("launcher_bundle_root")


def _media_tools_bridge(bridge: Any) -> None:
    """Image thumbnails/previews through the Kotlin `MediaTools` bridge (ImageDecoder) instead of Pillow."""
    from bento.adapters.media import generator as module
    from bento.domain.storage import BlobKind

    def generate_image(self, asset, source_path):  # type: ignore[no-untyped-def]
        global bridge_calls
        target_dir = self._asset_cache_dir(asset.id)
        generated = []
        for label, max_side in (("thumb-sm", 256), ("thumb-md", 1024), ("preview", 1600)):
            output = target_dir / f"{label}.jpg"
            size = json.loads(str(bridge.thumbnail(str(source_path), str(output), max_side, 85, "jpeg")))
            bridge_calls += 1
            generated.append(
                module._generated_file(
                    path=output,
                    kind=BlobKind.PREVIEW if label == "preview" else BlobKind.THUMBNAIL,
                    filename=f"{asset.id}-{label}.jpg",
                    mime_type="image/jpeg",
                    width=int(size["width"]),
                    height=int(size["height"]),
                )
            )
        return tuple(generated)

    module.LocalMediaGenerator._generate_image = generate_image  # type: ignore[method-assign]
    if "media_tools_bridge" not in applied:
        applied.append("media_tools_bridge")
