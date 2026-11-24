"""CLI-support Drive path routes on a real (temporary) SQLite database."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from bento.infrastructure.db.engine import sqlite_url
from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    data_dir = tmp_path / "data"
    db_dir = data_dir / "db"
    db_dir.mkdir(parents=True)
    api_root = Path(__file__).parents[3]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "migrations"))
    config.set_main_option("sqlalchemy.url", sqlite_url(db_dir / "bento.sqlite3"))
    command.upgrade(config, "head")
    return TestClient(create_app(Settings(data_dir=str(data_dir))))


def _folder(client: TestClient, name: str, parent_id: str | None = None) -> dict[str, Any]:
    response = client.post("/api/drive/folders", json={"name": name, "parent_id": parent_id})
    assert response.status_code == 200, response.text
    return response.json()


def _upload(client: TestClient, name: str, content: bytes, folder_id: str | None = None) -> dict[str, Any]:
    data = {"folder_id": folder_id} if folder_id else {}
    response = client.post("/api/assets/upload", files={"file": (name, content, "text/plain")}, data=data)
    assert response.status_code == 200, response.text
    return response.json()


def _error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code and error["request_id"]
    return error


def test_resolve_root_folder_asset_and_id(client: TestClient) -> None:
    docs = _folder(client, "Docs")
    year = _folder(client, "2026", docs["id"])
    asset = _upload(client, "nota.txt", b"hola", year["id"])

    root = client.get("/api/drive/resolve", params={"path": "/"}).json()
    assert root == {"kind": "root", "path": "/", "folder": None, "asset": None, "breadcrumbs": []}
    assert client.get("/api/drive/resolve").json()["kind"] == "root"

    folder = client.get("/api/drive/resolve", params={"path": "/Docs/2026/"}).json()
    assert folder["kind"] == "folder" and folder["path"] == "/Docs/2026"
    assert folder["folder"]["id"] == year["id"] and folder["folder"]["parent_id"] == docs["id"]
    assert folder["breadcrumbs"] == [{"id": docs["id"], "name": "Docs"}, {"id": year["id"], "name": "2026"}]

    found = client.get("/api/drive/resolve", params={"path": "Docs/2026/nota.txt"}).json()
    assert found["kind"] == "asset" and found["folder"] is None
    assert found["asset"]["id"] == asset["id"] and found["asset"]["thumbnail_url"] is None
    assert found["asset"] == client.get(f"/api/assets/{asset['id']}").json()  # same AssetResponse builder

    by_id = client.get("/api/drive/resolve", params={"path": f"id:{asset['id']}"}).json()
    assert by_id["path"] == "/Docs/2026/nota.txt" and len(by_id["breadcrumbs"]) == 2


def test_resolve_errors(client: TestClient) -> None:
    docs = _folder(client, "Docs")
    duplicate = _folder(client, "Docs")
    error = _error(client.get("/api/drive/resolve", params={"path": "/Docs"}), 409, "path_ambiguous")
    assert error["details"]["path"] == "/Docs"
    assert [c["id"] for c in error["details"]["candidates"]] == [docs["id"], duplicate["id"]]
    assert all(c["kind"] == "folder" and c["path"] == "/Docs" and c["created_at"] for c in error["details"]["candidates"])

    error = _error(client.get("/api/drive/resolve", params={"path": "/Nada/x"}), 404, "path_not_found")
    assert error["details"] == {"path": "/Nada/x", "missing_from": 0}
    _error(client.get("/api/drive/resolve", params={"path": "id:folder_missing"}), 404, "path_not_found")

    error = _error(client.get("/api/drive/resolve", params={"path": "/a/../b"}), 400, "validation_failed")
    assert error["details"] == {"reason": "dot_segment"}
    _error(client.get("/api/drive/resolve", params={"path": "/a//b"}), 400, "validation_failed")


def test_trashed_items_are_ignored(client: TestClient) -> None:
    old = _folder(client, "Docs")
    assert client.delete(f"/api/drive/folders/{old['id']}").status_code == 200
    new = _folder(client, "Docs")
    assert client.get("/api/drive/resolve", params={"path": "/Docs"}).json()["folder"]["id"] == new["id"]
    asset = _upload(client, "x.txt", b"x")
    assert client.delete(f"/api/assets/{asset['id']}").status_code == 200
    _error(client.get("/api/drive/resolve", params={"path": "/x.txt"}), 404, "path_not_found")


def test_ensure_creates_reuses_oldest_and_is_idempotent(client: TestClient) -> None:
    first = client.post("/api/drive/folders/ensure", json={"path": "/Fotos/2026/Enero"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["path"] == "/Fotos/2026/Enero" and len(body["created"]) == 3
    assert body["folder"]["name"] == "Enero" and body["folder"]["id"] == body["created"][-1]

    again = client.post("/api/drive/folders/ensure", json={"path": "Fotos/2026/Enero/"}).json()
    assert again["created"] == [] and again["folder"]["id"] == body["folder"]["id"]

    fotos_id = body["created"][0]
    _folder(client, "Fotos")  # a newer duplicate never wins and never causes path_ambiguous
    reused = client.post("/api/drive/folders/ensure", json={"path": "/Fotos/2026/Febrero"}).json()
    assert len(reused["created"]) == 1
    assert client.get("/api/drive/resolve", params={"path": f"id:{reused['folder']['id']}"}).json()["breadcrumbs"][0]["id"] == fotos_id

    root = client.post("/api/drive/folders/ensure", json={"path": "/"}).json()
    assert root == {"folder": None, "path": "/", "created": []}
    # Folders created by ensure appear in the regular Drive listing (same use case as the UI).
    listing = client.get("/api/drive/items").json()["items"]
    assert sum(1 for item in listing if item["name"] == "Fotos") == 2
    _error(client.post("/api/drive/folders/ensure", json={"path": "/a/./b"}), 400, "validation_failed")


def test_tree_depth_ordering_and_truncation(client: TestClient) -> None:
    docs = _folder(client, "docs")
    _folder(client, "Archivo")
    deep = _folder(client, "deep", docs["id"])
    _folder(client, "deeper", deep["id"])
    _upload(client, "b.txt", b"b")
    _upload(client, "A.txt", b"a")

    tree = client.get("/api/drive/tree", params={"depth": 2}).json()
    assert tree["truncated"] is False and tree["nodes"] == 6
    root = tree["root"]
    assert root["kind"] == "root" and root["id"] is None and root["path"] == "/"
    assert [child["name"] for child in root["children"]] == ["Archivo", "docs", "A.txt", "b.txt"]
    assert root["children"][0]["children"] == []
    deep_node = root["children"][1]["children"][0]
    assert deep_node["path"] == "/docs/deep" and deep_node["has_more"] is True and "children" not in deep_node
    asset_node = root["children"][2]
    assert asset_node["kind"] == "asset" and asset_node["size_bytes"] == 1 and asset_node["mime_type"] == "text/plain"
    assert asset_node["created_at"] and "children" not in asset_node

    sub = client.get("/api/drive/tree", params={"path": "/docs", "depth": 5, "include_assets": "false"}).json()
    assert sub["root"]["kind"] == "folder" and sub["root"]["children"][0]["children"][0]["name"] == "deeper"

    truncated = client.get("/api/drive/tree", params={"max_nodes": 3}).json()
    assert truncated["truncated"] is True and truncated["nodes"] == 3 and truncated["root"]["has_more"] is True

    _error(client.get("/api/drive/tree", params={"depth": 21}), 400, "validation_failed")
    _error(client.get("/api/drive/tree", params={"max_nodes": 0}), 400, "validation_failed")
    _error(client.get("/api/drive/tree", params={"path": "/nada"}), 404, "path_not_found")


def test_paths_for_ids(client: TestClient) -> None:
    docs = _folder(client, "Docs")
    slash = _folder(client, "a/b", docs["id"])
    asset = _upload(client, "nota.txt", b"n", slash["id"])
    response = client.post("/api/drive/paths", json={"ids": [asset["id"], docs["id"], "missing_id"]})
    assert response.status_code == 200
    assert response.json() == {
        "paths": {asset["id"]: "/Docs/a\\/b/nota.txt", docs["id"]: "/Docs"},
        "missing": ["missing_id"],
    }
    _error(client.post("/api/drive/paths", json={"ids": ["x"] * 501}), 400, "validation_failed")


def test_lookup_sha256(client: TestClient) -> None:
    docs = _folder(client, "Docs")
    content = b"contenido privado"
    asset = _upload(client, "doc.txt", content, docs["id"])
    digest = hashlib.sha256(content).hexdigest()
    absent = "0" * 64
    response = client.post("/api/assets/lookup", json={"sha256": [digest, absent]})
    assert response.status_code == 200
    items = response.json()["items"]
    assert list(items) == [digest]
    assert items[digest]["asset"]["id"] == asset["id"] and items[digest]["path"] == "/Docs/doc.txt"

    assert client.delete(f"/api/assets/{asset['id']}").status_code == 200
    assert client.post("/api/assets/lookup", json={"sha256": [digest]}).json() == {"items": {}}
    _error(client.post("/api/assets/lookup", json={"sha256": [digest.upper()]}), 400, "validation_failed")
    _error(client.post("/api/assets/lookup", json={"sha256": [absent] * 501}), 400, "validation_failed")
