"""Android adapters against fake bridges: importable and tested on desktop, no Chaquopy."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bento.adapters.android.bridge import (
    BridgeIOError,
    BridgeNotFoundError,
    BridgePermissionDeniedError,
    BridgeUnsupportedError,
    bridge_error,
    call_json,
)
from bento.adapters.android.conditions import BridgeDeviceConditions
from bento.adapters.android.content_imports import BridgeContentImports
from bento.adapters.android.host import AndroidHost
from bento.adapters.android.media_store import BridgeMediaLibrary, MediaStoreSuggestions, MediaStoreWatcher, is_default_bucket
from bento.adapters.android.media_tools import BridgeMediaGenerator, BridgeMediaMetadataReader, BridgePDFPageRenderer
from bento.adapters.android.notifier import BridgeNotifier
from bento.adapters.android.ocr_mlkit import MLKitOCRAdapter
from bento.adapters.device import NullNotifier, PermissiveDeviceConditions, RateLimitedNotifier, UnavailableContentImports
from bento.domain.assets import Asset, AssetKind, AssetMetadata, AssetMode, ProcessingState
from bento.domain.device import PERMISSIVE_CONDITIONS, Thermal
from bento.domain.storage import BlobKind
from bento.ports.device import ContentHandleError, transfer_finished, transfer_progress
from tests.unit.android.bridge_fakes import (
    FakeBridgeException,
    FakeContentImports,
    FakeDeviceConditions,
    FakeMediaStoreSource,
    FakeMediaTools,
    FakeNotifier,
    FakeOcr,
)


def test_bridge_exceptions_map_to_typed_errors_without_leaking_messages() -> None:
    assert isinstance(bridge_error(FakeBridgeException("unsupported", "/secret/path")), BridgeUnsupportedError)
    assert isinstance(bridge_error(FakeBridgeException("not_found")), BridgeNotFoundError)
    assert isinstance(bridge_error(FakeBridgeException("permission_denied")), BridgePermissionDeniedError)
    unknown = bridge_error(RuntimeError("content://media/42 exploded"))
    assert isinstance(unknown, BridgeIOError) and "content://" not in str(unknown)
    mapped = bridge_error(FakeBridgeException("cancelled", "/secret/path"))
    assert mapped.code == "cancelled" and "/secret" not in str(mapped)

    class Broken:
        def snapshot(self) -> str:
            return "{not json"

    with pytest.raises(BridgeIOError):
        call_json(Broken(), "snapshot")


def test_conditions_cache_push_updates_and_subscribers() -> None:
    bridge = FakeDeviceConditions(unmetered=False, metered=True, charging=False, battery_pct=40)
    now = [0.0]
    conditions = BridgeDeviceConditions(bridge, ttl=5, clock=lambda: now[0])
    seen: list[object] = []
    unsubscribe = conditions.subscribe(seen.append)
    first = conditions.snapshot()
    assert first.metered and not first.charging and bridge.calls == 1
    assert conditions.snapshot() is first and bridge.calls == 1  # cached
    pushed = conditions.update(json.dumps({"online": True, "unmetered": True, "charging": True, "thermal": "severe"}))
    assert pushed.unmetered and pushed.thermal == Thermal.SEVERE and conditions.snapshot() == pushed
    assert len(seen) == 2
    unsubscribe()
    now[0] = 10
    conditions.snapshot()
    assert bridge.calls == 2 and len(seen) == 2

    class Failing:
        def snapshot(self) -> str:
            raise FakeBridgeException("io")

    assert BridgeDeviceConditions(Failing()).snapshot() == PERMISSIVE_CONDITIONS


def test_notifier_rate_limits_progress_to_one_hertz_and_flushes_the_latest() -> None:
    bridge = FakeNotifier()
    now = [0.0]
    notifier = RateLimitedNotifier(BridgeNotifier(bridge), interval=1.0, clock=lambda: now[0])
    for done in range(1, 6):
        notifier.emit(transfer_progress("backup", done=done, total=10))
        now[0] += 0.1
    assert [payload["done"] for _, payload in bridge.events] == [1]
    now[0] = 1.2
    notifier.flush()
    assert [payload["done"] for _, payload in bridge.events] == [1, 5]
    notifier.emit(transfer_progress("upload", done=1, total=2))  # other kinds are independent
    notifier.emit(transfer_progress("backup", done=6, total=10))  # inside the window: pending
    notifier.emit(transfer_finished("backup", count=10, failed=0))  # flushes pending progress first
    assert [(name, payload.get("done")) for name, payload in bridge.events[2:]] == [
        ("transfer_progress", 1),
        ("transfer_progress", 6),
        ("transfer_finished", None),
    ]

    class Exploding:
        def emit(self, event: str, payload: str) -> None:
            raise FakeBridgeException("io")

    BridgeNotifier(Exploding()).emit(transfer_finished("import", count=1, failed=0))  # never raises


def test_content_imports_adopt_once_and_hand_over_the_descriptor(tmp_path: Path) -> None:
    file = tmp_path / "shared.pdf"
    file.write_bytes(b"%PDF-1.7 shared")
    bridge = FakeContentImports()
    handle = bridge.register(file, "../../evil.pdf", "application/pdf")
    imports = BridgeContentImports(bridge)
    description = imports.describe(handle)
    assert description.display_name == "../../evil.pdf" and description.size_bytes == len(b"%PDF-1.7 shared")
    descriptor = imports.adopt(handle)
    with os.fdopen(descriptor, "rb") as handle_file:
        assert handle_file.read() == b"%PDF-1.7 shared"
    with pytest.raises(OSError):
        os.fstat(descriptor)  # closed with the file object
    with pytest.raises(ContentHandleError):
        imports.adopt(handle)  # one-time
    with pytest.raises(ContentHandleError):
        UnavailableContentImports().describe(1)


def _asset(kind: AssetKind, mime: str) -> Asset:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Asset(
        id=f"asset_{kind.value}",
        kind=kind,
        mode=AssetMode.PHOTOS,
        folder_id=None,
        filename="x",
        favorite=False,
        metadata=AssetMetadata(original_filename="x", mime_type=mime, size_bytes=10, sha256="c" * 64),
        processing_state=ProcessingState.THUMBNAIL_PENDING,
        created_at=now,
        updated_at=now,
    )


def test_media_tools_generator_images_videos_pdfs_and_pillow_fallback(tmp_path: Path) -> None:
    async def scenario() -> None:
        bridge = FakeMediaTools()
        generator = BridgeMediaGenerator(bridge, tmp_path / "cache")
        source = tmp_path / "source.bin"
        source.write_bytes(b"x")

        images = await generator.generate(_asset(AssetKind.IMAGE, "image/heic"), source)
        assert [(f.kind, f.width) for f in images] == [(BlobKind.THUMBNAIL, 256), (BlobKind.THUMBNAIL, 1024), (BlobKind.PREVIEW, 1600)]
        assert all(f.path.is_file() and len(f.sha256) == 64 for f in images)
        video = await generator.generate(_asset(AssetKind.VIDEO, "video/mp4"), source)
        assert [call[0] for call in bridge.calls[-2:]] == ["videoFrame", "videoFrame"] and len(video) == 2
        pdf = await generator.generate(_asset(AssetKind.PDF, "application/pdf"), source)
        assert [f.kind for f in pdf] == [BlobKind.THUMBNAIL, BlobKind.PREVIEW]
        await generator.cleanup(images + video + pdf)
        assert not any(f.path.exists() for f in images + video + pdf)

        from PIL import Image

        Image.new("RGB", (40, 30)).save(tmp_path / "real.jpg")
        fallback = BridgeMediaGenerator(FakeMediaTools(unsupported=True), tmp_path / "cache2")
        produced = await fallback.generate(_asset(AssetKind.IMAGE, "image/jpeg"), tmp_path / "real.jpg")
        assert produced and produced[0].mime_type == "image/jpeg"  # Pillow took over

        pages = await BridgePDFPageRenderer(FakeMediaTools(page_count=3), tmp_path / "pages").render_pages(
            asset_id="asset_pdf", source_path=source
        )
        assert [page.page_number for page in pages] == [1, 2, 3]
        metadata = await BridgeMediaMetadataReader(bridge).read(str(source), "image/jpeg")
        assert metadata.taken_at == "2024-03-05T10:11:12Z" and metadata.exif["model"] == "Pixel 7a"  # type: ignore[index]

    asyncio.run(scenario())


def test_mlkit_ocr_returns_the_rapidocr_block_shape() -> None:
    async def scenario() -> None:
        adapter = MLKitOCRAdapter(FakeOcr())
        assert await adapter.is_enabled() is True
        blocks = await adapter.extract_text("asset_1", "/data/page.jpg")
        assert [(block.text, block.confidence) for block in blocks] == [("Factura", 0.98), ("Total 12.000", 0.91)]
        assert all(block.asset_id == "asset_1" and block.id.startswith("ocr_") for block in blocks)
        assert await MLKitOCRAdapter(FakeOcr(available=False)).is_enabled() is False

    asyncio.run(scenario())


def test_media_library_pages_scans_checks_existence_and_opens_descriptors(tmp_path: Path) -> None:
    bridge = FakeMediaStoreSource(tmp_path)
    bridge.add_bucket("cam", "Camera", "DCIM/Camera/")
    bridge.add_bucket("dl", "Download", "Download/")
    ids = [bridge.add("cam", f"IMG_{index}.jpg", f"photo {index}".encode()) for index in range(7)]
    library = BridgeMediaLibrary(bridge, page_size=3)
    items = list(library.scan("cam"))
    assert [item.media_id for item in items] == [str(value) for value in ids]
    assert len([call for call in bridge.calls if call.startswith("scan:cam")]) == 3
    assert items[0].change_token == ids[0] and items[0].relative_path == "DCIM/Camera/"
    bridge.remove(ids[0])
    assert library.existing((str(ids[0]), str(ids[1]))) == frozenset({str(ids[1])})
    with library.open(items[1], require_original=True) as handle:
        assert handle.read() == b"photo 1"
    assert library.access().location is True
    buckets = library.buckets()
    assert [(bucket.name, bucket.count) for bucket in buckets] == [("Camera", 6), ("Download", 0)]
    assert is_default_bucket(buckets[0]) and not is_default_bucket(buckets[1])
    assert [suggestion.path for suggestion in MediaStoreSuggestions(library).suggestions()] == ["media_store:cam"]


def test_media_store_watcher_routes_changes_by_bucket() -> None:
    watcher = MediaStoreWatcher()
    changes: list[tuple[str, str]] = []
    watcher.watch("src_cam", "media_store:cam", lambda source, path: changes.append((source, path)))
    watcher.watch("src_shots", "media_store:shots", lambda source, path: changes.append((source, path)))
    assert watcher.notify(frozenset({"cam"})) == 1
    assert watcher.notify(None) == 2
    watcher.unwatch("src_cam")
    assert watcher.notify(frozenset({"cam"})) == 0
    assert changes == [("src_cam", "media_store:cam"), ("src_cam", "media_store:cam"), ("src_shots", "media_store:shots")]


def test_android_host_builds_only_the_bridges_it_got() -> None:
    host = AndroidHost.from_bridges({"conditions": FakeDeviceConditions()})
    assert host.conditions is not None and host.notifier is None and host.media_library is None
    with pytest.raises(ValueError):
        AndroidHost.from_bridges({"camera": object()})
    assert PermissiveDeviceConditions().snapshot() == PERMISSIVE_CONDITIONS
    NullNotifier().emit(transfer_finished("backup", count=0, failed=0))
