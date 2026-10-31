from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bento.adapters.fake_telegram import FakeTelegramAccount, FakeTelegramCloud
from bento.domain.account import LoginStep
from bento.domain.errors import TelegramNotAvailableError
from bento.infrastructure import runtime as runtime_module
from bento.infrastructure.runtime import get_telegram_runtime, reset_telegram_runtime
from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app
from tests.integration.fake_telegram.support import MemoryKeyStore, run


@pytest.fixture(autouse=True)
def _fresh_runtime() -> Iterator[None]:
    reset_telegram_runtime()
    yield
    reset_telegram_runtime()


def test_local_storage_has_no_telegram_runtime(tmp_path: Path) -> None:
    assert get_telegram_runtime(Settings(data_dir=str(tmp_path), storage_backend="local"), MemoryKeyStore()) is None


def test_fake_runtime_is_cached_per_process_until_reset(tmp_path: Path) -> None:
    settings = Settings(data_dir=str(tmp_path), storage_backend="fake")

    first = get_telegram_runtime(settings, MemoryKeyStore())

    assert first is not None
    assert isinstance(first.account, FakeTelegramAccount)
    assert get_telegram_runtime(settings, MemoryKeyStore()) is first
    run(first.account.start_qr_login())
    assert (tmp_path / "fake-telegram" / "cloud.json").is_file()
    other_dir = Settings(data_dir=str(tmp_path), storage_backend="fake", fake_telegram_dir=str(tmp_path / "elsewhere"))
    assert get_telegram_runtime(other_dir, MemoryKeyStore()) is not first
    reset_telegram_runtime()
    assert get_telegram_runtime(settings, MemoryKeyStore()) is not first


def test_telegram_runtime_requires_the_mtproto_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(data_dir=str(tmp_path), storage_backend="telegram")
    monkeypatch.setattr(runtime_module, "MTPROTO_RUNTIME_MODULE", "bento.infrastructure.mtproto_missing.runtime")

    with pytest.raises(TelegramNotAvailableError):
        get_telegram_runtime(settings, MemoryKeyStore())


def test_telegram_runtime_delegates_to_the_mtproto_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(data_dir=str(tmp_path), storage_backend="telegram")
    key_store = MemoryKeyStore()
    sentinel = object()
    calls: list[tuple[object, object]] = []
    module = types.ModuleType("bento_test_mtproto_runtime")
    module.create_mtproto_runtime = lambda *args: calls.append(args) or sentinel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "bento_test_mtproto_runtime", module)
    monkeypatch.setattr(runtime_module, "MTPROTO_RUNTIME_MODULE", "bento_test_mtproto_runtime")

    assert get_telegram_runtime(settings, key_store) is sentinel
    assert get_telegram_runtime(settings, key_store) is sentinel
    assert calls == [(settings, key_store)]


def test_dev_route_approves_pending_fake_logins(tmp_path: Path) -> None:
    settings = Settings(data_dir=str(tmp_path), storage_backend="fake")
    key_store = MemoryKeyStore()
    runtime = get_telegram_runtime(settings, key_store)
    assert runtime is not None
    client = TestClient(create_app(settings))

    assert client.post("/api/dev/fake-telegram/approve-login").json() == {"approved": 0}

    async def start_and_check_pending() -> LoginStep:
        await runtime.account.start_qr_login()
        return (await runtime.account.status()).step

    # Auto-approval needs 2 s of waiting, so a fresh token is still pending until the route approves it.
    assert run(start_and_check_pending()) == LoginStep.QR_PENDING
    assert client.post("/api/dev/fake-telegram/approve-login").json() == {"approved": 1}
    assert run(runtime.account.status()).authorized


@pytest.mark.parametrize(
    "settings",
    [
        Settings(storage_backend="local"),
        Settings(storage_backend="telegram"),
        Settings(storage_backend="local", environment="production"),
    ],
)
def test_dev_route_is_hidden_unless_fake_outside_production(tmp_path: Path, settings: Settings) -> None:
    client = TestClient(create_app(settings.model_copy(update={"data_dir": str(tmp_path)})))

    response = client.post("/api/dev/fake-telegram/approve-login")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert "/api/dev/fake-telegram/approve-login" not in client.get("/openapi.json").text


def test_concurrent_writers_get_unique_increasing_message_ids(tmp_path: Path) -> None:
    FakeTelegramCloud(tmp_path).ensure_ready()
    channel = FakeTelegramCloud(tmp_path).create_channel("Bento · Sync")

    def post(writer: int) -> list[int]:
        cloud = FakeTelegramCloud(tmp_path)
        return [cloud.post_message(channel.id, text=f"{writer}:{index}").id for index in range(20)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        batches = list(pool.map(post, range(8)))

    assert all(batch == sorted(batch) for batch in batches)
    ids = sorted(message_id for batch in batches for message_id in batch)
    assert ids == list(range(1, 161))
    _, messages = FakeTelegramCloud(tmp_path).read_chat(channel.id)
    assert [message.id for message in messages] == ids
