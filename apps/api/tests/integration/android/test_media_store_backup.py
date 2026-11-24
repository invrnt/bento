"""Phone backup from MediaStore buckets through the real backup service, with a fake MediaStoreSource bridge."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from bento.adapters.android.host import AndroidHost
from bento.domain.backup import BackupFileState
from bento.domain.storage import StorageBackend
from bento.infrastructure import services
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AssetModel, BackupFileModel, BlobRefModel, FolderModel
from bento.interfaces.http.main import create_app
from tests.integration.storage_pipeline.support import RemoteSwitch, migrated_data_dir, pipeline_for
from tests.unit.android.bridge_fakes import FakeDeviceConditions, FakeMediaStoreSource, FakeNotifier


@pytest.fixture
def phone(tmp_path: Path) -> Iterator[tuple[TestClient, object, FakeMediaStoreSource]]:
    store = FakeMediaStoreSource(tmp_path / "media")
    store.add_bucket("cam", "Camera", "DCIM/Camera/")
    store.add_bucket("wa", "WhatsApp Images", "Pictures/WhatsApp/")
    store.add_bucket("empty", "Empty", "Empty/")
    notifier = FakeNotifier()
    store.notifier = notifier  # type: ignore[attr-defined]
    services.install_android_host(
        AndroidHost.from_bridges({"media_store": store, "conditions": FakeDeviceConditions(), "notifier": notifier})
    )
    data_dir = migrated_data_dir(tmp_path)
    components = pipeline_for(data_dir, RemoteSwitch(None), storage_backend="local", platform="android", device_name="Pixel 7a")
    from bento.infrastructure.settings import Settings

    app = create_app(Settings(data_dir=str(data_dir), platform="android", device_name="Pixel 7a", storage_backend="local"))
    app.state.storage_pipeline = components
    try:
        yield TestClient(app), components, store
    finally:
        services.install_android_host(None)


def _files(components: object) -> dict[str, BackupFileModel]:
    with session_scope(components.session_factory) as session:  # type: ignore[attr-defined]
        return {model.source_key: model for model in session.scalars(select(BackupFileModel))}


def test_media_store_buckets_back_up_with_dedupe_edits_removals_and_free_up_space(phone) -> None:  # type: ignore[no-untyped-def]
    client, components, store = phone
    backup = components.backup
    first = store.add("cam", "IMG_0001.jpg", b"\xff\xd8 first photo")
    second = store.add("cam", "IMG_0002.jpg", b"\xff\xd8 second photo")
    already = store.add("cam", "IMG_0003.jpg", b"\xff\xd8 already in the vault")
    store.add("wa", "IMG-WA0001.jpg", b"\xff\xd8 whatsapp")

    suggestions = client.get("/api/backup/suggestions").json()["items"]
    assert [(s["kind"], s["id"], s["count"], s["suggested"]) for s in suggestions] == [
        ("media_store", "cam", 3, True),
        ("media_store", "wa", 1, False),
    ]

    # The same bytes already uploaded from elsewhere: linked, never uploaded twice.
    existing = client.post("/api/assets/upload", files={"file": ("dup.jpg", b"\xff\xd8 already in the vault", "image/jpeg")}).json()

    created = client.post("/api/backup/sources", json={"kind": "media_store", "bucket_id": "cam"})
    assert created.status_code == 200, created.text
    source = created.json()
    assert (source["kind"], source["bucket_id"], source["label"], source["path"]) == ("media_store", "cam", "Camera", "media_store:cam")
    assert client.post("/api/backup/sources", json={"kind": "media_store", "bucket_id": "cam"}).status_code == 400
    assert client.post("/api/backup/sources", json={"kind": "media_store", "bucket_id": "nope"}).status_code == 400
    with session_scope(components.session_factory) as session:
        folders = {model.name: model for model in session.scalars(select(FolderModel))}
    assert {"Del teléfono", "Pixel 7a", "Camera"} <= set(folders)
    assert folders["Camera"].parent_id == folders["Pixel 7a"].id and folders["Pixel 7a"].parent_id == folders["Del teléfono"].id

    async def run() -> None:
        summary = await backup.scan_source(source["id"])
        assert summary.queued == 3
        assert await backup.upload_pending() == 3

    asyncio.run(run())
    events = store.notifier.events  # type: ignore[attr-defined]
    assert events[0] == ("transfer_progress", {"kind": "backup", "done": 1, "total": 3, "bytes_done": 0, "bytes_total": 0, "paused": False})
    assert events[-1] == ("transfer_finished", {"kind": "backup", "count": 3, "failed": 0})
    files = _files(components)
    assert {key: model.state for key, model in files.items()} == {str(i): "done" for i in (first, second, already)}
    assert files[str(already)].asset_id == existing["id"]
    with session_scope(components.session_factory) as session:
        assets = {model.id: model for model in session.scalars(select(AssetModel))}
    assert len(assets) == 3
    photo = assets[files[str(first)].asset_id]
    assert photo.origin == "device" and photo.folder_id == folders["Camera"].id
    assert photo.taken_at is not None and photo.taken_at.replace(tzinfo=UTC) == datetime.fromtimestamp(1_709_633_472, UTC)
    for descriptor in store.opened:  # every adopted fd is closed
        with pytest.raises(OSError):
            os.fstat(descriptor)

    # Rescan with no change queues nothing; an edit (new generation) re-uploads; a removal drops the row.
    store.edit(second, b"\xff\xd8 second photo, edited")
    store.remove(first)

    async def rescan() -> None:
        summary = await backup.scan_source(source["id"])
        assert (summary.queued, summary.removed) == (1, 1)
        assert await backup.upload_pending() == 1

    asyncio.run(rescan())
    files = _files(components)
    assert set(files) == {str(second), str(already)}
    assert files[str(second)].asset_id not in {photo.id, existing["id"]}

    # Free up space: only originals with a confirmed remote copy whose sha256 matches the phone file.
    assert client.get("/api/backup/free-up-space/preview").json() == {"items": [], "total_bytes": 0, "count": 0}
    verified_asset = files[str(second)].asset_id
    with session_scope(components.session_factory) as session:
        session.execute(
            update(BlobRefModel).where(BlobRefModel.asset_id == verified_asset).values(backend=StorageBackend.TELEGRAM.value)
        )
    preview = client.get("/api/backup/free-up-space/preview").json()
    assert preview["count"] == 1 and preview["items"][0] == {
        "asset_id": verified_asset,
        "media_id": str(second),
        "size_bytes": len(b"\xff\xd8 second photo, edited"),
    }
    store.remove(second)  # the system delete request removed it
    confirmed = client.post("/api/backup/free-up-space/confirm", json={"media_ids": [str(second), str(already)]})
    assert confirmed.json() == {"freed": 1}  # `already` has no verified remote copy
    assert _files(components)[str(second)].state == BackupFileState.FREED.value

    async def after_free() -> None:
        summary = await backup.scan_source(source["id"])
        assert (summary.queued, summary.removed) == (0, 0)  # freed rows survive the vanished check

    asyncio.run(after_free())
    assert client.get(f"/api/assets/{verified_asset}").status_code == 200  # the asset stays

    status = client.get("/api/backup/status").json()
    assert set(status) == {"pending", "waiting", "uploaded_today", "last_backup_at", "partial_access", "location_access"}
    assert set(status["waiting"]) >= {"wifi", "charging", "battery"}
    assert status["location_access"] is True and status["partial_access"] is False
    run_now = client.post("/api/backup/run-now")
    assert run_now.status_code == 202 and run_now.json()["accepted"] is True


def test_media_sources_need_a_media_library(tmp_path: Path) -> None:
    data_dir = migrated_data_dir(tmp_path)
    components = pipeline_for(data_dir, RemoteSwitch(None), storage_backend="local")
    from bento.infrastructure.settings import Settings

    app = create_app(Settings(data_dir=str(data_dir), storage_backend="local"))
    app.state.storage_pipeline = components
    client = TestClient(app)
    rejected = client.post("/api/backup/sources", json={"kind": "media_store", "bucket_id": "cam"})
    assert rejected.status_code == 400 and rejected.json()["error"]["details"]["reason"] == "media_store_unavailable"
    status = client.get("/api/backup/status").json()
    assert status["waiting"] == {"offline": 0, "thermal": 0, "battery": 0, "charging": 0, "wifi": 0}
    assert client.get("/api/backup/free-up-space/preview").json()["count"] == 0
