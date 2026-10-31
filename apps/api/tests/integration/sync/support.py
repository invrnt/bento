"""Two (or more) Bento devices of one account in one process: separate SQLite databases and key stores on a
shared fake Telegram cloud, each with a test `VaultSessionPort` built on the fake transport and `VaultCrypto`."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.fake_telegram import FakeTelegramOptions
from bento.adapters.media.catalog import SQLiteBlobRefCatalog
from bento.adapters.repositories import SQLiteAlbumRepository, SQLiteAssetRepository, SQLiteFolderRepository
from bento.adapters.security import InMemoryKeyStore, VaultCrypto
from bento.adapters.sync import SQLiteSyncAdapters, install_change_capture
from bento.application.drive import DriveUseCases
from bento.application.photos import PhotosUseCases
from bento.application.sync import SyncEngine, SyncPolicy
from bento.domain.account import TelegramAccount
from bento.domain.assets import Asset, AssetKind, AssetMetadata, AssetMode, ProcessingState
from bento.domain.security import DeviceIdentity, EncryptionMetadata, EncryptionMode, VaultKeyring
from bento.domain.storage import BlobKind, BlobPart, BlobRef, StorageBackend
from bento.domain.vault import VaultHeader, VaultLayout, VaultState, VaultStatus
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import (
    AlbumAssetModel,
    AlbumModel,
    AssetModel,
    BlobRefModel,
    DeviceModel,
    FolderModel,
    ThumbnailModel,
)
from bento.infrastructure.runtime import TelegramRuntime, create_fake_telegram_runtime
from bento.ports.vault import VaultContext
from tests.integration.db.support import migrated_session_factory
from tests.integration.fake_telegram.support import sign_in

VAULT_ID = "vlt_sync_test"
ACCOUNT = TelegramAccount(user_id=777000001, display_name="Ana Demo")
CRYPTO = VaultCrypto()


@dataclass
class SyncClock:
    """Shared wall clock of every device (ms for HLCs, datetimes for rows)."""

    current: datetime = field(default_factory=lambda: datetime(2026, 3, 1, 12, 0, tzinfo=UTC))

    def now(self) -> datetime:
        return self.current

    def now_ms(self) -> int:
        return int(self.current.timestamp() * 1000)

    def advance(self, seconds: float = 1.0) -> None:
        self.current += timedelta(seconds=seconds)


class NoopManifest:
    async def append(self, **kwargs: Any) -> None:
        del kwargs


class FakeVaultSession:
    """`VaultSessionPort` test double: layout and keyring in memory, header through the fake transport."""

    def __init__(self, runtime: TelegramRuntime, identity: DeviceIdentity) -> None:
        self.runtime = runtime
        self.identity = identity
        self.layout: VaultLayout | None = None
        self.keyring: VaultKeyring | None = None
        self.keyring_updates: list[VaultKeyring] = []

    async def status(self) -> VaultStatus:
        if self.layout is None:
            return VaultStatus(state=VaultState.NO_VAULT)
        if self.keyring is None:
            return VaultStatus(state=VaultState.LOCKED, vault_id=self.layout.vault_id)
        return VaultStatus(state=VaultState.READY, vault_id=self.layout.vault_id)

    async def current(self) -> VaultContext | None:
        if self.layout is None or self.keyring is None:
            return None
        return VaultContext(layout=self.layout, keyring=self.keyring, device=self.identity, account=ACCOUNT)

    async def require(self) -> VaultContext:
        context = await self.current()
        assert context is not None
        return context

    async def device_identity(self) -> DeviceIdentity:
        return self.identity

    async def install(self, layout: VaultLayout, keyring: VaultKeyring) -> VaultStatus:
        self.layout, self.keyring = layout, keyring
        return await self.status()

    async def update_keyring(self, keyring: VaultKeyring) -> None:
        self.keyring = keyring
        self.keyring_updates.append(keyring)

    async def read_header(self) -> VaultHeader | None:
        assert self.layout is not None and self.keyring is not None
        text = await self.runtime.transport.read_header_text(self.layout)
        if text is None:
            return None
        header = VaultHeader.from_json(text)
        if not CRYPTO.verify_header_mac(self.keyring, header.canonical_unsigned_bytes(), header.mac):
            return None
        return header

    async def update_header(self, mutate: Callable[[VaultHeader], VaultHeader]) -> VaultHeader:
        assert self.layout is not None and self.keyring is not None
        current = await self.read_header()
        assert current is not None
        updated = mutate(current)
        signed = replace(updated, mac=CRYPTO.header_mac(self.keyring, updated.canonical_unsigned_bytes()))
        await self.runtime.transport.publish_header_text(self.layout, signed.to_json())
        return signed


@dataclass
class SyncDevice:
    name: str
    factory: sessionmaker[Session]
    adapters: SQLiteSyncAdapters
    vault: FakeVaultSession
    runtime: TelegramRuntime
    engine: SyncEngine
    clock: SyncClock

    @property
    def device_id(self) -> str:
        return self.vault.identity.device_id

    @property
    def drive(self) -> DriveUseCases:
        return DriveUseCases(assets=self.assets, folders=self.folders, manifest=NoopManifest(), clock=self.clock)

    @property
    def photos(self) -> PhotosUseCases:
        return PhotosUseCases(assets=self.assets, albums=self.albums, clock=self.clock)

    @property
    def assets(self) -> SQLiteAssetRepository:
        return SQLiteAssetRepository(self.factory)

    @property
    def folders(self) -> SQLiteFolderRepository:
        return SQLiteFolderRepository(self.factory)

    @property
    def albums(self) -> SQLiteAlbumRepository:
        return SQLiteAlbumRepository(self.factory)

    async def context(self) -> VaultContext:
        return await self.vault.require()

    async def sync(self) -> None:
        """One full cycle: attach, flush everything pending, pull to the tip, snapshot check."""
        await self.engine.sync_once(await self.context(), force_flush=True)

    async def push(self) -> int:
        context = await self.engine.prepare(await self.context())
        return await self.engine.flush(context, force=True)

    async def pull(self) -> None:
        context = await self.engine.prepare(await self.context())
        await self.engine.pull(context)

    async def add_asset(self, asset_id: str, *, filename: str = "foto.jpg", folder_id: str | None = None, remote: bool = True) -> Asset:
        now = self.clock.now()
        asset = Asset(
            id=asset_id,
            kind=AssetKind.IMAGE,
            mode=AssetMode.PHOTOS,
            folder_id=folder_id,
            filename=filename,
            metadata=AssetMetadata(
                original_filename=filename,
                mime_type="image/jpeg",
                size_bytes=1234,
                sha256=hashlib.sha256(asset_id.encode()).hexdigest(),
                taken_at=now,
                exif={"camera": "test"},
            ),
            processing_state=ProcessingState.INDEXED,
            favorite=False,
            created_at=now,
            updated_at=now,
        )
        await self.assets.add(asset)
        if remote:
            await self.store_remote_original(asset_id)
        return asset

    async def store_remote_original(self, asset_id: str, *, blob_id: str | None = None) -> BlobRef:
        blob = BlobRef(
            id=blob_id or f"blob_{asset_id}",
            asset_id=asset_id,
            backend=StorageBackend.TELEGRAM,
            kind=BlobKind.ORIGINAL,
            object_key=f"vault/{blob_id or f'blob_{asset_id}'}",
            size_bytes=1290,
            sha256=hashlib.sha256(asset_id.encode()).hexdigest(),
            encryption=EncryptionMetadata(mode=EncryptionMode.AES_GCM_STREAM, key_epoch=1, format_version=2),
            parts=(BlobPart(index=0, channel_id="-1001000000001", message_id="7", size_bytes=1290),),
        )
        await SQLiteBlobRefCatalog(self.factory, self.clock).add(blob)
        return blob

    async def store_local_original(self, asset_id: str) -> BlobRef:
        blob = BlobRef(
            id=f"blob_{asset_id}",
            asset_id=asset_id,
            backend=StorageBackend.LOCAL,
            kind=BlobKind.ORIGINAL,
            object_key=f"originals/{asset_id}",
            size_bytes=1234,
            sha256=hashlib.sha256(asset_id.encode()).hexdigest(),
        )
        await SQLiteBlobRefCatalog(self.factory, self.clock).add(blob)
        return blob

    def purge(self, model: type[Any], key: Any) -> None:
        with session_scope(self.factory) as session:
            row = session.get(model, key)
            assert row is not None
            session.delete(row)


def make_cloud_device(
    root: Path, cloud_dir: Path, name: str, clock: SyncClock, *, policy: SyncPolicy | None = None
) -> SyncDevice:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    factory = migrated_session_factory(directory)
    install_change_capture(factory, now_ms=clock.now_ms, now=clock.now)
    adapters = SQLiteSyncAdapters.create(factory, clock, vector_dimensions=8, now_ms=clock.now_ms, now=clock.now)
    runtime = create_fake_telegram_runtime(
        cloud_dir, InMemoryKeyStore(), options=FakeTelegramOptions(device_model=name, poll_interval_seconds=0.01)
    )
    identity = CRYPTO.generate_device_identity()
    vault = FakeVaultSession(runtime, identity)
    engine = SyncEngine(
        vault=vault,
        transport=runtime.transport,
        crypto=CRYPTO,
        outbox=adapters.outbox,
        state=adapters.state,
        applier=adapters.applier,
        snapshots=adapters.snapshots,
        hlc=adapters.hlc,
        holds=adapters.holds,
        publisher=adapters.publisher,
        clock=clock,
        policy=policy or SyncPolicy(post_interval_seconds=0),
    )
    return SyncDevice(name=name, factory=factory, adapters=adapters, vault=vault, runtime=runtime, engine=engine, clock=clock)


async def create_vault(device: SyncDevice) -> VaultKeyring:
    await sign_in(device)  # type: ignore[arg-type]
    layout = await device.runtime.transport.create_vault(VAULT_ID)
    keyring = CRYPTO.generate_keyring(VAULT_ID)
    header = VaultHeader(
        vault_id=VAULT_ID,
        created_at=device.clock.now(),
        layout=layout,
        current_epoch=keyring.current_epoch,
        recovery=CRYPTO.wrap_for_recovery(keyring, CRYPTO.generate_recovery_code()),
    )
    signed = replace(header, mac=CRYPTO.header_mac(keyring, header.canonical_unsigned_bytes()))
    await device.runtime.transport.publish_header_text(layout, signed.to_json())
    await device.vault.install(layout, keyring)
    return keyring


async def join_vault(device: SyncDevice, host: SyncDevice) -> None:
    """What a pairing grant does: same layout and keyring on another signed-in device."""
    await sign_in(device)  # type: ignore[arg-type]
    assert host.vault.layout is not None and host.vault.keyring is not None
    await device.vault.install(host.vault.layout, host.vault.keyring)


def synced_state(factory: sessionmaker[Session]) -> dict[str, Any]:
    """Synced columns of every tracked table (device-local columns excluded) for convergence checks."""
    with session_scope(factory) as session:
        folders = {
            row.id: (row.name, row.parent_id, _iso(row.created_at), _iso(row.deleted_at))
            for row in session.scalars(select(FolderModel))
        }
        assets = {
            row.id: (
                row.kind,
                row.mode,
                row.folder_id,
                row.filename,
                row.original_filename,
                row.mime_type,
                row.size_bytes,
                row.sha256,
                _iso(row.taken_at),
                row.exif_json,
                row.favorite,
                _iso(row.created_at),
                _iso(row.deleted_at),
            )
            for row in session.scalars(select(AssetModel))
        }
        albums = {row.id: (row.title, _iso(row.created_at), _iso(row.deleted_at)) for row in session.scalars(select(AlbumModel))}
        items = sorted((row.album_id, row.asset_id) for row in session.scalars(select(AlbumAssetModel)))
        blobs = {
            row.id: (
                row.asset_id,
                row.kind,
                row.size_bytes,
                row.sha256,
                row.encryption_mode,
                row.key_epoch,
                row.format_version,
                [(part.part_index, part.channel_id, part.message_id, part.size_bytes) for part in row.parts],
            )
            for row in session.scalars(select(BlobRefModel).where(BlobRefModel.backend == "telegram"))
        }
        thumbnails = {
            row.id: (row.asset_id, row.blob_ref_id, row.width, row.height) for row in session.scalars(select(ThumbnailModel))
        }
        devices = {
            row.id: (row.name, row.platform, row.public_key, row.telegram_auth_hash, _iso(row.added_at), _iso(row.removed_at))
            for row in session.scalars(select(DeviceModel))
        }
    return {
        "folders": folders,
        "assets": assets,
        "albums": albums,
        "album_items": items,
        "blobs": blobs,
        "thumbnails": thumbnails,
        "devices": devices,
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()
