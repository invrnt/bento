"""Process-wide service factories shared by Telegram-first features.

Each factory is implemented by the stage agent that owns the service (see
`orchestration/execution/telegram-first-program.md`). Callers depend on the returned
ports only, so features can be wired before every implementation lands.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bento.infrastructure.settings import Settings
    from bento.ports.blob_store import RemoteBlobStorePort
    from bento.ports.content import AssetContentPort
    from bento.ports.key_store import KeyStorePort
    from bento.ports.security import BlobCipherPort, PairingCryptoFactoryPort, VaultCryptoPort
    from bento.ports.sync import SyncStatusProviderPort
    from bento.ports.vault import VaultSessionPort


def get_key_store(settings: Settings) -> KeyStorePort:
    """Owner: vault-crypto (Stage 14) / mtproto wiring (Stage 15). `<data_dir>/secure`, cached per data dir."""
    from bento.infrastructure.mtproto import wiring

    return wiring.key_store(settings)


def get_vault_crypto() -> VaultCryptoPort:
    from bento.infrastructure.mtproto import wiring

    return wiring.vault_crypto()


def get_blob_cipher() -> BlobCipherPort:
    from bento.infrastructure.mtproto import wiring

    return wiring.blob_cipher()


def get_pairing_crypto() -> PairingCryptoFactoryPort:
    from bento.infrastructure.mtproto import wiring

    return wiring.pairing_crypto()


def get_vault_session(settings: Settings) -> VaultSessionPort:
    """Owner: mtproto agent. Cached per process; never raises (local mode reports `local_only`)."""
    from bento.infrastructure.mtproto import wiring

    return wiring.vault_session(settings)


def get_remote_blob_store(settings: Settings) -> RemoteBlobStorePort | None:
    """Owner: mtproto agent. None when the vault is not ready on this device."""
    from bento.infrastructure.mtproto import wiring

    return wiring.remote_blob_store(settings)


def get_asset_content(settings: Settings) -> AssetContentPort:
    """Owner: storage-pipeline (backup) agent."""
    from bento.infrastructure.storage_pipeline import get_storage_pipeline

    return get_storage_pipeline(settings).content


_sync_status_lock = threading.Lock()
_sync_status_providers: dict[tuple[str, str], SyncStatusProviderPort] = {}


def get_sync_status_provider(settings: Settings) -> SyncStatusProviderPort:
    """Owner: sync agent. Reads only the local sync state the worker loop persists (no Telegram calls);
    reports `disabled` for local storage. `request_sync()` writes the cross-process "sync now" marker."""
    from bento.adapters.sync import SQLiteSyncOutbox, SQLiteSyncStateStore
    from bento.application.sync import SyncStatusService
    from bento.infrastructure.db.clock import SystemClock
    from bento.infrastructure.db.engine import create_app_session_factory
    from bento.infrastructure.settings import settings_database_path

    key = (settings.storage_backend, str(settings_database_path(settings).resolve()))
    with _sync_status_lock:
        provider = _sync_status_providers.get(key)
        if provider is None:
            factory = create_app_session_factory(settings)
            provider = SyncStatusService(
                enabled=settings.storage_backend != "local",
                state=SQLiteSyncStateStore(factory),
                outbox=SQLiteSyncOutbox(factory),
                clock=SystemClock(),
            )
            _sync_status_providers[key] = provider
        return provider


def reset_services() -> None:
    """Drop cached instances (tests, account reloads). Each owner clears its own caches here."""
    from bento.infrastructure.mtproto import wiring
    from bento.infrastructure.storage_pipeline import reset_storage_pipeline

    wiring.reset()
    reset_storage_pipeline()
    with _sync_status_lock:
        _sync_status_providers.clear()
