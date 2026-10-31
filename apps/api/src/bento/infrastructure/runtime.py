"""Process-wide selection of the Telegram implementation for the configured storage backend."""

from __future__ import annotations

import importlib
import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bento.adapters.fake_telegram import (
    FakeRemotePartStore,
    FakeTelegramAccount,
    FakeTelegramChats,
    FakeTelegramCloud,
    FakeTelegramOptions,
    FakeTelegramSession,
    FakeVaultTransport,
)
from bento.domain.errors import TelegramNotAvailableError
from bento.infrastructure.settings import Settings, fake_telegram_directory
from bento.ports.key_store import KeyStorePort
from bento.ports.telegram import RemotePartStorePort, TelegramAccountPort, TelegramChatsPort, VaultTransportPort

MTPROTO_RUNTIME_MODULE = "bento.infrastructure.mtproto.runtime"


@dataclass(frozen=True, slots=True)
class TelegramRuntime:
    account: TelegramAccountPort
    transport: VaultTransportPort
    parts: RemotePartStorePort
    chats: TelegramChatsPort


_lock = threading.Lock()
_cached: tuple[tuple[str, ...], TelegramRuntime] | None = None


def get_telegram_runtime(settings: Settings, key_store: KeyStorePort) -> TelegramRuntime | None:
    """`None` for local storage. Cached per process: the first key store wins until `reset_telegram_runtime()`."""
    global _cached
    if settings.storage_backend == "local":
        return None
    key = _cache_key(settings)
    with _lock:
        if _cached is not None and _cached[0] == key:
            return _cached[1]
        runtime = _create_runtime(settings, key_store)
        _cached = (key, runtime)
        return runtime


def reset_telegram_runtime() -> None:
    """Forget the cached runtime (tests, account reloads, settings changes)."""
    global _cached
    with _lock:
        _cached = None


def create_fake_telegram_runtime(
    directory: Path | str,
    key_store: KeyStorePort,
    *,
    options: FakeTelegramOptions | None = None,
    environ: Mapping[str, str] | None = None,
    clock: Callable[[], float] | None = None,
) -> TelegramRuntime:
    """An uncached fake runtime; call twice with different key stores to simulate two devices in one process."""
    resolved = options or FakeTelegramOptions.from_environ(os.environ if environ is None else environ)
    cloud = FakeTelegramCloud(directory) if clock is None else FakeTelegramCloud(directory, clock=clock)
    session = FakeTelegramSession(cloud, key_store, resolved)
    return TelegramRuntime(
        account=FakeTelegramAccount(session),
        transport=FakeVaultTransport(session),
        parts=FakeRemotePartStore(session),
        chats=FakeTelegramChats(session),
    )


def approve_fake_telegram_logins(settings: Settings) -> int:
    """Approve every pending QR login of the configured fake cloud (blocking; dev route and tests)."""
    return FakeTelegramCloud(fake_telegram_directory(settings)).approve_pending_logins()


def _create_runtime(settings: Settings, key_store: KeyStorePort) -> TelegramRuntime:
    if settings.storage_backend == "fake":
        options = FakeTelegramOptions.from_environ(os.environ, app_name=f"{settings.app_name} {settings.app_version}")
        return create_fake_telegram_runtime(fake_telegram_directory(settings), key_store, options=options)
    try:
        module: Any = importlib.import_module(MTPROTO_RUNTIME_MODULE)
    except ModuleNotFoundError as exc:
        parts = MTPROTO_RUNTIME_MODULE.split(".")
        if exc.name in {".".join(parts[:index]) for index in range(1, len(parts) + 1)}:
            raise TelegramNotAvailableError() from exc
        raise
    return module.create_mtproto_runtime(settings, key_store)


def _cache_key(settings: Settings) -> tuple[str, ...]:
    if settings.storage_backend == "fake":
        return ("fake", str(fake_telegram_directory(settings).resolve()))
    return (settings.storage_backend, str(Path(settings.data_dir).resolve()))
