from __future__ import annotations

import asyncio
import math
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bento.application.smart_search.activation import DownloadJobResult
from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app
from tests.fakes.model_host import BLOB_SIZE, FakeModelHost, running_model_host
from tests.integration.db.support import migrated_session_factory
from tests.unit.models.model_fakes import ServiceKit, files_under, make_kit

STATUS_KEYS = {
    "state",
    "waiting_network",
    "error_code",
    "failed_step",
    "space_id",
    "download",
    "indexing",
    "model",
    "free_bytes",
    "update_available",
    "locked",
    "search_available",
    "can_use_now",
    "suggest_in_onboarding",
}


@pytest.fixture
def host() -> Iterator[FakeModelHost]:
    with running_model_host() as server:
        yield server


def client_for(tmp_path: Path, kit: ServiceKit) -> TestClient:
    app = create_app(Settings(data_dir=str(tmp_path / "data")))
    app.state.smart_search_activation = kit.service
    return TestClient(app)


def wait_until(predicate: Any, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached in time")
        time.sleep(0.005)


def test_journey_activate_pause_resume_verify_start_index_ready_remove(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)
    client = client_for(tmp_path, kit)
    space_id = kit.spec.space().id

    initial = client.get("/api/smart-search")
    assert initial.status_code == 200
    body = initial.json()
    assert set(body) == STATUS_KEYS
    assert body["state"] == "off"
    assert body["space_id"] is None
    assert body["search_available"] is False
    assert body["locked"] is False
    assert body["update_available"] is None
    assert body["model"] == {
        "model_id": "embeddinggemma-2-q8_0",
        "display_name": "EmbeddingGemma 2",
        "license_spdx": "Apache-2.0",
        "license_url": "/api/smart-search/license",
        "size_bytes": BLOB_SIZE,
        "download_host": "primary.bento.example",
        "dims": 512,
    }
    assert body["free_bytes"] > 0

    activated = client.post("/api/smart-search/activate", json={})
    assert activated.status_code == 200
    assert activated.json()["state"] == "downloading"
    assert activated.json()["space_id"] == space_id
    assert activated.json()["download"] == {"bytes_done": 0, "bytes_total": BLOB_SIZE}
    assert kit.switch.value == "managed"

    # The worker runs the job on a slow link; the person pauses it mid-way.
    host.behavior.trickle_delay = 0.004
    results: list[DownloadJobResult] = []
    worker = threading.Thread(target=lambda: results.append(asyncio.run(kit.run_last_job())))
    worker.start()
    wait_until(lambda: client.get("/api/smart-search").json()["download"]["bytes_done"] > 0)

    paused = client.post("/api/smart-search/pause")
    assert paused.status_code == 200
    assert paused.json()["state"] == "paused"
    worker.join(timeout=10)
    assert results == [DownloadJobResult.STOPPED]
    done = client.get("/api/smart-search").json()["download"]["bytes_done"]
    assert 0 < done < BLOB_SIZE

    resumed = client.post("/api/smart-search/resume")
    assert resumed.status_code == 200
    assert resumed.json()["state"] == "downloading"
    assert resumed.json()["download"]["bytes_done"] == done

    # Observe `verifying` through the API while the store re-checks the hash.
    seen_while_verifying: list[str] = []
    real_verify = kit.store.verify

    def observing_verify(spec: Any) -> bool:
        seen_while_verifying.append(client.get("/api/smart-search").json()["state"])
        return real_verify(spec)

    kit.store.verify = observing_verify  # type: ignore[method-assign]
    host.behavior.trickle_delay = 0.0
    assert asyncio.run(kit.run_last_job()) is DownloadJobResult.STARTING
    assert seen_while_verifying[-1] == "verifying"

    starting = client.get("/api/smart-search").json()
    assert starting["state"] == "starting"
    assert starting["download"] == {"bytes_done": BLOB_SIZE, "bytes_total": BLOB_SIZE}
    assert kit.hooks.started and kit.hooks.started[0][0] == space_id

    # Fake runtime and indexing ports from here on.
    asyncio.run(kit.service.runtime_ready(space_id))
    asyncio.run(kit.service.index_progress(space_id, 20, 20))
    indexing = client.get("/api/smart-search").json()
    assert indexing["state"] == "indexing"
    assert indexing["indexing"] == {"done": 20, "total": 20}
    assert indexing["search_available"] is True
    asyncio.run(kit.service.indexed(space_id))
    ready = client.get("/api/smart-search").json()
    assert ready["state"] == "ready"
    assert ready["search_available"] is True

    removed = client.delete("/api/smart-search/model")
    assert removed.status_code == 200
    assert removed.json()["state"] == "off"
    assert removed.json()["search_available"] is False
    assert files_under(kit.store.root) == []
    assert kit.switch.value == "disabled"
    assert kit.hooks.stopped_spaces == [space_id]


@pytest.mark.parametrize(
    ("method", "path", "event"),
    [
        ("post", "/api/smart-search/pause", "pause"),
        ("post", "/api/smart-search/resume", "resume"),
        ("post", "/api/smart-search/retry", "retry"),
        ("post", "/api/smart-search/cancel", "cancel"),
        ("post", "/api/smart-search/update", "update"),
        ("post", "/api/smart-search/use-now", "use_now"),
        ("delete", "/api/smart-search/model", "remove"),
    ],
)
def test_actions_in_the_wrong_state_are_409(
    tmp_path: Path, host: FakeModelHost, method: str, path: str, event: str
) -> None:
    client = client_for(tmp_path, make_kit(tmp_path, host))

    response = getattr(client, method)(path)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "smart_search_state_conflict"
    assert error["details"] == {"state": "off", "event": event}
    assert error["request_id"]


def test_activate_twice_is_409(tmp_path: Path, host: FakeModelHost) -> None:
    client = client_for(tmp_path, make_kit(tmp_path, host))

    assert client.post("/api/smart-search/activate").status_code == 200
    again = client.post("/api/smart-search/activate", json={})

    assert again.status_code == 409
    assert again.json()["error"]["details"] == {"state": "downloading", "event": "activate"}


def test_activate_validates_the_model_and_dims(tmp_path: Path, host: FakeModelHost) -> None:
    client = client_for(tmp_path, make_kit(tmp_path, host))

    bad_dims = client.post("/api/smart-search/activate", json={"dims": 300})
    assert bad_dims.status_code == 400
    assert bad_dims.json()["error"]["code"] == "invalid_model_spec"
    assert bad_dims.json()["error"]["details"]["allowed"] == [768, 512, 256, 128]

    unknown = client.post("/api/smart-search/activate", json={"model_id": "unknown-model"})
    assert unknown.status_code == 400
    assert unknown.json()["error"]["code"] == "invalid_model_spec"

    assert client.post("/api/smart-search/activate", json={"model_id": "Not An Id"}).status_code == 422
    assert client.post("/api/smart-search/activate", json={"dims": 0}).status_code == 422
    assert client.get("/api/smart-search").json()["state"] == "off"

    chosen = client.post("/api/smart-search/activate", json={"model_id": "embeddinggemma-2-q8_0", "dims": 256})
    assert chosen.status_code == 200
    assert chosen.json()["space_id"].endswith("/256")
    assert chosen.json()["model"]["dims"] == 256


def test_activate_without_space_is_409_with_the_numbers(tmp_path: Path, host: FakeModelHost) -> None:
    client = client_for(tmp_path, make_kit(tmp_path, host, free_bytes=1000))

    response = client.post("/api/smart-search/activate")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "smart_search_no_space"
    assert error["details"] == {"required_bytes": BLOB_SIZE + math.ceil(BLOB_SIZE * 0.10), "free_bytes": 1000}


def test_env_locked_provider_is_reported_and_refused(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)
    kit.switch.is_locked = True
    client = client_for(tmp_path, kit)

    assert client.get("/api/smart-search").json()["locked"] is True
    response = client.post("/api/smart-search/activate")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "settings_source_locked"


def test_cancel_from_error_returns_to_off(tmp_path: Path, host: FakeModelHost) -> None:
    kit = make_kit(tmp_path, host)
    client = client_for(tmp_path, kit)
    host.behavior.wrong_body = True
    client.post("/api/smart-search/activate")
    assert asyncio.run(kit.run_last_job()) is DownloadJobResult.FAILED

    errored = client.get("/api/smart-search").json()
    assert (errored["state"], errored["error_code"], errored["failed_step"]) == ("error", "checksum", "verifying")
    assert errored["search_available"] is False

    retried = client.post("/api/smart-search/retry")
    assert retried.json()["state"] == "downloading"
    assert retried.json()["download"]["bytes_done"] == 0

    cancelled = client.post("/api/smart-search/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "off"
    assert files_under(kit.store.root) == []


def test_license_is_served_as_plain_text(tmp_path: Path, host: FakeModelHost) -> None:
    client = client_for(tmp_path, make_kit(tmp_path, host))

    response = client.get("/api/smart-search/license")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "Apache License" in response.text
    assert "Version 2.0, January 2004" in response.text


def test_default_wiring_reads_the_packaged_manifest_and_the_database(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "db").mkdir(parents=True)
    migrated_session_factory(data_dir / "db")
    client = TestClient(create_app(Settings(data_dir=str(data_dir))))

    response = client.get("/api/smart-search")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "off"
    assert body["locked"] is False
    assert body["model"]["model_id"] == "embeddinggemma-2-q8_0"
    assert body["model"]["size_bytes"] == 309_855_456
    assert body["model"]["download_host"] == "huggingface.co"
    assert body["model"]["dims"] == 512


def test_openapi_lists_every_smart_search_endpoint(tmp_path: Path) -> None:
    paths = create_app(Settings(data_dir=str(tmp_path / "data"))).openapi()["paths"]

    assert {"get"} <= set(paths["/api/smart-search"])
    for action in ("activate", "pause", "resume", "retry", "cancel", "update", "use-now"):
        assert "post" in paths[f"/api/smart-search/{action}"]
    assert "delete" in paths["/api/smart-search/model"]
    assert "get" in paths["/api/smart-search/license"]
