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
