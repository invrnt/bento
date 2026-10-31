"""Process-wide composition of the Telegram vault services (the bodies behind `infrastructure/services.py`).

Works for both Telegram backends: MTProto and the fake cloud come from `get_telegram_runtime`.
"""

from __future__ import annotations

import os
import platform
import socket
import threading
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.jobs import SQLiteJobQueue
from bento.adapters.media.catalog import SQLiteBlobRefCatalog
from bento.adapters.repositories.devices import SQLiteDeviceRepository
from bento.adapters.security import (
    PairingCryptoFactory,
    StreamingBlobCipher,
    VaultCrypto,
    WrappedFileKeyStore,
    load_wrapping_key,
)
from bento.adapters.settings import SQLiteSettingsRepository
from bento.adapters.storage.telegram_vault_blob_store import MIB, SQLiteUploadSessionStore, TelegramVaultBlobStore
from bento.adapters.telegram_mtproto.vault_state import (
    SQLiteStorageBackendPreference,
    SQLiteVaultState,
    SQLiteVaultUsage,
)
from bento.application.account import AccountService
from bento.application.vault import LAYOUT_KEY, DeviceDescription, TelegramPorts, VaultService
from bento.domain.devices import DevicePlatform
from bento.domain.errors import TelegramNotAvailableError
from bento.infrastructure.db.clock import SystemClock
from bento.infrastructure.db.engine import create_session_factory, session_scope, sqlite_url
from bento.infrastructure.db.models import SyncStateModel
from bento.infrastructure.runtime import TelegramRuntime, get_telegram_runtime
from bento.infrastructure.settings import Settings, settings_database_path
from bento.ports.key_store import TELEGRAM_SESSION, VAULT_KEYRING, KeyStorePort

_lock = threading.RLock()
_key_stores: dict[str, KeyStorePort] = {}
_session_factories: dict[str, sessionmaker[Session]] = {}
_vault_sessions: dict[tuple[str, ...], VaultService] = {}
_account_services: dict[tuple[str, ...], AccountService] = {}
_singletons: dict[str, object] = {}

_PLATFORMS = {"Linux": DevicePlatform.LINUX, "Darwin": DevicePlatform.MACOS, "Windows": DevicePlatform.WINDOWS}
_OS_LABELS = {"Linux": "Linux", "Darwin": "macOS", "Windows": "Windows"}


def key_store(settings: Settings) -> KeyStorePort:
    """`WrappedFileKeyStore` in `<data_dir>/secure`, wrapped by `BENTO_DEVICE_WRAPPING_KEY` or a key file."""
    data_dir = Path(settings.data_dir).resolve()
    with _lock:
        store = _key_stores.get(str(data_dir))
        if store is None:
            wrapping = load_wrapping_key(os.environ, data_dir)
            store = WrappedFileKeyStore(data_dir / "secure", wrapping.key)
            _key_stores[str(data_dir)] = store
        return store


def vault_crypto() -> VaultCrypto:
    return _singleton("vault_crypto", VaultCrypto)


def blob_cipher() -> StreamingBlobCipher:
    return _singleton("blob_cipher", StreamingBlobCipher)


def pairing_crypto() -> PairingCryptoFactory:
    return _singleton("pairing_crypto", PairingCryptoFactory)


def session_factory(settings: Settings) -> sessionmaker[Session]:
    path = str(settings_database_path(settings).resolve())
    with _lock:
        factory = _session_factories.get(path)
        if factory is None:
            factory = create_session_factory(sqlite_url(path))
            _session_factories[path] = factory
        return factory


def telegram_runtime(settings: Settings) -> TelegramRuntime | None:
    """`None` for local storage; raises `TelegramNotAvailableError` without build credentials."""
    return get_telegram_runtime(settings, key_store(settings))


