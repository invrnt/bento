from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from telethon import errors

from bento.adapters.security import InMemoryKeyStore
from bento.domain.errors import StorageUnavailableError, TelegramAccountError, TelegramFloodWaitError, TelegramNotAvailableError
from bento.infrastructure.mtproto.client import TelethonClientFactory
from bento.infrastructure.mtproto.config import ClientIdentity, TelegramAppCredentials, load_credentials, system_version
from bento.infrastructure.mtproto.flood import FloodWaitPolicy
from bento.infrastructure.mtproto.runtime import create_mtproto_runtime, live_bandwidth_limit
from bento.infrastructure.mtproto.transfer import TokenBucket, TransferLimits
from bento.infrastructure.settings import Settings
from bento.ports.key_store import TELEGRAM_SESSION
from tests.unit.telegram_mtproto.fake_telethon import FakeTelethonClient, make_session


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def test_flood_waits_are_slept_exactly_plus_jitter_then_retried() -> None:
    sleeps = Sleeps()
    policy = FloodWaitPolicy(sleep=sleeps, random_fraction=lambda: 0.5, jitter_seconds=2.0)
    attempts = 0

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise errors.FloodWaitError(request=None, capture=7)
        return "ok"

    assert run(policy.run(operation)) == "ok"
    assert sleeps.calls == [8.0, 8.0]


def test_long_flood_waits_are_recorded_and_raised() -> None:
    recorded: list[int] = []

    async def record(seconds: int) -> None:
        recorded.append(seconds)

    sleeps = Sleeps()
    policy = FloodWaitPolicy(sleep=sleeps, on_long_wait=record)

    async def operation() -> None:
        raise errors.FloodWaitError(request=None, capture=420)

    with pytest.raises(TelegramFloodWaitError) as raised:
        run(policy.run(operation))
    assert raised.value.retry_after_seconds == 420 and raised.value.details == {"retry_after_seconds": 420}
    assert recorded == [420] and sleeps.calls == []

    async def broken_recorder(seconds: int) -> None:
        raise RuntimeError("disk full")

    with pytest.raises(TelegramFloodWaitError):
        run(FloodWaitPolicy(on_long_wait=broken_recorder).run(operation))


def test_retries_are_bounded_and_other_errors_pass_through() -> None:
    sleeps = Sleeps()
    policy = FloodWaitPolicy(sleep=sleeps, max_retries=2, random_fraction=lambda: 0.0)

    async def always_flood() -> None:
        raise errors.SlowModeWaitError(request=None, capture=1)

    with pytest.raises(TelegramFloodWaitError):
        run(policy.run(always_flood))
    assert sleeps.calls == [1.0, 1.0]

    async def boom() -> None:
        raise ValueError("not a flood")

    with pytest.raises(ValueError):
        run(policy.run(boom))


def test_session_maps_errors_and_rebuilds_the_client_when_the_stored_session_changes() -> None:
    async def scenario() -> None:
        client = FakeTelethonClient()
        session, store = make_session(client)
        assert await session.account() is None
        with pytest.raises(TelegramAccountError) as raised:
            await session.authorized_client()
        assert raised.value.code == "telegram_not_authorized"

        await store.put(TELEGRAM_SESSION, b"1stored-session")
        account = await session.account()
        assert account is not None and account.display_name == "Ana Demo" and account.phone_masked == "+57 ••• ••• 12"
        assert session.built == ["", "1stored-session"]  # type: ignore[attr-defined]

        async def network(_client: Any) -> None:
            raise ConnectionError("offline")

        with pytest.raises(TelegramAccountError) as raised:
            await session.call(network)
        assert raised.value.code == "telegram_network"

        async def rpc(_client: Any) -> None:
            raise errors.ChannelPrivateError(request=None)

        with pytest.raises(StorageUnavailableError) as unavailable:
            await session.call(rpc)
        assert unavailable.value.details == {"backend": "telegram", "reason": "CHANNEL_PRIVATE"}

        async def revoked(_client: Any) -> None:
            raise errors.AuthKeyUnregisteredError(request=None)

        with pytest.raises(TelegramAccountError):
            await session.call(revoked)
        assert await session.account() is None  # remembered until the session changes

        await session.forget()
        assert await store.get(TELEGRAM_SESSION) is None and not client.connected

    run(scenario())


