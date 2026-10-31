"""`create_mtproto_runtime`: the Telegram ports of this process on the real Telegram (Telethon)."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from bento.adapters.security import VaultCrypto
from bento.adapters.telegram_mtproto.account import MtprotoTelegramAccount
from bento.adapters.telegram_mtproto.chats import MtprotoTelegramChats
from bento.adapters.telegram_mtproto.parts import MtprotoRemotePartStore
from bento.adapters.telegram_mtproto.session import MtprotoSession
from bento.adapters.telegram_mtproto.transport import MtprotoVaultTransport
from bento.adapters.telegram_mtproto.vault_state import SQLiteVaultState
from bento.application.account import FLOOD_WAIT_UNTIL_KEY
from bento.application.devices import telegram_device_model
from bento.application.vault import DeviceIdentityStore
from bento.domain.settings import SettingSource
from bento.infrastructure.db.clock import SystemClock
from bento.infrastructure.db.engine import create_session_factory, sqlite_url
from bento.infrastructure.mtproto.client import TelethonClientFactory
from bento.infrastructure.mtproto.config import ClientIdentity, load_credentials, system_version
from bento.infrastructure.mtproto.flood import FloodWaitPolicy
from bento.infrastructure.mtproto.transfer import TokenBucket, TransferLimits
from bento.infrastructure.runtime import TelegramRuntime
from bento.infrastructure.settings import Settings, settings_database_path
from bento.ports.key_store import KeyStorePort

BANDWIDTH_KEY = "backup_bandwidth_limit_kbps"
LIVE_SETTING_TTL_SECONDS = 5.0


def create_mtproto_runtime(settings: Settings, key_store: KeyStorePort) -> TelegramRuntime:
    """Raises `TelegramNotAvailableError` when the build has no Telegram application credentials."""
    credentials = load_credentials(settings)
    identities = DeviceIdentityStore(key_store, VaultCrypto())

    async def identity() -> ClientIdentity:
        device = await identities.get()
        return ClientIdentity(
            device_model=telegram_device_model(device.device_id),
            system_version=system_version(),
            app_version=settings.app_version,
        )

    clock = SystemClock()
    state = SQLiteVaultState(create_session_factory(sqlite_url(settings_database_path(settings))), clock)

    async def record_long_wait(seconds: int) -> None:
        await state.set_value(FLOOD_WAIT_UNTIL_KEY, (clock.now() + timedelta(seconds=seconds)).isoformat())

    session = MtprotoSession(
        factory=TelethonClientFactory(credentials, identity),
        key_store=key_store,
        policy=FloodWaitPolicy(on_long_wait=record_long_wait),
        transfers=TransferLimits(
            parallel_transfers=settings.telegram_parallel_transfers,
            upload_bucket=TokenBucket(live_bandwidth_limit(settings)),
        ),
    )
    return TelegramRuntime(
        account=MtprotoTelegramAccount(session),
        transport=MtprotoVaultTransport(session),
        parts=MtprotoRemotePartStore(session),
        chats=MtprotoTelegramChats(session),
    )


async def reload_telegram_session(runtime: TelegramRuntime) -> None:
    """Disconnect the MTProto client so the next call uses the session stored now (`account_reload`)."""
    session = getattr(runtime.account, "session", None)
    if isinstance(session, MtprotoSession):
        await session.reload()


def live_bandwidth_limit(settings: Settings, *, ttl_seconds: float = LIVE_SETTING_TTL_SECONDS) -> Callable[[], int]:
    """`backup_bandwidth_limit_kbps` as saved now (environment/policy values are fixed for the process)."""
    default = int(settings.backup_bandwidth_limit_kbps)
    snapshot = settings.effective_snapshot
    effective = snapshot.values.get(BANDWIDTH_KEY) if snapshot is not None else None
    if effective is not None and effective.source in {SettingSource.ENVIRONMENT, SettingSource.POLICY}:
        return lambda: default
    path = settings_database_path(settings)
    cached = [default, float("-inf")]

    def read() -> int:
        now = time.monotonic()
        if now - cached[1] >= ttl_seconds:
            cached[1] = now
            cached[0] = _saved_int(path, BANDWIDTH_KEY, default)
        return int(cached[0])

    return read


def _saved_int(path: Path, key: str, default: int) -> int:
    if not path.is_file():
        return default
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return default
    if row is None:
        return default
    try:
        return max(0, int(json.loads(row[0])))
    except (TypeError, ValueError):
        return default
