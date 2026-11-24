from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from bento.infrastructure.db.engine import sqlite_url
from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app


def test_upload_duplicate_download_and_logical_delete_local_mode(tmp_path: Path) -> None:
    data_dir = _migrated_data_dir(tmp_path)
    client = TestClient(create_app(Settings(data_dir=str(data_dir))))
    content = b"private document"

    first = client.post(
        "/api/assets/upload",
        files={"file": ("note.txt", content, "text/plain")},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["filename"] == "note.txt"
    assert body["mime_type"] == "text/plain"
    assert body["processing_state"] == "indexed"  # nothing else to process: a txt with AI indexing off is ready
    assert body["duplicate"] is False
    assert first.headers["x-bento-duplicate"] == "false"

    duplicate = client.post(
        "/api/assets/upload",
        files={"file": ("renamed.txt", content, "text/plain")},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == body["id"]
    assert duplicate.json()["duplicate"] is True
    assert duplicate.headers["x-bento-duplicate"] == "true"

    download = client.get(f"/api/assets/{body['id']}/download")
    assert download.status_code == 200
    assert download.content == content

    deleted = client.delete(f"/api/assets/{body['id']}")
    assert deleted.status_code == 200
    assert client.get(f"/api/assets/{body['id']}").status_code == 404


def test_asset_error_model_for_missing_asset_and_unsupported_preview(tmp_path: Path) -> None:
    data_dir = _migrated_data_dir(tmp_path)
    client = TestClient(create_app(Settings(data_dir=str(data_dir))))

    missing = client.get("/api/assets/asset_missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "asset_not_found"
    assert missing.json()["error"]["request_id"]

    upload = client.post(
        "/api/assets/upload",
        files={"file": ("notes.txt", b"plain text", "text/plain")},
    )
    asset_id = upload.json()["id"]

    preview = client.get(f"/api/assets/{asset_id}/preview")
    assert preview.status_code == 415
    assert preview.json()["error"]["code"] == "unsupported_media_type"


def test_upload_queues_ocr_after_the_thumbnail_when_ocr_is_configured(tmp_path: Path) -> None:
    data_dir = _migrated_data_dir(tmp_path)
    client = TestClient(create_app(Settings(data_dir=str(data_dir), ocr_provider="mock")))
    png = _png_bytes()

    upload = client.post("/api/assets/upload", files={"file": ("scan.png", png, "image/png")})
    assert upload.status_code == 200
    asset_id = upload.json()["id"]

    jobs = [item for item in client.get("/api/jobs").json()["items"] if item.get("asset_id") == asset_id]
    by_type = {item["type"]: item for item in jobs}
    assert {"thumbnail", "ocr"} <= set(by_type)
    assert by_type["thumbnail"]["priority"] < by_type["ocr"]["priority"]
    assert "embedding" not in by_type  # embeddings provider stays disabled


def test_upload_queues_no_ocr_when_ocr_is_disabled(tmp_path: Path) -> None:
    data_dir = _migrated_data_dir(tmp_path)
    client = TestClient(create_app(Settings(data_dir=str(data_dir))))
    upload = client.post("/api/assets/upload", files={"file": ("scan.png", _png_bytes(), "image/png")})
    asset_id = upload.json()["id"]
    types = {item["type"] for item in client.get("/api/jobs").json()["items"] if item.get("asset_id") == asset_id}
    assert "ocr" not in types


def _png_bytes() -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (16, 16), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _migrated_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    db_dir = data_dir / "db"
    db_dir.mkdir(parents=True)
    api_root = Path(__file__).parents[3]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "migrations"))
    config.set_main_option("sqlalchemy.url", sqlite_url(db_dir / "bento.sqlite3"))
    command.upgrade(config, "head")
    return data_dir
