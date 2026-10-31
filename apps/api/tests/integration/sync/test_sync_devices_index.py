"""Device rows, keys rotation races, and `asset_index` propagation between two devices."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from bento.adapters.embeddings import MockEmbeddingProvider
from bento.adapters.media.catalog import SQLiteBlobRefCatalog
from bento.adapters.ocr import MockOCRAdapter
from bento.adapters.repositories.devices import SQLiteDeviceRepository
from bento.adapters.search.sqlite_fts import SQLiteFTSSearchIndex
from bento.adapters.search.sqlite_vec import SQLiteVecSearchIndex
from bento.application.drive import CreateFolderCommand
from bento.application.indexing import OCRIndexingService
from bento.application.indexing.embedding import EmbeddingIndexingService
from bento.application.sync import AssetIndexRecorder
from bento.application.sync.keys import build_keys_message
from bento.domain.devices import Device, DevicePlatform
from bento.domain.search import SearchQuery
from bento.domain.storage import BlobKind, BlobRef, StorageBackend
from bento.domain.sync import SyncMessageKind
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import DeviceModel, OCRBlockModel
from bento.infrastructure.settings import Settings
from bento.interfaces.http.routes_pairing import device_session_factory
from tests.integration.sync.support import (
    CRYPTO,
    NoopManifest,
    SyncClock,
    SyncDevice,
    create_vault,
    join_vault,
    make_cloud_device,
    synced_state,
)


@pytest.fixture
def pair(tmp_path: Path) -> tuple[SyncDevice, SyncDevice]:
    clock = SyncClock()
    cloud = tmp_path / "cloud"
    first = make_cloud_device(tmp_path, cloud, "laptop", clock)
    second = make_cloud_device(tmp_path, cloud, "desktop", clock)

    async def setup() -> None:
        await create_vault(first)
        await join_vault(second, first)
        await first.sync()
        await second.sync()

    asyncio.run(setup())
    return first, second


def test_device_ops_keep_local_columns_and_stamp_the_sender_last_seen(pair: tuple[SyncDevice, SyncDevice]) -> None:
    first, second = pair

    async def scenario() -> None:
        now = first.clock.now()
        own = Device(id=second.device_id, name="Escritorio", platform=DevicePlatform.LINUX, public_key="cHVi",
                     added_at=now, current=True, last_seen_at=now - timedelta(days=3))
        await SQLiteDeviceRepository(second.factory).save(own)
        for device in (first, second):
            await SQLiteDeviceRepository(device.factory).save(
                Device(id=first.device_id, name="Portátil", platform=DevicePlatform.LINUX, public_key="a2V5",
                       added_at=now, current=device is first, last_seen_at=now)
            )
        # The laptop records the desktop too (as a pairing host does) and renames it.
        await SQLiteDeviceRepository(first.factory).save(
            Device(id=second.device_id, name="Escritorio · Linux", platform=DevicePlatform.LINUX, public_key="cHVi",
                   added_at=now, current=False, last_seen_at=None)
        )
        await first.push()
        await second.pull()

        with session_scope(second.factory) as session:
            desktop = session.get(DeviceModel, second.device_id)
            laptop = session.get(DeviceModel, first.device_id)
        assert desktop is not None and laptop is not None
        assert desktop.name == "Escritorio · Linux"
        assert desktop.is_current is True and desktop.last_seen_at is not None
        assert desktop.last_seen_at.replace(tzinfo=UTC) == now - timedelta(days=3)
        assert laptop.is_current is False
        assert laptop.last_seen_at is not None and laptop.last_seen_at.replace(tzinfo=UTC) > now - timedelta(days=1)

    asyncio.run(scenario())


def test_pairing_device_factory_has_change_capture(tmp_path: Path) -> None:
    from tests.integration.storage_pipeline.support import migrated_data_dir

    data_dir = migrated_data_dir(tmp_path)
    settings = Settings(data_dir=str(data_dir), storage_backend="fake")
    factory = device_session_factory(settings)

    async def scenario() -> None:
        from bento.adapters.sync import SQLiteSyncOutbox, SQLiteSyncStateStore

        await SQLiteSyncStateStore(factory).set_value("capture", '{"device_id":"dev_host","vault_id":"vlt_x"}')
        await SQLiteDeviceRepository(factory).save(
            Device(id="dev_guest", name="Invitado", platform=DevicePlatform.MACOS, public_key="cHVi",
                   added_at=datetime(2026, 1, 1, tzinfo=UTC))
        )
        [entry] = await SQLiteSyncOutbox(factory).page()
        assert (entry.operation.entity.value, entry.operation.entity_id) == ("device", "dev_guest")
        assert "is_current" not in entry.operation.fields and "last_seen_at" not in entry.operation.fields

    asyncio.run(scenario())


def test_own_batch_sealed_with_an_old_epoch_after_rotation_is_published_again(pair: tuple[SyncDevice, SyncDevice]) -> None:
    first, second = pair

    async def scenario() -> None:
        await first.register()
        await first.push()
        await second.pull()
        stale_context = await first.context()
        rotated = CRYPTO.rotate_keyring(stale_context.keyring)
        recipients = {device.device_id: device.vault.identity.public_key for device in (first, second)}
        # Another process of the laptop rotates the keys while its sync loop still holds the old keyring.
        await first.runtime.transport.post_sync_document(
            stale_context.layout,
            SyncMessageKind.KEYS,
            build_keys_message(CRYPTO, first.vault.identity, rotated, recipients),
        )
        folder = await first.drive.create_folder(CreateFolderCommand(name="Durante la rotación"))
        await first.engine.flush(stale_context, force=True)  # vault session still answers epoch 1
        await second.pull()
        assert folder.id not in synced_state(second.factory)["folders"]

        await first.vault.update_keyring(rotated)
        await first.pull()  # sees its own epoch-1 batch rejected by the floor and queues the ops again
        await first.push()
        await second.pull()
        assert folder.id in synced_state(second.factory)["folders"]
        assert synced_state(first.factory) == synced_state(second.factory)

    asyncio.run(scenario())


def test_ocr_and_embedding_results_reach_peers_without_reindexing(pair: tuple[SyncDevice, SyncDevice], tmp_path: Path) -> None:
    first, second = pair

    async def scenario() -> None:
        await first.add_asset("asset_receipt", filename="recibo.jpg")
        local_original = tmp_path / "uploads" / "originals" / "recibo.jpg"
        local_original.parent.mkdir(parents=True)
        local_original.write_bytes(b"jpeg bytes")
        await SQLiteBlobRefCatalog(first.factory, first.clock).add(
            BlobRef(id="blob_local_receipt", asset_id="asset_receipt", backend=StorageBackend.LOCAL, kind=BlobKind.ORIGINAL,
                    object_key="originals/recibo.jpg", size_bytes=10)
        )
        recorder = AssetIndexRecorder(outbox=first.adapters.outbox, hlc=first.adapters.hlc, state=first.adapters.state)

        class Resolver:
            def resolve(self, blob_ref: object) -> Path:
                return local_original

        class LatestLocal:
            async def latest_for_asset(self, asset_id: str, kind: object) -> object:
                return await SQLiteBlobRefCatalog(first.factory, first.clock).get("blob_local_receipt")

        ocr = OCRIndexingService(
            assets=first.assets, blob_refs=LatestLocal(), resolver=Resolver(),  # type: ignore[arg-type]
            provider=MockOCRAdapter(default_text="Total factura panadería"), index=SQLiteFTSSearchIndex(first.factory, first.clock),
            manifest=NoopManifest(), clock=first.clock, index_recorder=recorder,  # type: ignore[arg-type]
        )
        embedding = EmbeddingIndexingService(
            assets=first.assets, blob_refs=LatestLocal(), resolver=Resolver(),  # type: ignore[arg-type]
            provider=MockEmbeddingProvider(dimensions=8), index=SQLiteVecSearchIndex(first.factory, first.clock, dimensions=8),
            manifest=NoopManifest(), clock=first.clock, index_recorder=recorder,  # type: ignore[arg-type]
        )
        await ocr.process_asset_ocr("asset_receipt")
        await embedding.process_asset_embedding("asset_receipt")
        await first.push()
        await second.pull()

        results = await SQLiteFTSSearchIndex(second.factory, second.clock).search(SearchQuery(text="panadería"))
        assert [hit.asset_id for hit in results.items] == ["asset_receipt"]
        with session_scope(second.factory) as session:
            assert [row.text for row in session.scalars(select(OCRBlockModel))] == ["Total factura panadería"]
        vectors = SQLiteVecSearchIndex(second.factory, second.clock, dimensions=8)
        _, query = await MockEmbeddingProvider(dimensions=8).embed_image("asset_receipt", local_original)
        hits = await vectors.search_vectors(query, limit=1)
        assert hits and hits[0].asset_id == "asset_receipt" and hits[0].distance < 1e-4

        # A device bootstrapped from a snapshot gets the index data too (snapshots wait until caught up).
        assert not await first.engine.maybe_snapshot(await first.context(), force=True)
        await first.pull()
        assert await first.engine.maybe_snapshot(await first.context(), force=True)
        third = make_cloud_device(tmp_path, tmp_path / "cloud", "tablet", first.clock)
        await join_vault(third, first)
        await third.sync()
        results = await SQLiteFTSSearchIndex(third.factory, third.clock).search(SearchQuery(text="panadería"))
        assert [hit.asset_id for hit in results.items] == ["asset_receipt"]

    asyncio.run(scenario())


def test_pairing_messages_and_unknown_text_are_skipped_by_the_sync_cursor(pair: tuple[SyncDevice, SyncDevice]) -> None:
    first, second = pair

    async def scenario() -> None:
        context = await first.context()
        transport = first.runtime.transport
        await transport.post_sync_text(context.layout, SyncMessageKind.PAIRING, '{"bento": "pair_request", "request_id": "r1"}')
        await transport.post_sync_document(context.layout, SyncMessageKind.PAIRING, b"opaque pairing frame")
        folder = await first.drive.create_folder(CreateFolderCommand(name="Después del emparejamiento"))
        await first.push()
        await second.pull()
        assert folder.id in synced_state(second.factory)["folders"]
        refs = await transport.list_sync_messages(context.layout, after_message_id=0, limit=1000)
        assert await second.adapters.state.get_value("last_applied_message_id") == str(refs[-1].message_id)

    asyncio.run(scenario())
