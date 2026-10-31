"""`FolderWatcherPort` on watchdog; events arrive on watchdog's thread and are debounced by the caller."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import Any

from watchdog.events import FileSystemEventHandler

from bento.adapters.backup.scanner import is_ignored_name

_IGNORED_EVENT_TYPES = frozenset({"opened", "closed_no_write"})


class _SourceEventHandler(FileSystemEventHandler):
    def __init__(self, source_id: str, on_change: Callable[[str, str], None]) -> None:
        super().__init__()
        self._source_id = source_id
        self._on_change = on_change

    def dispatch(self, event: Any) -> None:
        if getattr(event, "event_type", "") in _IGNORED_EVENT_TYPES:
            return
        for raw in (getattr(event, "src_path", ""), getattr(event, "dest_path", "")):
            path = os.fsdecode(raw) if raw else ""
            if path and not is_ignored_name(os.path.basename(path)):
                self._on_change(self._source_id, path)


class WatchdogFolderWatcher:
    def __init__(self, observer_factory: Callable[[], Any] | None = None) -> None:
        self._observer_factory = observer_factory
        self._observer: Any | None = None
        self._watches: dict[str, tuple[str, Any]] = {}
        self._lock = threading.Lock()

    def watch(self, source_id: str, path: str, on_change: Callable[[str, str], None]) -> None:
        with self._lock:
            current = self._watches.get(source_id)
            if current is not None and current[0] == path:
                return
            observer = self._ensure_observer()
            if current is not None:
                observer.unschedule(current[1])
            self._watches.pop(source_id, None)
            # OSError (missing folder, inotify limits) propagates so the caller retries later.
            watch = observer.schedule(_SourceEventHandler(source_id, on_change), path, recursive=True)
            self._watches[source_id] = (path, watch)

    def unwatch(self, source_id: str) -> None:
        with self._lock:
            current = self._watches.pop(source_id, None)
            if current is not None and self._observer is not None:
                try:
                    self._observer.unschedule(current[1])
                except (KeyError, OSError):
                    pass

    def stop(self) -> None:
        with self._lock:
            observer, self._observer = self._observer, None
            self._watches.clear()
        if observer is not None:
            observer.stop()
            observer.join(timeout=5)

    def _ensure_observer(self) -> Any:
        if self._observer is None:
            if self._observer_factory is None:
                from watchdog.observers import Observer

                self._observer_factory = Observer
            self._observer = self._observer_factory()
            self._observer.daemon = True
            self._observer.start()
        return self._observer
