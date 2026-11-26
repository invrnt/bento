"""Smart search activation and removal take effect without restarting the API or the worker (bug 1 of the
2026-11-26 real-model exit check, `orchestration/execution/evidence/smart-search-real-model-2026-11-26.md`).

The API app and the worker are both built while `embeddings_provider` is `disabled`, with the production
wiring (`create_app`, `_create_dispatcher`, `_worker_embedding`). Only the outside world is faked: the model host
(`tests/fakes/model_host.py`), the packaged catalog (the tiny blob in place of the 310 MB GGUF) and llama-server
(`tests/fakes/fake_llama_server_bin.py`, a real child process on a Unix socket).
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bento.application.smart_search.runtime import endpoint_file_path, read_endpoint_file
from bento.infrastructure.settings import Settings
from bento.infrastructure.storage_pipeline import reset_storage_pipeline
from bento.interfaces.http.main import create_app
from bento.interfaces.worker import main as worker_main
from tests.fakes.model_host import FakeModelHost, running_model_host
from tests.integration.db.support import migrated_session_factory
from tests.unit.models.model_fakes import fake_host_downloader, tiny_catalog

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fake llama-server listens on a Unix socket")

FAKE_BIN = Path(__file__).parents[2] / "fakes" / "fake_llama_server_bin.py"
FAKE_DIMS = 768  # EmbeddingGemma 2 native dims; the space truncates to 512


@pytest.fixture
def host() -> Iterator[FakeModelHost]:
    with running_model_host() as server:
        yield server


@pytest.fixture
def data_dir() -> Iterator[Path]:
    """Short, so the Unix socket under `<data_dir>/run/` fits the 108-byte limit."""
    path = Path(tempfile.mkdtemp(prefix="bento-ss-", dir="/tmp" if os.path.isdir("/tmp") else None))
    yield path / "data"
    shutil.rmtree(path, ignore_errors=True)


class Stack:
    """One device: the API (TestClient) and the worker (dispatcher + runtime supervisor + space janitor) side by
    side on one data dir, both built once while smart search is off."""

    def __init__(self, data_dir: Path, host: FakeModelHost, monkeypatch: pytest.MonkeyPatch) -> None:
        (data_dir / "db").mkdir(parents=True)
        migrated_session_factory(data_dir / "db")
        wrapper = data_dir.parent / "llama-server"
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_BIN}" "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)
        self.catalog = tiny_catalog(host.blob)
        monkeypatch.setattr("bento.infrastructure.models.packaged_model_catalog", lambda: self.catalog)
        monkeypatch.setattr(
            "bento.adapters.models.http_downloader.HttpModelDownloader", lambda **_: fake_host_downloader(host)
        )
        monkeypatch.setattr(worker_main, "_WORKER_EMBEDDINGS", {})
        self.settings = Settings(
            data_dir=str(data_dir),
            storage_backend="local",
            embeddings_provider="disabled",
            ocr_provider="disabled",
            llama_server_path=str(wrapper),
        )
        spec = self.catalog.default()
        self.weights = data_dir / "models" / spec.model_id / spec.revision / spec.weights.name
        self.control_fake_server()
        self.endpoint_file = endpoint_file_path(data_dir)

        self.client = TestClient(create_app(self.settings))
        self.embedding = worker_main._worker_embedding(self.settings)
        self.dispatcher = worker_main._create_dispatcher("worker-test", self.settings)
        self.janitor = worker_main._space_janitor(self.settings)

    @property
    def runtime(self) -> Any:
        assert self.embedding.runtime is not None, "the worker must own a runtime even while smart search is off"
        return self.embedding.runtime

    def status(self) -> dict[str, Any]:
        response = self.client.get("/api/smart-search")
        assert response.status_code == 200
        return dict(response.json())

    def search(self, query: str) -> list[dict[str, Any]]:
        response = self.client.get("/api/search", params={"q": query})
        assert response.status_code == 200
        return list(response.json()["items"])

    def launches(self) -> int:
        path = Path(f"{self.weights}.launches.jsonl")
        return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0

    def drain(self) -> None:
        async def loop() -> None:
            while await self.dispatcher.process_one():
                pass
            await self.runtime.tick()

        asyncio.run(loop())

    def control_fake_server(self) -> None:
        """`<weights>.fake.json` tells the fake server its vector size (removal deletes the model folder)."""
        self.weights.parent.mkdir(parents=True, exist_ok=True)
        Path(f"{self.weights}.fake.json").write_text(json.dumps({"dims": FAKE_DIMS}), encoding="utf-8")

    def work_until(self, done: Callable[[], bool], *, timeout: float = 30.0) -> None:
        """What `run_worker` does, one step at a time: one job, then one supervisor tick."""

        async def loop() -> None:
            deadline = time.monotonic() + timeout
            while not done():
                if time.monotonic() > deadline:
                    raise AssertionError(f"not reached in {timeout:.0f}s; status {self.status()}")
                ran = await self.dispatcher.process_one()
                await self.runtime.tick()
                if not ran:
                    await asyncio.sleep(0.02)

        asyncio.run(loop())

    def close(self) -> None:
        asyncio.run(self.runtime.stop())
        self.client.close()
        reset_storage_pipeline()


@pytest.fixture
def stack(data_dir: Path, host: FakeModelHost, monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    device = Stack(data_dir, host, monkeypatch)
    try:
        yield device
    finally:
        device.close()


def _png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 180, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def _semantic(items: list[dict[str, Any]]) -> list[str]:
    return [item["title"] for item in items if "semantic" in item["match_reasons"]]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - not ours
        return True
    try:  # a zombie child counts as gone
        waited, _ = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True
    return waited == 0


def test_activate_reaches_ready_and_semantic_search_without_restarting_anything(stack: Stack) -> None:
    for name in ("factura-luz-enero.txt", "receta-pasta.txt", "viaje-playa.txt"):
        uploaded = stack.client.post("/api/assets/upload", files={"file": (name, name.encode(), "text/plain")})
        assert uploaded.status_code == 200
    stack.drain()  # thumbnails and the like; nothing to embed while smart search is off
    assert stack.launches() == 0 and not stack.endpoint_file.exists()
    assert _semantic(stack.search("facturas")) == []
    assert stack.client.get("/api/settings").json()["embeddings_state"] == "disabled"

    activated = stack.client.post("/api/smart-search/activate", json={})
    assert activated.status_code == 200
    assert activated.json()["state"] == "downloading"

    seen: list[tuple[str, int, int]] = []

    def ready() -> bool:
        body = stack.status()
        seen.append((body["state"], body["indexing"]["done"], body["indexing"]["total"]))
        return body["state"] == "ready"

    stack.work_until(ready)

    # The worker built at startup with `disabled` started llama-server once, for the activated space.
    assert stack.launches() == 1
    info = read_endpoint_file(stack.endpoint_file)
    assert info is not None and info.space_id == activated.json()["space_id"]
    states = [state for state, _, _ in seen]
    assert "indexing" not in states or states.index("indexing") < states.index("ready")
    indexing_done = [done for state, done, _ in seen if state == "indexing"]
    assert indexing_done == sorted(indexing_done)  # progress only moves forward
    assert stack.status()["indexing"] == {"done": 3, "total": 3}

    # The API built its search while `disabled`; it follows the change on the next request.
    assert set(_semantic(stack.search("facturas de luz"))) == {
        "factura-luz-enero.txt",
        "receta-pasta.txt",
        "viaje-playa.txt",
    }
    assert stack.client.get("/api/settings").json()["embeddings_state"] == "ready"

    # A file uploaded after activation gets its own embedding job (the upload policy follows too).
    later = stack.client.post("/api/assets/upload", files={"file": ("playa.png", _png(), "image/png")})
    assert later.status_code == 200
    stack.work_until(lambda: "playa.png" in _semantic(stack.search("playa")))


def test_remove_stops_the_server_and_search_falls_back_to_text(stack: Stack) -> None:
    uploaded = stack.client.post("/api/assets/upload", files={"file": ("factura.txt", b"factura", "text/plain")})
    assert uploaded.status_code == 200
    assert stack.client.post("/api/smart-search/activate", json={}).status_code == 200
    stack.work_until(lambda: stack.status()["state"] == "ready")
    assert _semantic(stack.search("factura")) == ["factura.txt"]
    info = read_endpoint_file(stack.endpoint_file)
    assert info is not None and info.pid is not None and _alive(info.pid)

    removed = stack.client.delete("/api/smart-search/model")
    assert removed.status_code == 200
    assert removed.json()["state"] == "off"

    # The API stops asking for vectors at once; text search still finds the file.
    items = stack.search("factura")
    assert [item["title"] for item in items] == ["factura.txt"]
    assert _semantic(items) == []
    assert stack.client.get("/api/settings").json()["embeddings_state"] == "disabled"

    # The worker's next tick stops llama-server; the janitor drops the vectors.
    asyncio.run(stack.runtime.tick())
    assert not stack.endpoint_file.exists()
    deadline = time.monotonic() + 10
    while _alive(info.pid):
        assert time.monotonic() < deadline, "llama-server is still running after removal"
        time.sleep(0.05)
    assert asyncio.run(stack.janitor.sweep()) == (info.space_id,)

    # Turning it on again works in the same processes.
    stack.control_fake_server()
    assert stack.client.post("/api/smart-search/activate", json={}).status_code == 200
    stack.work_until(lambda: stack.status()["state"] == "ready")
    assert _semantic(stack.search("factura")) == ["factura.txt"]
