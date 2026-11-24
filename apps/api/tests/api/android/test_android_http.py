"""Android HTTP additions: imports by fd handle, thumbnail sizes, timeline keyset paging/index, offline pins,
local storage, and the pairing link form."""

from __future__ import annotations

import io
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from bento.adapters.android.host import AndroidHost
from bento.domain.storage import StorageBackend
from bento.infrastructure import services
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AssetModel, BlobRefModel, CacheEntryModel, JobModel
from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app
from tests.integration.storage_pipeline.support import RemoteSwitch, migrated_data_dir, pipeline_for
from tests.unit.android.bridge_fakes import FakeContentImports, FakeMediaTools, FakeNotifier


@pytest.fixture
def android(tmp_path: Path) -> Iterator[tuple[TestClient, object, dict[str, object]]]:
    bridges = {"content_imports": FakeContentImports(), "notifier": FakeNotifier(), "media_tools": FakeMediaTools()}
    services.install_android_host(AndroidHost.from_bridges(bridges))
    data_dir = migrated_data_dir(tmp_path)
    components = pipeline_for(data_dir, RemoteSwitch(None), storage_backend="local", platform="android")
    app = create_app(Settings(data_dir=str(data_dir), storage_backend="local", platform="android"))
    app.state.storage_pipeline = components
    try:
        with TestClient(app) as client:
            yield client, components, bridges
    finally:
        services.install_android_host(None)


def _jpeg(color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (80, 60), color).save(buffer, format="JPEG")
    return buffer.getvalue()


