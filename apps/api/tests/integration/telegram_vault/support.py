"""Devices of one fake Telegram account, each with its own SQLite database, key store, and real `VaultService`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.fake_telegram import FAKE_LOGIN_CODE, FakeTelegramCloud, FakeTelegramOptions
from bento.adapters.media.catalog import SQLiteBlobRefCatalog
from bento.adapters.repositories.devices import SQLiteDeviceRepository
from bento.adapters.security import InMemoryKeyStore, StreamingBlobCipher, VaultCrypto
from bento.adapters.settings import SQLiteSettingsRepository
from bento.adapters.storage.telegram_vault_blob_store import SQLiteUploadSessionStore, TelegramVaultBlobStore
from bento.adapters.telegram_mtproto.vault_state import (
    SQLiteStorageBackendPreference,
    SQLiteVaultState,
    SQLiteVaultUsage,
)
from bento.application.vault import DeviceDescription, TelegramPorts, VaultService
from bento.domain.devices import DevicePlatform
from bento.infrastructure.runtime import TelegramRuntime, bento_device_model, create_fake_telegram_runtime
from bento.ports.telegram import RemotePartStorePort
from tests.integration.db.support import migrated_session_factory

START = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


@dataclass
class TickingClock:
    current: datetime = START

    def now(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


@dataclass
class VaultDevice:
    name: str
    data_dir: Path
    cloud_dir: Path
    key_store: InMemoryKeyStore
    runtime: TelegramRuntime
    sessions: sessionmaker[Session]
    vault: VaultService
    state: SQLiteVaultState
    devices: SQLiteDeviceRepository
    clock: TickingClock
    crypto: VaultCrypto

    @property
    def cloud(self) -> FakeTelegramCloud:
        return FakeTelegramCloud(self.cloud_dir)

    async def sign_in(self) -> None:
        await self.runtime.account.start_phone_login("+57 300 000 0001")
        status = await self.runtime.account.submit_code(FAKE_LOGIN_CODE)
        assert status.authorized

    def blob_store(self, *, parts: RemotePartStorePort | None = None, part_size_bytes: int = 64 * 1024, **kwargs: Any) -> TelegramVaultBlobStore:
        return TelegramVaultBlobStore(
            vault=self.vault,
            parts=parts or self.runtime.parts,
            cipher=StreamingBlobCipher(),
            sessions=SQLiteUploadSessionStore(self.sessions),
            catalog=SQLiteBlobRefCatalog(self.sessions, self.clock),
            clock=self.clock,
            temp_dir=self.data_dir / "cache" / "remote-blobs",
            part_size_bytes=part_size_bytes,
            **kwargs,
        )


def make_vault_device(root: Path, cloud_dir: Path, name: str, *, telegram: bool = True, **options: Any) -> VaultDevice:
    data_dir = root / name
    (data_dir / "db").mkdir(parents=True)
    sessions = migrated_session_factory(data_dir / "db")
    key_store = InMemoryKeyStore()
    runtime = create_fake_telegram_runtime(
        cloud_dir,
        key_store,
        options=FakeTelegramOptions(platform="linux", app_name="Bento test", poll_interval_seconds=0.05, **options),
        device_model=bento_device_model(key_store),
    )
    clock = TickingClock()
    crypto = VaultCrypto()
    state = SQLiteVaultState(sessions, clock)
    devices = SQLiteDeviceRepository(sessions)
    vault = VaultService(
        telegram=(lambda: TelegramPorts(account=runtime.account, transport=runtime.transport)) if telegram else (lambda: None),
        crypto=crypto,
        key_store=key_store,
        state=state,
        devices=devices,
        usage=SQLiteVaultUsage(sessions),
        device=DeviceDescription(name=f"{name} · Linux", platform=DevicePlatform.LINUX),
        clock=clock,
        backend_preference=SQLiteStorageBackendPreference(SQLiteSettingsRepository(sessions, clock)),
    )
    return VaultDevice(
        name=name,
        data_dir=data_dir,
        cloud_dir=cloud_dir,
        key_store=key_store,
        runtime=runtime,
        sessions=sessions,
        vault=vault,
        state=state,
        devices=devices,
        clock=clock,
        crypto=crypto,
    )


def local_ingestion(device: VaultDevice) -> Any:
    """The upload ingestion over this device's database and a local blob store."""
    from bento.adapters.jobs import SQLiteJobQueue
    from bento.adapters.manifest import SQLiteManifestJournal
    from bento.adapters.media import LocalUploadMetadataExtractor
    from bento.adapters.repositories import SQLiteAssetRepository, SQLiteFolderRepository
    from bento.adapters.storage.local_blob_store import LocalBlobStoreAdapter
    from bento.application.ingestion import AssetIngestionService
    from bento.application.upload import UploadAssetUseCase

    return AssetIngestionService(
        upload=UploadAssetUseCase(
            assets=SQLiteAssetRepository(device.sessions),
            folders=SQLiteFolderRepository(device.sessions),
            blob_store=LocalBlobStoreAdapter(device.data_dir / "uploads"),
            jobs=SQLiteJobQueue(device.sessions, device.clock),
            manifest=SQLiteManifestJournal(device.sessions, device.clock, device.data_dir / "journal"),
            clock=device.clock,
        ),
        blob_refs=SQLiteBlobRefCatalog(device.sessions, device.clock),
        metadata_extractor=LocalUploadMetadataExtractor(),
    )
