from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app
from tests.integration.storage_pipeline.support import (
    JobRunner,
    RemoteSwitch,
    migrated_data_dir,
    pipeline_for,
    vault_remote_store,
)


def test_delete_moves_to_trash_and_the_trash_id_restores_or_purges(tmp_path: Path) -> None:
    data_dir = migrated_data_dir(tmp_path)
    store = asyncio.run(vault_remote_store(tmp_path))
    components = pipeline_for(data_dir, RemoteSwitch(store))
    app = create_app(Settings(data_dir=str(data_dir), storage_backend="fake"))
    app.state.storage_pipeline = components
    client = TestClient(app)

    asset = client.post("/api/assets/upload", files={"file": ("foto.jpg", b"\xff\xd8\xff" + b"x" * 64, "image/jpeg")}).json()
    folder = client.post("/api/drive/folders", json={"name": "Viejos"}).json()
    asyncio.run(JobRunner(components).run_all())

    assert client.delete(f"/api/assets/{asset['id']}").status_code == 200
    assert client.delete(f"/api/drive/folders/{folder['id']}").status_code == 200
    listing = client.get("/api/trash").json()
    assert listing["next_cursor"] is None
    items = {item["id"]: item for item in listing["items"]}
    assert set(items) == {asset["id"], folder["id"]}
    assert items[asset["id"]]["type"] == "asset" and items[asset["id"]]["name"] == "foto.jpg"
    assert items[asset["id"]]["thumbnail_url"] is None  # no thumbnail generated in this test
    assert items[folder["id"]] == {
        "id": folder["id"],
        "type": "folder",
        "name": "Viejos",
        "size_bytes": 0,
        "deleted_at": items[folder["id"]]["deleted_at"],
        "purge_at": items[folder["id"]]["purge_at"],
        "thumbnail_url": None,
    }
    assert client.get("/api/trash", params={"limit": 1}).json()["next_cursor"] == "1"

    assert client.post("/api/trash/restore", json={"ids": [asset["id"]]}).json() == {"restored": 1}
    assert client.get(f"/api/assets/{asset['id']}").status_code == 200

    client.delete(f"/api/assets/{asset['id']}")
    purged = client.post("/api/trash/purge", json={"ids": [asset["id"]]}).json()
    assert purged == {"purged": 1, "deferred": []}
    assert len(store.deleted) == 1
    assert client.get(f"/api/assets/{asset['id']}/content").status_code == 404
    assert client.post("/api/trash/empty").json() == {"purged": 1, "deferred": []}
    assert client.get("/api/trash").json() == {"items": [], "next_cursor": None}