def _wait_import(client: TestClient, import_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        body = client.get(f"/api/android/imports/{import_id}").json()
        if body["done"]:
            return body
        time.sleep(0.02)
    raise AssertionError("import did not finish")


def test_imports_adopt_fd_handles_sanitize_names_and_dedupe(android, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    client, _components, bridges = android
    imports: FakeContentImports = bridges["content_imports"]  # type: ignore[assignment]
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "a.pdf").write_bytes(b"%PDF-1.4 big shared document")
    (shared / "b.jpg").write_bytes(_jpeg())
    first = imports.register(shared / "a.pdf", "../../etc/passwd\x07.pdf", "application/pdf")
    second = imports.register(shared / "b.jpg", "foto.jpg", "image/jpeg")
    again = imports.register(shared / "a.pdf", "copy.pdf", "application/pdf")
    started = client.post(
        "/api/android/imports",
        json={"items": [{"fd_handle": first}, {"fd_handle": second, "display_name": "foto.jpg", "mime_type": "image/jpeg"},
                        {"fd_handle": again}, {"fd_handle": 999}]},
    )
    assert started.status_code == 202
    body = _wait_import(client, started.json()["import_id"])
    statuses = [item["status"] for item in body["items"]]
    assert statuses == ["done", "done", "duplicate", "failed"]
    assert body["items"][0]["asset_id"] == body["items"][2]["asset_id"]
    asset = client.get(f"/api/assets/{body['items'][0]['asset_id']}").json()
    assert "/" not in asset["filename"] and "\x07" not in asset["filename"] and asset["filename"].endswith(".pdf")
    assert imports.registered == {}  # every handle adopted exactly once (999 was never registered)
    notifier: FakeNotifier = bridges["notifier"]  # type: ignore[assignment]
    assert notifier.events[-1] == ("transfer_finished", {"kind": "import", "count": 3, "failed": 1})
    assert client.get("/api/android/imports/imp_missing").status_code == 404
    assert client.post("/api/android/imports", json={"items": []}).status_code == 422


def test_thumbnail_sizes_etag_timeline_paging_index_and_item_fields(android) -> None:  # type: ignore[no-untyped-def]
    client, components, _bridges = android
    ids = []
    for index in range(5):
        uploaded = client.post("/api/assets/upload", files={"file": (f"p{index}.jpg", _jpeg((index * 40, 0, 0)), "image/jpeg")})
        ids.append(uploaded.json()["id"])
    import asyncio

    from bento.domain.jobs import JobType
    from bento.interfaces.worker.main import _create_dispatcher

    dispatcher = _create_dispatcher(worker_id="w", settings=components.settings)  # MediaTools bridge generator

    async def thumbnails() -> None:
        while await dispatcher.process_one(types=frozenset({JobType.THUMBNAIL})):
            pass

    asyncio.run(thumbnails())
    # Spread capture dates over two months.
    with session_scope(components.session_factory) as session:
        base = datetime(2024, 3, 20, 12, tzinfo=UTC)
        for offset, asset_id in enumerate(ids):
            moment = base - timedelta(days=offset * 6)  # Mar 20, 14, 8, 2, Feb 25
            session.execute(update(AssetModel).where(AssetModel.id == asset_id).values(taken_at=moment))

    page = client.get("/api/photos/timeline", params={"limit": 2}).json()
    seen = [asset["id"] for group in page["groups"] for asset in group["assets"]]
    assert seen == ids[:2] and page["next_cursor"].startswith("k.")
    item = page["groups"][0]["assets"][0]
    assert item["width"] == 1024 and item["remote_state"] == "local_only" and item["thumbnail_etag"]
    while page["next_cursor"]:
        page = client.get("/api/photos/timeline", params={"limit": 2, "cursor": page["next_cursor"]}).json()
        seen += [asset["id"] for group in page["groups"] for asset in group["assets"]]
    assert seen == ids  # keyset paging: no duplicates or gaps
    assert [a["id"] for g in client.get("/api/photos/timeline", params={"cursor": "2"}).json()["groups"] for a in g["assets"]] == ids[2:]

    index = client.get("/api/photos/timeline/index").json()["months"]
    assert [(month["month"], month["count"]) for month in index] == [("2024-03", 4), ("2024-02", 1)]
    february = client.get("/api/photos/timeline", params={"cursor": index[1]["first_cursor"]}).json()
    assert [a["id"] for g in february["groups"] for a in g["assets"]] == [ids[4]]

    small = client.get(f"/api/assets/{ids[0]}/thumbnail", params={"size": 256})
    assert small.status_code == 200 and small.headers["cache-control"] == "private, max-age=31536000, immutable"
    medium = client.get(f"/api/assets/{ids[0]}/thumbnail", params={"size": 512})
    large = client.get(f"/api/assets/{ids[0]}/thumbnail", params={"size": 1024})
    assert medium.headers["etag"] == large.headers["etag"] != small.headers["etag"]  # nearest not smaller: 1024
    cached = client.get(f"/api/assets/{ids[0]}/thumbnail", params={"size": 256}, headers={"If-None-Match": small.headers["etag"]})
    assert cached.status_code == 304
    assert client.get(f"/api/assets/{ids[0]}/thumbnail", params={"size": 300}).status_code == 400
    default = client.get(f"/api/assets/{ids[0]}/thumbnail")
    assert default.status_code == 200, default.text  # default behavior unchanged

    with session_scope(components.session_factory) as session:
        session.execute(update(JobModel).where(JobModel.asset_id == ids[1]).values(status="failed"))
        session.add(
            JobModel(
                id="job_up", type="remote_upload", status="queued", priority=1, payload_json={"kind": "original"},
                attempts=0, max_attempts=3, asset_id=ids[1], created_at=base, updated_at=base,
            )
        )
        session.execute(
            update(BlobRefModel).where(BlobRefModel.asset_id == ids[2], BlobRefModel.kind == "original").values(backend="telegram")
        )
    states = {
        a["id"]: a["remote_state"] for g in client.get("/api/photos/timeline").json()["groups"] for a in g["assets"]
    }
    assert states[ids[1]] == "uploading" and states[ids[2]] == "remote" and states[ids[3]] == "local_only"


def test_offline_pins_and_local_storage(android) -> None:  # type: ignore[no-untyped-def]
    client, components, _bridges = android
    asset = client.post("/api/assets/upload", files={"file": ("doc.pdf", b"%PDF-1.4 pin me", "application/pdf")}).json()
    local_pin = client.put(f"/api/assets/{asset['id']}/offline")
    assert local_pin.status_code == 202 and local_pin.json() == {"asset_id": asset["id"], "pinned": True, "downloading": False}

    # An uploaded original cached locally: pinning marks the cache entry and eviction skips it.
    with session_scope(components.session_factory) as session:
        session.execute(update(BlobRefModel).where(BlobRefModel.asset_id == asset["id"]).values(backend=StorageBackend.TELEGRAM.value))
        blob = session.query(BlobRefModel).filter(BlobRefModel.asset_id == asset["id"], BlobRefModel.kind == "original").one()
        path = components.cache.path_for(blob.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4 pin me")
        session.add(CacheEntryModel(blob_ref_id=blob.id, path=str(path), size_bytes=15, last_accessed_at=datetime(2020, 1, 1, tzinfo=UTC)))
    assert client.put(f"/api/assets/{asset['id']}/offline").json()["pinned"] is True
    storage = client.get("/api/storage/local").json()
    assert storage["pinned_bytes"] == 15 and storage["pinned_count"] == 1 and storage["cache_limit_bytes"] == components.cache_max_bytes
    assert set(storage) == {"cache_bytes", "cache_files", "pinned_bytes", "pinned_count", "cache_limit_bytes", "thumbs_bytes"}
    import asyncio

    with session_scope(components.session_factory) as session:  # no processing pending for the asset
        session.execute(update(JobModel).values(status="succeeded"))
        session.execute(update(AssetModel).values(processing_state="indexed"))
    result = asyncio.run(components.cache.evict(max_bytes=0))
    assert result.deleted_files == 0 and path.exists()
    assert client.delete(f"/api/assets/{asset['id']}/offline").json()["pinned"] is False
    assert asyncio.run(components.cache.evict(max_bytes=0)).deleted_files == 1
    assert client.put("/api/assets/asset_missing/offline").status_code == 404


def test_pairing_link_form_depends_on_the_site_url() -> None:
    from types import SimpleNamespace

    from bento.domain.pairing import PairingCode
    from bento.interfaces.http.routes_pairing import pairing_response

    code = PairingCode.parse("X2B0-2YM6-Q3SQ")
    session = SimpleNamespace(
        id="pair_1", role=SimpleNamespace(value="host"), transport=SimpleNamespace(value="relay"),
        state=SimpleNamespace(value="waiting"), code=code, expires_at=datetime(2026, 1, 1, tzinfo=UTC), peer=None,
        sas=None, error_code=None, vault=SimpleNamespace(created_at=None, devices_count=1),
    )
    view = SimpleNamespace(session=session, telegram_login_url=None, error_message=None)
    plain = pairing_response(view)  # type: ignore[arg-type]
    assert plain.link == "bento://join?v=1&c=X2B0-2YM6-Q3SQ" and plain.web_link is None
    site = pairing_response(view, site_url="https://bento.example/")  # type: ignore[arg-type]
    assert site.link == site.web_link == "https://bento.example/join#v=1&c=X2B0-2YM6-Q3SQ"
    assert site.qr != plain.qr  # the QR encodes the link form in use


def test_jobs_and_status_show_why_work_waits(tmp_path: Path) -> None:
    from bento.adapters.jobs import SQLiteJobQueue
    from bento.domain.jobs import JobType
    from tests.unit.android.bridge_fakes import FakeDeviceConditions

    conditions = FakeDeviceConditions(unmetered=False, metered=True, charging=False, battery_pct=60)
    services.install_android_host(AndroidHost.from_bridges({"conditions": conditions}))
    try:
        data_dir = migrated_data_dir(tmp_path)
        components = pipeline_for(data_dir, RemoteSwitch(None), storage_backend="local", platform="android")
        settings = Settings(data_dir=str(data_dir), storage_backend="local", platform="android")
        app = create_app(settings)
        app.state.storage_pipeline = components
        client = TestClient(app)
        import asyncio

        queue: SQLiteJobQueue = components.jobs

        async def seed() -> dict[str, str]:
            upload = await queue.enqueue(type=JobType.REMOTE_UPLOAD, priority=10, payload={"kind": "original"})
            thumb = await queue.enqueue(type=JobType.REMOTE_UPLOAD, priority=11, payload={"kind": "thumbnail"})
            ocr = await queue.enqueue(type=JobType.OCR, priority=3, payload={})
            return {"upload": upload.id, "thumb": thumb.id, "ocr": ocr.id}

        ids = asyncio.run(seed())
        reasons = {job["id"]: job["wait_reason"] for job in client.get("/api/jobs").json()["items"]}
        assert reasons == {ids["upload"]: "wifi", ids["thumb"]: None, ids["ocr"]: "charging"}
        assert client.get("/api/sync/status").json()["waiting"] == {"wifi": 1, "charging": 1}
        assert client.get("/api/backup/status").json()["waiting"]["wifi"] == 1

        assert client.post("/api/backup/run-now").status_code == 202  # lifts the Wi-Fi rule for this backlog
        services.get_job_eligibility(settings)  # cached per database; the run-now timestamp is read live
        reasons = {job["id"]: job["wait_reason"] for job in client.get("/api/jobs").json()["items"]}
        assert reasons[ids["upload"]] is None and reasons[ids["ocr"]] == "charging"
    finally:
        services.install_android_host(None)