def test_input_peers_come_from_the_dialogs_when_not_cached() -> None:
    async def scenario() -> None:
        client = FakeTelethonClient()
        session, _ = make_session(client)
        client.get_input_entity = _unknown  # type: ignore[method-assign]
        from tests.unit.telegram_mtproto.fake_telethon import bento_channel

        channel = bento_channel(client, "Bento · Sync", "about")
        peer_id = next(key for key, value in client.channels.items() if value is channel)

        peer = await session.input_peer(await session.client(), peer_id)

        assert peer.channel_id == channel.entity.id
        with pytest.raises(StorageUnavailableError):
            await session.input_peer(await session.client(), -100999)

    run(scenario())


async def _unknown(_peer: Any) -> Any:
    raise ValueError("unknown")


def test_token_bucket_spreads_uploads_over_the_limit() -> None:
    now = [0.0]
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limit = [100]
    bucket = TokenBucket(lambda: limit[0], clock=lambda: now[0], sleep=sleep)

    run(bucket.consume(300 * 1024))

    assert sum(sleeps) == pytest.approx(3.0)
    limit[0] = 0
    sleeps.clear()
    run(bucket.consume(10**9))
    assert sleeps == []


def test_transfer_limits_bound_parallel_uploads() -> None:
    async def scenario() -> int:
        limits = TransferLimits(parallel_transfers=2)
        active = peak = 0

        async def transfer() -> None:
            nonlocal active, peak
            async with limits.upload_slot():
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(*(transfer() for _ in range(6)))
        await limits.consume_upload(10)
        return peak

    assert run(scenario()) == 2


def test_bandwidth_limit_is_read_live_from_saved_settings(tmp_path: Path) -> None:
    settings = Settings(data_dir=str(tmp_path), backup_bandwidth_limit_kbps=0)
    read = live_bandwidth_limit(settings, ttl_seconds=0.0)
    assert read() == 0
    (tmp_path / "db").mkdir()
    connection = sqlite3.connect(tmp_path / "db" / "bento.sqlite3")
    connection.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
    connection.execute("INSERT INTO settings VALUES (?, ?, '')", ("backup_bandwidth_limit_kbps", json.dumps(512)))
    connection.commit()
    connection.close()

    assert read() == 512


def test_credentials_are_build_configuration() -> None:
    with pytest.raises(TelegramNotAvailableError):
        load_credentials(Settings())
    with pytest.raises(TelegramNotAvailableError):
        load_credentials(Settings(telegram_api_id="abc", telegram_api_hash="hash"))
    credentials = load_credentials(Settings(telegram_api_id=" 12345 ", telegram_api_hash="0123abcd"))
    assert credentials == TelegramAppCredentials(api_id=12345, api_hash="0123abcd")
    assert "0123abcd" not in repr(credentials)
    assert system_version()


def test_client_factory_announces_bento_and_leaves_flood_waits_to_the_policy() -> None:
    captured: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def client_class(*args: Any, **kwargs: Any) -> str:
        captured.append((args, kwargs))
        return "client"

    async def identity() -> ClientIdentity:
        return ClientIdentity(device_model="Bento (a1b2c3)", system_version="Linux 6.8", app_version="0.1.0")

    factory = TelethonClientFactory(TelegramAppCredentials(42, "hash"), identity, client_class=client_class)

    assert run(factory("")) == "client"
    (session, api_id, api_hash), kwargs = captured[0]
    assert api_id == 42 and api_hash == "hash" and session.save() == ""
    assert kwargs["device_model"] == "Bento (a1b2c3)" and kwargs["system_version"] == "Linux 6.8"
    assert kwargs["app_version"] == "0.1.0" and kwargs["flood_sleep_threshold"] == 0
    assert kwargs["receive_updates"] is True and kwargs["catch_up"] is False


def test_mtproto_runtime_needs_credentials_and_connects_lazily(tmp_path: Path) -> None:
    store = InMemoryKeyStore()
    with pytest.raises(TelegramNotAvailableError):
        create_mtproto_runtime(Settings(data_dir=str(tmp_path), storage_backend="telegram"), store)

    runtime = create_mtproto_runtime(
        Settings(data_dir=str(tmp_path), storage_backend="telegram", telegram_api_id="1", telegram_api_hash="h"), store
    )

    from bento.adapters.telegram_mtproto.account import MtprotoTelegramAccount
    from bento.adapters.telegram_mtproto.chats import MtprotoTelegramChats
    from bento.adapters.telegram_mtproto.parts import MtprotoRemotePartStore
    from bento.adapters.telegram_mtproto.transport import MtprotoVaultTransport

    assert isinstance(runtime.account, MtprotoTelegramAccount)
    assert isinstance(runtime.transport, MtprotoVaultTransport)
    assert isinstance(runtime.parts, MtprotoRemotePartStore)
    assert isinstance(runtime.chats, MtprotoTelegramChats)
    assert run(store.get("device.identity")) is None  # nothing happens before the first call
