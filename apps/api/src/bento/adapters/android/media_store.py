"""`MediaLibraryPort` and backup suggestions over the `MediaStoreSource` bridge."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from typing import Any, BinaryIO

from bento.adapters.android.bridge import BridgeIOError, call, call_json
from bento.domain.backup import BackupSuggestion, BackupSuggestionKind, MediaAccess, MediaBucket, MediaItem

SCAN_PAGE = 500
# Buckets enabled by default on Android (`product/android.md` §5).
DEFAULT_BUCKET_NAMES = frozenset({"camera", "cámara", "screenshots", "capturas de pantalla"})


class BridgeMediaLibrary:
    def __init__(self, bridge: Any, *, page_size: int = SCAN_PAGE) -> None:
        self._bridge = bridge
        self._page_size = page_size

    def access(self) -> MediaAccess:
        data = call_json(self._bridge, "access")
        data = data if isinstance(data, dict) else {}
        return MediaAccess(full=bool(data.get("full")), partial=bool(data.get("partial")), location=bool(data.get("location")))

    def buckets(self) -> tuple[MediaBucket, ...]:
        data = call_json(self._bridge, "buckets")
        buckets = []
        for raw in data if isinstance(data, list) else []:
            if not isinstance(raw, dict) or not raw.get("bucket_id"):
                continue
            buckets.append(
                MediaBucket(
                    bucket_id=str(raw["bucket_id"]),
                    name=str(raw.get("name") or ""),
                    relative_path=str(raw.get("relative_path") or ""),
                    count=_int(raw.get("count")) or 0,
                    video_count=_int(raw.get("video_count")) or 0,
                )
            )
        return tuple(buckets)

    def scan(self, bucket_id: str) -> Iterator[MediaItem]:
        after = 0
        while True:
            page = call_json(self._bridge, "scan", bucket_id, after, self._page_size)
            if not isinstance(page, dict):
                raise BridgeIOError("scan returned malformed JSON")
            for raw in page.get("items") or ():
                item = media_item(raw)
                if item is not None:
                    yield item
            next_after = page.get("next_after")
            if not isinstance(next_after, int) or isinstance(next_after, bool) or next_after <= after:
                return
            after = next_after

    def existing(self, media_ids: tuple[str, ...]) -> frozenset[str]:
        if not media_ids:
            return frozenset()
        data = call_json(self._bridge, "exists", json.dumps([int(value) for value in media_ids]))
        return frozenset(str(value) for value in data) if isinstance(data, list) else frozenset()

    def open(self, item: MediaItem, *, require_original: bool) -> BinaryIO:
        descriptor = int(call(self._bridge, "openFd", item.uri, bool(require_original)))
        if descriptor < 0:
            raise BridgeIOError("openFd returned no descriptor")
        try:
            return os.fdopen(descriptor, "rb", buffering=1024 * 1024)
        except OSError:
            os.close(descriptor)
            raise


class MediaStoreSuggestions:
    """`BackupSuggestionsPort` on Android: buckets with items, `path` = `media_store:<bucket_id>`."""

    def __init__(self, library: BridgeMediaLibrary) -> None:
        self._library = library

    def suggestions(self) -> tuple[BackupSuggestion, ...]:
        return tuple(
            BackupSuggestion(
                path=f"{MEDIA_STORE_PREFIX}{bucket.bucket_id}",
                label=bucket.name,
                kind=BackupSuggestionKind.MEDIA_STORE,
                bucket_id=bucket.bucket_id,
                count=bucket.count,
                suggested=is_default_bucket(bucket),
            )
            for bucket in self._library.buckets()
            if bucket.count > 0
        )


def is_default_bucket(bucket: MediaBucket) -> bool:
    return bucket.name.strip().lower() in DEFAULT_BUCKET_NAMES


def media_item(raw: object) -> MediaItem | None:
    if not isinstance(raw, dict):
        return None
    media_id = raw.get("media_id")
    uri = raw.get("uri")
    if media_id is None or not isinstance(uri, str) or not uri:
        return None
    return MediaItem(
        media_id=str(media_id),
        uri=uri,
        bucket_id=str(raw.get("bucket_id") or ""),
        display_name=str(raw.get("display_name") or f"{media_id}"),
        mime_type=str(raw.get("mime_type") or "application/octet-stream"),
        size_bytes=_int(raw.get("size_bytes")) or 0,
        generation=_int(raw.get("generation")) or 0,
        date_taken_ms=_int(raw.get("date_taken_ms")),
        date_modified_s=_int(raw.get("date_modified_s")),
        width=_int(raw.get("width")),
        height=_int(raw.get("height")),
        duration_ms=_int(raw.get("duration_ms")),
        relative_path=str(raw.get("relative_path") or ""),
    )


def _int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


class MediaStoreWatcher:
    """`FolderWatcherPort` for `media_store` sources: Kotlin's `ContentObserver` reports changes through
    `engine.on_event("media_changed", {"bucket_ids": [...]})`, which calls `notify`."""

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self._watches: dict[str, tuple[str, Callable[[str, str], None]]] = {}

    def watch(self, source_id: str, path: str, on_change: Callable[[str, str], None]) -> None:
        with self._lock:
            self._watches[source_id] = (path, on_change)

    def unwatch(self, source_id: str) -> None:
        with self._lock:
            self._watches.pop(source_id, None)

    def stop(self) -> None:
        with self._lock:
            self._watches.clear()

    def notify(self, bucket_ids: frozenset[str] | None) -> int:
        """Report a change to every watched source of `bucket_ids` (None = all); returns how many were told."""
        with self._lock:
            targets = [
                (source_id, path, callback)
                for source_id, (path, callback) in self._watches.items()
                if bucket_ids is None or path.removeprefix(MEDIA_STORE_PREFIX) in bucket_ids
            ]
        for source_id, path, callback in targets:
            callback(source_id, path)
        return len(targets)


MEDIA_STORE_PREFIX = "media_store:"
