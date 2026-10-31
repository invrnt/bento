from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app
from tests.integration.storage_pipeline.support import RemoteSwitch, migrated_data_dir, pipeline_for


def test_activity_snapshot_for_an_idle_and_a_busy_library(tmp_path: Path) -> None:
    data_dir = migrated_data_dir(tmp_path)
    components = pipeline_for(data_dir, RemoteSwitch(None), storage_backend="local")
    app = create_app(Settings(data_dir=str(data_dir)))
    app.state.storage_pipeline = components
    client = TestClient(app)

    idle = {"active": 0, "queued": 0, "bytes_total": 0, "bytes_done": 0, "eta_seconds": None}
    assert client.get("/api/activity").json() == {
        "summary": "up_to_date",
        "uploads": idle,
        "downloads": idle,
        "attention": [],
    }

    folder = tmp_path / "Docs"
    folder.mkdir()
    (folder / "a.txt").write_text("abc")
    client.post("/api/backup/sources", json={"path": str(folder)})
    asyncio.run(components.backup.scan_source(client.get("/api/backup/sources").json()["items"][0]["id"]))
    busy = client.get("/api/activity").json()
    assert busy["summary"] == "uploading"
    assert busy["uploads"]["queued"] == 1 and busy["uploads"]["bytes_total"] == 3

    client.patch("/api/backup/policy", json={"paused": True})
    assert client.get("/api/activity").json()["summary"] == "paused"
