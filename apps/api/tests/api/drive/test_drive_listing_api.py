from __future__ import annotations

from io import BytesIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from bento.infrastructure.db.engine import sqlite_url
from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app


def test_drive_items_sort_order_and_folder_item_count(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=str(_migrated_data_dir(tmp_path)))))
    docs = client.post("/api/drive/folders", json={"name": "Docs"}).json()
    client.post("/api/drive/folders", json={"name": "alfa"})
    client.post("/api/drive/folders", json={"name": "inner", "parent_id": docs["id"]})
    client.post("/api/assets/upload", files={"file": ("in.txt", b"x", "text/plain")}, data={"folder_id": docs["id"]})
    client.post("/api/assets/upload", files={"file": ("big.txt", b"y" * 50, "text/plain")})
    client.post("/api/assets/upload", files={"file": ("a.txt", b"z", "text/plain")})

    by_name = client.get("/api/drive/items", params={"sort": "name"}).json()["items"]
    assert [item["name"] for item in by_name] == ["alfa", "Docs", "a.txt", "big.txt"]
    counts = {item["name"]: item["item_count"] for item in by_name if item["type"] == "folder"}
    assert counts == {"alfa": 0, "Docs": 2}
    assert all(item["item_count"] is None for item in by_name if item["type"] == "asset")

    by_size = client.get("/api/drive/items", params={"sort": "size", "order": "desc"}).json()["items"]
    assert [item["name"] for item in by_size] == ["Docs", "alfa", "big.txt", "a.txt"]

    paged = client.get("/api/drive/items", params={"sort": "name", "limit": 3}).json()
    rest = client.get("/api/drive/items", params={"sort": "name", "limit": 3, "cursor": paged["next_cursor"]}).json()
    assert [item["name"] for item in paged["items"] + rest["items"]] == ["alfa", "Docs", "a.txt", "big.txt"]

    invalid = client.get("/api/drive/items", params={"sort": "color"})
    assert invalid.status_code == 422

    files = [item["asset"] for item in by_name if item["type"] == "asset"]
    assert all(asset["locally_available"] is True and asset["offline_pinned"] is False for asset in files)


def test_asset_detail_carries_exif_summary_and_local_state(tmp_path: Path) -> None:
    from PIL import ExifTags, Image

    client = TestClient(create_app(Settings(data_dir=str(_migrated_data_dir(tmp_path)))))
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "Google"
    exif[ExifTags.Base.Model] = "Pixel 8"
    exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.ExposureTime] = 0.004
    exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.ISOSpeedRatings] = 100
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format="JPEG", exif=exif)

    asset_id = client.post("/api/assets/upload", files={"file": ("p.jpg", buffer.getvalue(), "image/jpeg")}).json()["id"]
    body = client.get(f"/api/assets/{asset_id}").json()
    assert body["exif"]["camera_make"] == "Google"
    assert body["exif"]["camera_model"] == "Pixel 8"
    assert body["exif"]["exposure_display"] == "1/250"
    assert body["exif"]["iso"] == 100
    assert body["exif"]["latitude"] is None
    assert body["locally_available"] is True
    assert body["offline_pinned"] is False

    plain = client.post("/api/assets/upload", files={"file": ("n.txt", b"n", "text/plain")}).json()
    assert plain["exif"] is None


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
