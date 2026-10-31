from __future__ import annotations

import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from bento.infrastructure.db.engine import sqlite_url
from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app


def test_local_release_critical_journey(tmp_path: Path) -> None:
    data_dir = _migrated_data_dir(tmp_path)
    client = TestClient(create_app(Settings(data_dir=str(data_dir), storage_backend="local")))

    settings = client.get("/api/settings")
    assert settings.status_code == 200
    assert settings.json()["storage_backend"] == "local"
    assert settings.json()["telegram_enabled"] is False
    assert settings.json()["worker_concurrency"] == 1

    document = client.post(
        "/api/assets/upload",
        files={"file": ("factura-smoke.txt", b"factura smoke local", "text/plain")},
        data={"mode": "drive"},
    )
    assert document.status_code == 200
    document_asset = document.json()

    drive = client.get("/api/drive/items")
    assert drive.status_code == 200
    assert any(item["asset"]["id"] == document_asset["id"] for item in drive.json()["items"] if item["type"] == "asset")

    search = client.get("/api/search", params={"q": "factura-smoke", "limit": "10"})
    assert search.status_code == 200
    assert any(item["asset_id"] == document_asset["id"] for item in search.json()["items"])

    download = client.get(f"/api/assets/{document_asset['id']}/download")
    assert download.status_code == 200
    assert download.content == b"factura smoke local"

    folder = client.post("/api/drive/folders", json={"name": "Smoke Folder"})
    assert folder.status_code == 200
    folder_id = folder.json()["id"]
    renamed = client.patch(f"/api/drive/folders/{folder_id}", json={"name": "Smoke Folder Renamed"})
    assert renamed.status_code == 200
    moved = client.post(f"/api/drive/items/{document_asset['id']}/move", json={"folder_id": folder_id})
    assert moved.status_code == 200
    nested_drive = client.get("/api/drive/items", params={"folder_id": folder_id})
    assert any(item["asset"]["id"] == document_asset["id"] for item in nested_drive.json()["items"] if item["type"] == "asset")

    photo = client.post(
        "/api/assets/upload",
        files={"file": ("foto-smoke.jpg", _tiny_jpeg(), "image/jpeg")},
        data={"mode": "photos"},
    )
    assert photo.status_code == 200
    photo_asset = photo.json()
    timeline = client.get("/api/photos/timeline")
    assert timeline.status_code == 200
    assert any(asset["id"] == photo_asset["id"] for group in timeline.json()["groups"] for asset in group["assets"])
    favorite = client.post(f"/api/photos/{photo_asset['id']}/favorite", json={"favorite": True})
    assert favorite.status_code == 200
    assert favorite.json()["favorite"] is True

    jobs = client.get("/api/jobs")
    assert jobs.status_code == 200
    assert any(job["asset_id"] == photo_asset["id"] and job["type"] == "thumbnail" for job in jobs.json()["items"])
    reindex = client.post("/api/admin/reindex")
    assert reindex.status_code == 200
    assert reindex.json()["enqueued"] == 1

    manifest_path = data_dir / "journal" / "manifest-events.jsonl"
    assert manifest_path.is_file()
    events = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]
    assert any(event["type"] == "asset_created" and event["entity_id"] == document_asset["id"] for event in events)
    assert any(event["type"] == "blob_stored" for event in events)


def _migrated_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    db_dir = data_dir / "db"
    db_dir.mkdir(parents=True)
    api_root = Path(__file__).parents[2]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "migrations"))
    config.set_main_option("sqlalchemy.url", sqlite_url(db_dir / "bento.sqlite3"))
    command.upgrade(config, "head")
    return data_dir


def _tiny_jpeg() -> bytes:
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00"
        b"\xff\xdb\x00C\x00"
        + (b"\x08" * 64)
        + b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
        b"\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08"
        b"\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xbf\xff\xd9"
    )