def vault_session(settings: Settings) -> VaultService:
    cache_key = _cache_key(settings)
    with _lock:
        service = _vault_sessions.get(cache_key)
        if service is not None:
            return service
        sessions = session_factory(settings)
        clock = SystemClock()

        def telegram() -> TelegramPorts | None:
            runtime = telegram_runtime(settings)
            return None if runtime is None else TelegramPorts(account=runtime.account, transport=runtime.transport)

        service = VaultService(
            telegram=telegram,
            crypto=vault_crypto(),
            key_store=_LazyKeyStore(settings),
            state=SQLiteVaultState(sessions, clock),
            devices=SQLiteDeviceRepository(sessions),
            usage=SQLiteVaultUsage(sessions),
            device=device_description(),
            clock=clock,
            backend_preference=SQLiteStorageBackendPreference(SQLiteSettingsRepository(sessions, clock)),
        )
        _vault_sessions[cache_key] = service
        return service


def account_service(settings: Settings) -> AccountService:
    cache_key = _cache_key(settings)
    with _lock:
        service = _account_services.get(cache_key)
        if service is not None:
            return service
        vault = vault_session(settings)

        def account() -> object:
            runtime = telegram_runtime(settings)
            return None if runtime is None else runtime.account

        async def changed() -> None:
            vault.invalidate()

        service = AccountService(
            account=account,  # type: ignore[arg-type]
            jobs=SQLiteJobQueue(session_factory(settings), SystemClock()),
            on_change=changed,
        )
        _account_services[cache_key] = service
        return service


def remote_blob_store(settings: Settings) -> TelegramVaultBlobStore | None:
    """The vault blob store, or `None` while this device has no unlocked vault (cheap local checks only)."""
    if settings.storage_backend == "local" or not vault_installed(settings):
        return None
    try:
        runtime = telegram_runtime(settings)
    except TelegramNotAvailableError:
        return None
    if runtime is None:
        return None
    sessions = session_factory(settings)
    clock = SystemClock()
    return TelegramVaultBlobStore(
        vault=vault_session(settings),
        parts=runtime.parts,
        cipher=blob_cipher(),
        sessions=SQLiteUploadSessionStore(sessions),
        catalog=SQLiteBlobRefCatalog(sessions, clock),
        clock=clock,
        temp_dir=Path(settings.data_dir) / "cache" / "remote-blobs",
        part_size_bytes=settings.telegram_part_size_mb * MIB,
    )


def vault_installed(settings: Settings) -> bool:
    """A layout is stored and the key store holds a keyring and a Telegram session."""
    try:
        with session_scope(session_factory(settings)) as session:
            if session.get(SyncStateModel, LAYOUT_KEY) is None:
                return False
    except SQLAlchemyError:
        return False
    store = key_store(settings)
    if isinstance(store, WrappedFileKeyStore):
        return all((store.directory / f"{name}.bin").is_file() for name in (VAULT_KEYRING, TELEGRAM_SESSION))
    return True


def device_description() -> DeviceDescription:
    """Default device name `<hostname> · <OS>`; people can rename it from Dispositivos."""
    system = platform.system()
    host = socket.gethostname().split(".")[0].strip() or "Bento"
    return DeviceDescription(
        name=f"{host} · {_OS_LABELS.get(system, system or 'Desktop')}",
        platform=_PLATFORMS.get(system, DevicePlatform.OTHER),
    )


def reset() -> None:
    with _lock:
        _key_stores.clear()
        _session_factories.clear()
        _vault_sessions.clear()
        _account_services.clear()
        _singletons.clear()


class _LazyKeyStore:
    """Opens the key store (and creates a wrapping key file if needed) only when a secret is touched."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def get(self, name: str) -> bytes | None:
        return await key_store(self._settings).get(name)

    async def put(self, name: str, value: bytes) -> None:
        await key_store(self._settings).put(name, value)

    async def delete(self, name: str) -> None:
        await key_store(self._settings).delete(name)


def _singleton(name: str, factory: type) -> object:
    with _lock:
        instance = _singletons.get(name)
        if instance is None:
            instance = factory()
            _singletons[name] = instance
        return instance  # type: ignore[return-value]


def _cache_key(settings: Settings) -> tuple[str, ...]:
    return (
        settings.storage_backend,
        str(Path(settings.data_dir).resolve()),
        settings.fake_telegram_dir,
    )
