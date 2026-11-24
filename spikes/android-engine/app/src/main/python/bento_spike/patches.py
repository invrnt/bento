"""Monkeypatches the spike needs so the *unchanged* backend runs on Android.

Every patch here is a required real backend change for agent 35 (listed in docs/dev/android-spike.md).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

applied: list[str] = []
media_tools_calls = 0


def apply() -> None:
    if applied:
        return
    _stub_watchdog()
    _bundle_root_for_migrations()
    _media_tools_bridge()


def _stub_watchdog() -> None:
    """`interfaces/worker/main.py` imports `adapters/backup/watcher.py`, which imports watchdog at module level;
    watchdog is not in the `android` profile. Stub it so the import succeeds; starting an observer fails loudly."""
    try:
        import watchdog  # noqa: F401
        return
    except ImportError:
        pass
    root = types.ModuleType("watchdog")
    events = types.ModuleType("watchdog.events")
    observers = types.ModuleType("watchdog.observers")

    class FileSystemEventHandler:  # noqa: D401 - shape-compatible stub
        pass

    class Observer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("watchdog folder watching is not available on Android (MediaStoreSource replaces it)")

    events.FileSystemEventHandler = FileSystemEventHandler  # type: ignore[attr-defined]
    observers.Observer = Observer  # type: ignore[attr-defined]
    root.events = events  # type: ignore[attr-defined]
    root.observers = observers  # type: ignore[attr-defined]
    sys.modules.update({"watchdog": root, "watchdog.events": events, "watchdog.observers": observers})
    applied.append("watchdog_stub")


def _bundle_root_for_migrations() -> None:
    """`launcher._bundle_root()` assumes `apps/api/` (or PyInstaller's `_MEIPASS`); on Android `alembic.ini` and
    `migrations/` ship as the extracted `bento_migrations` package."""
    import bento_migrations
    from bento.interfaces.desktop import launcher

    root = Path(bento_migrations.__file__).resolve().parent
    launcher._bundle_root = lambda: root  # type: ignore[assignment]
    applied.append("launcher_bundle_root")


def _media_tools_bridge() -> None:
    """Image thumbnails/previews through the Kotlin `MediaTools` bridge (ImageDecoder) instead of Pillow."""
    from bento.adapters.media import generator as module
    from bento.domain.storage import BlobKind

    def generate_image(self, asset, source_path):  # type: ignore[no-untyped-def]
        global media_tools_calls
        from java import jclass

        bridge = jclass("dev.bento.spike.MediaTools")
        target_dir = self._asset_cache_dir(asset.id)
        generated = []
        for label, max_side in (("thumb-sm", 256), ("thumb-md", 512), ("preview", 1600)):
            output = target_dir / f"{label}.jpg"
            size = str(bridge.thumbnail(str(source_path), str(output), max_side, 85))
            media_tools_calls += 1
            width, height = (int(value) for value in size.split(","))
            generated.append(
                module._generated_file(
                    path=output,
                    kind=BlobKind.PREVIEW if label == "preview" else BlobKind.THUMBNAIL,
                    filename=f"{asset.id}-{label}.jpg",
                    mime_type="image/jpeg",
                    width=width,
                    height=height,
                )
            )
        return tuple(generated)

    module.LocalMediaGenerator._generate_image = generate_image  # type: ignore[method-assign]
    applied.append("media_tools_bridge")
