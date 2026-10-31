"""Process-wide service factories shared by Telegram-first features.

Each factory is implemented by the stage agent that owns the service (see
`orchestration/execution/telegram-first-program.md`). Callers depend on the returned
ports only, so features can be wired before every implementation lands.
"""

from __future__ import annotations

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
    """Owner: vault-crypto (Stage 14) / mtproto wiring (Stage 15)."""
    raise NotImplementedError("get_key_store is wired in Stage 15")


def get_vault_crypto() -> VaultCryptoPort:
    raise NotImplementedError("get_vault_crypto is wired in Stage 15")


def get_blob_cipher() -> BlobCipherPort:
    raise NotImplementedError("get_blob_cipher is wired in Stage 15")


def get_pairing_crypto() -> PairingCryptoFactoryPort:
    raise NotImplementedError("get_pairing_crypto is wired in Stage 15")


def get_vault_session(settings: Settings) -> VaultSessionPort:
    """Owner: mtproto agent."""
    raise NotImplementedError("get_vault_session is implemented by the mtproto agent")


def get_remote_blob_store(settings: Settings) -> RemoteBlobStorePort | None:
    """Owner: mtproto agent. None when the vault is not ready on this device."""
    raise NotImplementedError("get_remote_blob_store is implemented by the mtproto agent")


def get_asset_content(settings: Settings) -> AssetContentPort:
    """Owner: storage-pipeline (backup) agent."""
    from bento.infrastructure.storage_pipeline import get_storage_pipeline

    return get_storage_pipeline(settings).content


def get_sync_status_provider(settings: Settings) -> SyncStatusProviderPort:
    """Owner: sync agent."""
    raise NotImplementedError("get_sync_status_provider is implemented by the sync agent")


def reset_services() -> None:
    """Drop cached instances (tests, account reloads). Each owner clears its own caches here."""
    from bento.infrastructure.storage_pipeline import reset_storage_pipeline

    reset_storage_pipeline()
