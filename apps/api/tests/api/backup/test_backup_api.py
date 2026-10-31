from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from bento.adapters.backup.suggestions import OsBackupSuggestions
from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app
from tests.integration.storage_pipeline.support import RemoteSwitch, migrated_data_dir, pipeline_for


def _client(tmp_path: Path) -> tuple[TestClient, object]:
    data_dir = migrated_data_dir(tmp_path)
    components = pipeline_for(data_dir, RemoteSwitch(None), storage_backend="local")
    app = create_app(Settings(data_dir=str(data_dir)))
    app.state.storage_pipeline = components
    return TestClient(app), components


def test_backup_sources_crud_and_validation(tmp_path: Path) -> None:
    client, components = _client(tmp_path)
    folder = tmp_path / "Imágenes"
    folder.mkdir()

    created = client.post("/api/backup/sources", json={"path": str(folder)})
    assert created.status_code == 200
    body = created.json()
    assert set(body) == {
        "id", "path", "label", "enabled", "state", "files_total", "files_done",
        "files_pending", "bytes_pending", "last_scan_at", "error",
    }
    assert body["label"] == "Imágenes" and body["enabled"] is True and body["state"] == "scanning"

    for path, reason in (
        (str(folder), "duplicate"),
        (str(tmp_path), "overlap"),
        (str(tmp_path / "nope"), "not_found"),
        (str(components.data_dir), "inside_data_dir"),
        ("relative/dir", "not_absolute"),
        ("/", "filesystem_root"),
    ):
        rejected = client.post("/api/backup/sources", json={"path": path})
        assert rejected.status_code == 400, path
        assert rejected.json()["error"]["code"] == "backup_source_invalid"
        assert rejected.json()["error"]["details"] == {"reason": reason}

    patched = client.patch(f"/api/backup/sources/{body['id']}", json={"enabled": False, "label": "Fotos"})
    assert patched.json()["enabled"] is False and patched.json()["label"] == "Fotos"
    assert patched.json()["state"] == "paused"
    assert client.post(f"/api/backup/sources/{body['id']}/scan").json()["id"] == body["id"]
    assert [item["id"] for item in client.get("/api/backup/sources").json()["items"]] == [body["id"]]
    assert client.delete(f"/api/backup/sources/{body['id']}").json() == {"removed": True}
    assert client.get("/api/backup/sources").json() == {"items": []}
    missing = client.delete("/api/backup/sources/bsrc_missing")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "backup_source_not_found"


def test_backup_policy_and_power(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    assert client.get("/api/backup/policy").json() == {
        "paused": False,
        "pause_on_battery": True,
        "bandwidth_limit_kbps": 0,
        "on_battery": False,
        "effective_paused": False,
    }
    on_battery = client.post("/api/backup/power", json={"on_battery": True}).json()
    assert on_battery["on_battery"] is True and on_battery["effective_paused"] is True
    patched = client.patch("/api/backup/policy", json={"pause_on_battery": False, "bandwidth_limit_kbps": 2048}).json()
    assert patched["effective_paused"] is False and patched["bandwidth_limit_kbps"] == 2048
    assert client.patch("/api/backup/policy", json={"paused": True}).json()["effective_paused"] is True
    assert client.patch("/api/backup/policy", json={"bandwidth_limit_kbps": -1}).status_code == 422
    values = client.get("/api/settings/values").json()["values"]
    assert values["backup_bandwidth_limit_kbps"]["value"] == 2048
    assert values["backup_pause_on_battery"]["value"] is False


def test_backup_suggestions_list_existing_folders(tmp_path: Path) -> None:
    client, components = _client(tmp_path)
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True)
    components.backup._suggestions = OsBackupSuggestions(home=home, platform="darwin", environ={})  # noqa: SLF001

    assert client.get("/api/backup/suggestions").json() == {
        "items": [{"path": str((home / "Documents").resolve()), "label": "Documents", "kind": "documents"}]
    }
