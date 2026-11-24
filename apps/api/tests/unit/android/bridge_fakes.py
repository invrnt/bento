"""Plain-Python stand-ins for the Kotlin bridges (`architecture/android-runtime.md` §5.1): same method names,
primitive arguments, JSON-string results, and `BridgeException(code, message)`-shaped failures."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class FakeBridgeException(Exception):
    """Shape of `dev.bento.engine.bridge.BridgeException` as Chaquopy exposes it (`getCode()`)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self._code = code

    def getCode(self) -> str:  # noqa: N802 - Kotlin property getter name
        return self._code


class FakeMediaTools:
    def __init__(self, *, unsupported: bool = False, page_count: int = 3) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.unsupported = unsupported
        self.page_count = page_count

    def _write(self, output: str, max_side: int) -> None:
        # Unique per output (real thumbnails differ per photo; blobs are content-addressed).
        Path(output).write_bytes(b"\xff\xd8fake-jpeg-" + f"{max_side}:{output}".encode() + b"\xff\xd9")

    def thumbnail(self, source: str, output: str, maxSide: int, quality: int, format: str) -> str:  # noqa: N803
        self.calls.append(("thumbnail", (source, output, maxSide, quality, format)))
        if self.unsupported:
            raise FakeBridgeException("unsupported", "ImageDecoder cannot decode")
        self._write(output, maxSide)
        return json.dumps({"width": maxSide, "height": maxSide * 3 // 4})

    def videoFrame(self, source: str, output: str, maxSide: int, quality: int, atMs: int) -> str:  # noqa: N802,N803
        self.calls.append(("videoFrame", (source, output, maxSide, quality, atMs)))
        self._write(output, maxSide)
        return json.dumps({"width": maxSide, "height": maxSide * 9 // 16, "duration_ms": 12_000})

    def pdfPage(self, source: str, output: str, page: int, maxSide: int) -> str:  # noqa: N802,N803
        self.calls.append(("pdfPage", (source, output, page, maxSide)))
        self._write(output, maxSide)
        return json.dumps({"width": maxSide, "height": maxSide, "page_count": self.page_count})

    def metadata(self, source: str, mime: str) -> str:
        self.calls.append(("metadata", (source, mime)))
        return json.dumps(
            {
                "width": 4000,
                "height": 3000,
                "duration_ms": None,
                "taken_at": "2024-03-05T10:11:12Z",
                "orientation": 1,
                "exif": {"make": "Google", "model": "Pixel 7a", "gps": {"lat": 6.2, "lon": -75.5}},
            }
        )


class FakeOcr:
    def __init__(self, *, available: bool = True) -> None:
        self._available = available
        self.calls: list[tuple[str, int]] = []

    def available(self) -> bool:
        return self._available

    def recognize(self, source: str, maxSide: int) -> str:  # noqa: N803
        self.calls.append((source, maxSide))
        return json.dumps(
            {
                "text": "Factura\nTotal 12.000",
                "language": "es",
                "lines": [
                    {"text": "Factura", "box": [1, 2, 30, 10], "confidence": 0.98},
                    {"text": "  ", "box": [0, 0, 0, 0], "confidence": 0.1},
                    {"text": "Total 12.000", "box": [1, 20, 60, 10], "confidence": 0.91},
                ],
            }
        )


class FakeMediaStoreSource:
    """A bucketed media library over files in a directory; `openFd` returns a real descriptor."""

    def __init__(self, root: Path, *, access: dict[str, bool] | None = None) -> None:
        self.root = root
        self.items: dict[int, dict[str, Any]] = {}
        self.buckets_meta: dict[str, dict[str, str]] = {}
        self.access_state = access or {"full": True, "partial": False, "location": True}
        self.opened: list[int] = []
        self.calls: list[str] = []
        self._next_id = 1000

    def add_bucket(self, bucket_id: str, name: str, relative_path: str) -> None:
        self.buckets_meta[bucket_id] = {"name": name, "relative_path": relative_path}
        (self.root / bucket_id).mkdir(parents=True, exist_ok=True)

    def add(self, bucket_id: str, name: str, content: bytes, *, mime: str = "image/jpeg", taken_ms: int = 1_709_633_472_000) -> int:
        self._next_id += 1
        media_id = self._next_id
        path = self.root / bucket_id / name
        path.write_bytes(content)
        self.items[media_id] = {
            "media_id": media_id,
            "uri": f"content://media/external/images/media/{media_id}",
            "bucket_id": bucket_id,
            "display_name": name,
            "mime_type": mime,
            "size_bytes": len(content),
            "date_taken_ms": taken_ms,
            "date_modified_s": taken_ms // 1000,
            "generation": media_id,
            "width": 4000,
            "height": 3000,
            "duration_ms": None,
            "relative_path": self.buckets_meta[bucket_id]["relative_path"],
            "_path": str(path),
        }
        return media_id

    def edit(self, media_id: int, content: bytes) -> None:
        item = self.items[media_id]
        Path(item["_path"]).write_bytes(content)
        self._next_id += 1
        item["generation"] = self._next_id
        item["size_bytes"] = len(content)

    def remove(self, media_id: int) -> None:
        item = self.items.pop(media_id)
        Path(item["_path"]).unlink()

    def _public(self, item: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in item.items() if not key.startswith("_")}

    def access(self) -> str:
        return json.dumps(self.access_state)

    def buckets(self) -> str:
        result = []
        for bucket_id, meta in self.buckets_meta.items():
            items = [item for item in self.items.values() if item["bucket_id"] == bucket_id]
            result.append(
                {
                    "bucket_id": bucket_id,
                    "name": meta["name"],
                    "relative_path": meta["relative_path"],
                    "count": len(items),
                    "video_count": sum(1 for item in items if item["mime_type"].startswith("video/")),
                }
            )
        return json.dumps(result)

    def scan(self, bucketId: str, afterMediaId: int, limit: int) -> str:  # noqa: N803
        self.calls.append(f"scan:{bucketId}:{afterMediaId}")
        matching = sorted(media_id for media_id, item in self.items.items() if item["bucket_id"] == bucketId and media_id > afterMediaId)
        page = matching[:limit]
        next_after = page[-1] if len(matching) > limit else None
        return json.dumps({"items": [self._public(self.items[media_id]) for media_id in page], "next_after": next_after})

    def changes(self, sinceGeneration: int, limit: int) -> str:  # noqa: N803
        changed = [item for item in self.items.values() if item["generation"] > sinceGeneration][:limit]
        return json.dumps(
            {"items": [self._public(item) for item in changed], "max_generation": max((i["generation"] for i in changed), default=sinceGeneration)}
        )

    def exists(self, mediaIds: str) -> str:  # noqa: N803
        return json.dumps([value for value in json.loads(mediaIds) if int(value) in self.items])

    def openFd(self, uri: str, requireOriginal: bool) -> int:  # noqa: N802,N803
        for item in self.items.values():
            if item["uri"] == uri:
                descriptor = os.open(item["_path"], os.O_RDONLY)
                self.opened.append(descriptor)
                return descriptor
        raise FakeBridgeException("not_found", uri)


class FakeDeviceConditions:
    def __init__(self, **state: Any) -> None:
        self.state: dict[str, Any] = {
            "online": True,
            "metered": False,
            "unmetered": True,
            "charging": True,
            "battery_pct": 80,
            "power_save": False,
            "data_saver": False,
            "storage_free_bytes": 10_000_000_000,
            "storage_total_bytes": 64_000_000_000,
            "thermal": "none",
        }
        self.state.update(state)
        self.calls = 0

    def snapshot(self) -> str:
        self.calls += 1
        return json.dumps(self.state)


class FakeNotifier:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event: str, payloadJson: str) -> None:  # noqa: N803
        self.events.append((event, json.loads(payloadJson)))


class FakeContentImports:
    def __init__(self) -> None:
        self.registered: dict[int, tuple[str, str, str]] = {}
        self._next = 1

    def register(self, path: Path, display_name: str, mime_type: str) -> int:
        handle = self._next
        self._next += 1
        self.registered[handle] = (str(path), display_name, mime_type)
        return handle

    def describe(self, handle: int) -> str:
        if handle not in self.registered:
            raise FakeBridgeException("not_found")
        path, name, mime = self.registered[handle]
        return json.dumps({"display_name": name, "mime_type": mime, "size_bytes": os.path.getsize(path)})

    def adopt(self, handle: int) -> int:
        if handle not in self.registered:
            raise FakeBridgeException("not_found")
        path, _name, _mime = self.registered.pop(handle)
        return os.open(path, os.O_RDONLY)


def all_bridges(root: Path) -> dict[str, Any]:
    (root / "media").mkdir(parents=True, exist_ok=True)
    return {
        "media_tools": FakeMediaTools(),
        "ocr": FakeOcr(),
        "media_store": FakeMediaStoreSource(root / "media"),
        "conditions": FakeDeviceConditions(),
        "notifier": FakeNotifier(),
        "content_imports": FakeContentImports(),
    }
