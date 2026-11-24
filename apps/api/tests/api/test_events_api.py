from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from bento.adapters.repositories.change_signatures import SQLiteChangeSignatures
from bento.application.events import ChangeTopic
from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app
from tests.api.assets.test_assets_api import _migrated_data_dir


def test_events_stream_is_sse_and_validates_topics(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=str(_migrated_data_dir(tmp_path)))))
    with client.stream("GET", "/api/events", params={"topics": "library,jobs", "max_seconds": 1}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-store"
        body = "".join(response.iter_text())
    assert body.startswith("retry: 3000\n\n")
    blocks = [block for block in body.split("\n\n") if block.startswith("event:")]
    event, data = blocks[0].split("\n")
    assert event == "event: ready" and json.loads(data.removeprefix("data: ")) == {"topics": ["jobs", "library"]}

    bad = client.get("/api/events", params={"topics": "weather"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "validation_failed"


def test_signatures_move_when_the_library_and_jobs_change(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=str(_migrated_data_dir(tmp_path))))
    client = TestClient(app)
    client.get("/api/drive/items")
    from bento.interfaces.http.routes_content import pipeline

    class _Request:
        def __init__(self) -> None:
            self.app = app

    signatures = SQLiteChangeSignatures(pipeline(_Request()).session_factory)  # type: ignore[arg-type]
    topics = frozenset(ChangeTopic)
    before = asyncio.run(signatures.signatures(topics))
    client.post("/api/assets/upload", files={"file": ("a.txt", b"hello", "text/plain")})
    after = asyncio.run(signatures.signatures(topics))
    assert after[ChangeTopic.LIBRARY] != before[ChangeTopic.LIBRARY]
    assert after[ChangeTopic.IMPORTS] == before[ChangeTopic.IMPORTS]
    client.post("/api/drive/folders", json={"name": "Docs"})
    assert asyncio.run(signatures.signatures(topics))[ChangeTopic.LIBRARY] != after[ChangeTopic.LIBRARY]
