from __future__ import annotations

from fastapi.testclient import TestClient

from bento.adapters.settings import SQLiteSettingsRepository
from bento.application.settings import EditableSettingsService
from bento.infrastructure.db.clock import SystemClock
from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app
from tests.integration.db.support import migrated_session_factory


def _client(tmp_path) -> TestClient:
    data_dir = tmp_path / "data"
    database_dir = data_dir / "db"
    database_dir.mkdir(parents=True)
    repository = SQLiteSettingsRepository(migrated_session_factory(database_dir), SystemClock())
    desktop_environ = {
        "BENTO_DESKTOP_API_TOKEN": "test-token-that-is-at-least-32-characters",
        "BENTO_DESKTOP_ORIGIN": "bento://app",
    }
    app = create_app(
        Settings(data_dir=str(data_dir), runtime_mode="desktop"),
        desktop_environ=desktop_environ,
    )
    app.state.editable_settings_service = EditableSettingsService(
        repository=repository,
        environ={},
        runtime_mode="desktop",
    )
    return TestClient(
        app,
        headers={
            "Authorization": f"Bearer {desktop_environ['BENTO_DESKTOP_API_TOKEN']}",
            "Origin": desktop_environ["BENTO_DESKTOP_ORIGIN"],
        },
    )


def test_settings_contract_supports_schema_validation_apply_and_conflict(tmp_path) -> None:
    client = _client(tmp_path)

    schema = client.get("/api/settings/schema")
    assert schema.status_code == 200
    assert any(field["key"] == "worker_concurrency" for field in schema.json()["fields"])

    values = client.get("/api/settings/values").json()
    assert values["revision"] == 0
    assert values["values"]["telegram_api_hash"] == {
        "source": "default",
        "locked": True,
        "apply_mode": "restart_services",
        "configured": False,
    }

    validation = client.post(
        "/api/settings/validate",
        json={"values": {"worker_concurrency": 2}, "run_probes": False},
    )
    assert validation.json()["valid"] is True
    assert validation.json()["restart_plan"]["mode"] == "restart_worker"

    applied = client.patch(
        "/api/settings/values",
        json={"revision": 0, "values": {"worker_concurrency": 2}},
    )
    assert applied.status_code == 200
    assert applied.json()["revision"] == 1
    assert applied.json()["values"]["worker_concurrency"]["value"] == 2

    conflict = client.patch(
        "/api/settings/values",
        json={"revision": 0, "values": {"worker_concurrency": 3}},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "settings_revision_conflict"


def test_settings_import_and_export_never_echo_secrets(tmp_path) -> None:
    client = _client(tmp_path)
    secret = "this-value-must-never-be-returned"
    preview = client.post(
        "/api/settings/import/preview",
        json={"content": f"BENTO_TELEGRAM_API_HASH={secret}\nWORKER_CONCURRENCY=2"},
    )
    assert preview.status_code == 200
    assert secret not in preview.text
    assert next(item for item in preview.json()["items"] if item["secret"])["configured"] is True

    exported = client.get("/api/settings/export")
    assert exported.status_code == 200
    assert secret not in exported.text
    assert "telegram_api_hash" not in exported.json()["values"]
