from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app
from tests.api.assets.test_assets_api import _migrated_data_dir


def test_album_detail_and_item_removal_match_the_web_client(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=str(_migrated_data_dir(tmp_path)), storage_backend="local")))
    photo = client.post(
        "/api/assets/upload", files={"file": ("playa.txt", b"not really a photo", "text/plain")}, data={"mode": "photos"}
    ).json()
    album = client.post("/api/photos/albums", json={"title": "Vacaciones"}).json()
    client.post(f"/api/photos/albums/{album['id']}/items", json={"asset_id": photo["id"]})

    detail = client.get(f"/api/photos/albums/{album['id']}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "Vacaciones" and detail.json()["asset_ids"] == [photo["id"]]

    removed = client.delete(f"/api/photos/albums/{album['id']}/items/{photo['id']}")
    assert removed.status_code == 200 and removed.json()["asset_ids"] == []
    assert client.get(f"/api/photos/albums/{album['id']}").json()["asset_ids"] == []

    missing = client.get("/api/photos/albums/album_missing")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "album_not_found"
    assert client.delete(f"/api/photos/albums/album_missing/items/{photo['id']}").status_code == 404


def test_album_rename_cover_and_delete_keep_the_photos(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=str(_migrated_data_dir(tmp_path)), storage_backend="local")))
    photo = client.post(
        "/api/assets/upload", files={"file": ("playa.txt", b"photo bytes", "text/plain")}, data={"mode": "photos"}
    ).json()
    other = client.post("/api/assets/upload", files={"file": ("otro.txt", b"other", "text/plain")}).json()
    album = client.post("/api/photos/albums", json={"title": "Vacaciones"}).json()
    client.post(f"/api/photos/albums/{album['id']}/items", json={"asset_id": photo["id"]})

    renamed = client.patch(f"/api/photos/albums/{album['id']}", json={"title": "Playa 2026"})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Playa 2026"
    assert renamed.json()["cover_asset_id"] is None

    cover = client.patch(f"/api/photos/albums/{album['id']}", json={"cover_asset_id": photo["id"]})
    assert cover.json()["cover_asset_id"] == photo["id"] and cover.json()["title"] == "Playa 2026"
    assert client.get(f"/api/photos/albums/{album['id']}").json()["cover_asset_id"] == photo["id"]
    not_member = client.patch(f"/api/photos/albums/{album['id']}", json={"cover_asset_id": other["id"]})
    assert not_member.status_code == 400 and not_member.json()["error"]["code"] == "validation_failed"
    assert client.patch(f"/api/photos/albums/{album['id']}", json={}).status_code == 400
    assert client.patch(f"/api/photos/albums/{album['id']}", json={"title": "  "}).status_code == 400
    cleared = client.patch(f"/api/photos/albums/{album['id']}", json={"cover_asset_id": None})
    assert cleared.json()["cover_asset_id"] is None

    deleted = client.delete(f"/api/photos/albums/{album['id']}")
    assert deleted.status_code == 200 and deleted.json()["deleted_at"] is not None
    assert client.get(f"/api/photos/albums/{album['id']}").status_code == 404
    assert all(item["id"] != album["id"] for item in client.get("/api/photos/albums").json()["items"])
    assert client.get(f"/api/assets/{photo['id']}").status_code == 200
    assert client.delete("/api/photos/albums/album_missing").status_code == 404
    assert client.patch("/api/photos/albums/album_missing", json={"title": "x"}).status_code == 404
