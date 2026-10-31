from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bento.adapters.sync import SQLiteSyncStateStore, configure_change_capture
from bento.infrastructure.db.engine import create_session_factory, session_scope, sqlite_url
from bento.infrastructure.db.models import FolderModel
from bento.infrastructure.services import reset_services
from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app
from tests.integration.storage_pipeline.support import migrated_data_dir


@pytest.fixture(autouse=True)
def _isolated() -> Iterator[None]:
    reset_services()
    yield
    reset_services()
    configure_change_capture(False)


def test_sync_is_disabled_for_local_storage(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(storage_backend="local", data_dir=str(tmp_path))))

    status = client.get("/api/sync/status")
    assert status.status_code == 200
    assert status.json() == {
        "state": "disabled",
        "pending_ops": 0,
        "last_push_at": None,
        "last_pull_at": None,
        "bootstrap": None,
        "waiting_until": None,
        "error": None,
    }
    assert client.post("/api/sync/now").json() == {"accepted": False}


def test_status_reflects_the_worker_loop_state_and_pending_ops(tmp_path: Path) -> None:
    data_dir = migrated_data_dir(tmp_path)
    client = TestClient(create_app(Settings(storage_backend="fake", data_dir=str(data_dir))))
    factory = create_session_factory(sqlite_url(data_dir / "db" / "bento.sqlite3"))
    state = SQLiteSyncStateStore(factory)

    async def seed() -> None:
        await state.set_value("capture", json.dumps({"vault_id": "vlt_api", "device_id": "dev_api"}))
        await state.set_value("bootstrap", json.dumps({"done": 120, "total": 480}))
        await state.set_value("loop", json.dumps({"state": "syncing", "waiting_until": None, "error": None}))
        await state.set_value("last_push_at", "2026-04-01T10:00:00+00:00")

    asyncio.run(seed())
    # The API's own writes are captured too (capture is on for non-local storage).
    from datetime import UTC, datetime

    now = datetime(2026, 4, 1, tzinfo=UTC)
    with session_scope(create_session_factory(sqlite_url(data_dir / "db" / "bento.sqlite3"))) as session:
        session.add(FolderModel(id="folder_api", name="Desde la API", created_at=now, updated_at=now))

    body = client.get("/api/sync/status").json()
    assert body["state"] == "bootstrapping"
    assert body["bootstrap"] == {"done": 120, "total": 480}
    assert body["pending_ops"] == 1
    assert body["last_push_at"] == "2026-04-01T10:00:00+00:00"

    asyncio.run(
        state.set_value(
            "loop",
            json.dumps(
                {"state": "waiting", "waiting_until": "2026-04-01T10:05:00+00:00", "error": {"code": "telegram_flood_wait", "message": "x"}}
            ),
        )
    )
    body = client.get("/api/sync/status").json()
    assert body["state"] == "waiting"
    assert body["waiting_until"] == "2026-04-01T10:05:00+00:00"
    assert body["error"] == {"code": "telegram_flood_wait", "message": "Telegram asked to wait before retrying", "details": {}}

    # A clock more than 5 minutes ahead of Telegram's: reported while the loop itself is healthy.
    asyncio.run(state.set_value("clock_skew", json.dumps({"skew_ms": 754_321, "message_id": 7, "at": "2026-04-01T10:00:00+00:00"})))
    asyncio.run(state.set_value("loop", json.dumps({"state": "idle", "waiting_until": None, "error": None})))
    body = client.get("/api/sync/status").json()
    assert body["state"] == "bootstrapping"
    assert body["error"]["code"] == "clock_skew" and "clock" in body["error"]["message"]
    assert body["error"]["details"] == {"direction": "ahead", "skew_seconds": 754}
    activity = client.get("/api/activity").json()
    [item] = [item for item in activity["attention"] if item["kind"] == "clock_skew"]
    assert item == {
        "id": "clock_skew",
        "kind": "clock_skew",
        "title_key": "activity.attention.clock_skew",
        "params": {"direction": "ahead", "skew_seconds": 754, "skew_minutes": 13},
        "action": "none",
    }

    asyncio.run(state.set_value("device_removed", json.dumps({"device_id": "dev_api", "epoch": 2})))
    body = client.get("/api/sync/status").json()
    assert body["state"] == "paused" and body["bootstrap"] is None
    assert body["error"]["code"] == "device_removed" and "removed" in body["error"]["message"]


def test_sync_now_leaves_a_marker_for_the_worker(tmp_path: Path) -> None:
    data_dir = migrated_data_dir(tmp_path)
    client = TestClient(create_app(Settings(storage_backend="fake", data_dir=str(data_dir))))

    response = client.post("/api/sync/now")

    assert response.status_code == 200 and response.json() == {"accepted": True}
    marker = asyncio.run(
        SQLiteSyncStateStore(create_session_factory(sqlite_url(data_dir / "db" / "bento.sqlite3"))).get_value("sync_requested_at")
    )
    assert marker is not None
