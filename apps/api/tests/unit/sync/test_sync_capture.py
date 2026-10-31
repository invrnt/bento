"""Change capture (adapter unit tests on a temporary SQLite database)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.media.catalog import SQLiteBlobRefCatalog, SQLiteThumbnailCatalog
from bento.adapters.repositories import SQLiteAlbumRepository, SQLiteAssetRepository, SQLiteFolderRepository
from bento.adapters.sync import SYNC_APPLY, install_change_capture
from bento.domain.assets import ProcessingState
from bento.domain.drive import Folder
from bento.domain.photos import Album
from bento.domain.security import EncryptionMetadata, EncryptionMode
from bento.domain.storage import BlobKind, BlobPart, BlobRef, StorageBackend
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import (
    AssetModel,
    BlobRefModel,
    FolderModel,
    SyncFieldClockModel,
    SyncOutboxModel,
    SyncPurgedModel,
    SyncStateModel,
)
from tests.integration.db.support import NOW, FixedClock, make_asset, migrated_session_factory

DEVICE = "dev_capture"


@pytest.fixture
def factory(tmp_path: Path) -> sessionmaker[Session]:
    session_factory = migrated_session_factory(tmp_path)
    ticks = iter(range(1_000, 10_000_000, 10))
    install_change_capture(session_factory, now_ms=lambda: next(ticks), now=lambda: NOW)
    with session_scope(session_factory) as session:
        session.add(SyncStateModel(key="capture", value=json.dumps({"vault_id": "vlt_t", "device_id": DEVICE}), updated_at=NOW))
    return session_factory


def ops(factory: sessionmaker[Session]) -> list[tuple[str, str, str, dict[str, Any]]]:
    with session_scope(factory) as session:
        rows = session.scalars(select(SyncOutboxModel).order_by(SyncOutboxModel.seq))
        return [(row.entity, row.entity_id, row.kind, dict(row.fields_json)) for row in rows]


def clear(factory: sessionmaker[Session]) -> None:
    with session_scope(factory) as session:
        session.query(SyncOutboxModel).delete()


def remote_blob(asset_id: str, *, blob_id: str = "blob_1", parts: int = 1) -> BlobRef:
    return BlobRef(
        id=blob_id,
        asset_id=asset_id,
        backend=StorageBackend.TELEGRAM,
        kind=BlobKind.ORIGINAL,
        object_key=f"vault/{blob_id}",
        size_bytes=300,
        sha256="b" * 64,
        encryption=EncryptionMetadata(mode=EncryptionMode.AES_GCM_STREAM, key_epoch=1, format_version=2),
        parts=tuple(BlobPart(index=i, channel_id="-1001", message_id=str(10 + i), size_bytes=100) for i in range(parts)),
    )


def test_insert_update_delete_produce_upsert_diff_and_purge(factory: sessionmaker[Session]) -> None:
    async def scenario() -> None:
        folders = SQLiteFolderRepository(factory)
        folder = Folder(id="folder_1", name="Docs", parent_id=None, created_at=NOW, updated_at=NOW)
        await folders.add(folder)
        await folders.save(replace(folder, name="Papeles"))
        await folders.save(replace(folder, name="Papeles"))  # unchanged values: no op
        with session_scope(factory) as session:
            session.delete(session.get(FolderModel, "folder_1"))

    asyncio.run(scenario())
    assert ops(factory) == [
        ("folder", "folder_1", "upsert", {"name": "Docs", "parent_id": None, "created_at": NOW.isoformat(), "deleted_at": None}),
        ("folder", "folder_1", "upsert", {"name": "Papeles"}),
        ("folder", "folder_1", "purge", {}),
    ]
    with session_scope(factory) as session:
        assert session.get(SyncPurgedModel, ("folder", "folder_1")) is not None
        assert list(session.scalars(select(SyncFieldClockModel).where(SyncFieldClockModel.entity_id == "folder_1"))) == []


def test_untracked_columns_and_timezone_round_trips_are_not_changes(factory: sessionmaker[Session]) -> None:
    async def scenario() -> None:
        assets = SQLiteAssetRepository(factory)
        asset = make_asset("asset_1")
        await assets.add(asset)
        clear(factory)
        stored = await assets.get("asset_1")
        assert stored is not None
        await assets.save(replace(stored, processing_state=ProcessingState.FAILED_PARTIAL, updated_at=NOW.replace(hour=13)))
        await assets.save(stored.toggle_favorite(NOW))

    asyncio.run(scenario())
    assert ops(factory) == [("asset", "asset_1", "upsert", {"favorite": True})]


def test_field_clocks_follow_local_ops_and_hlc_increases(factory: sessionmaker[Session]) -> None:
    async def scenario() -> None:
        folders = SQLiteFolderRepository(factory)
        folder = Folder(id="folder_1", name="A", parent_id=None, created_at=NOW, updated_at=NOW)
        await folders.add(folder)
        await folders.save(replace(folder, name="B"))

    asyncio.run(scenario())
    with session_scope(factory) as session:
        hlcs = [row.hlc for row in session.scalars(select(SyncOutboxModel).order_by(SyncOutboxModel.seq))]
        clocks = {row.field: row.hlc for row in session.scalars(select(SyncFieldClockModel))}
        last = session.get(SyncStateModel, "last_hlc")
    assert hlcs == sorted(hlcs) and len(set(hlcs)) == 2
    assert all(hlc.endswith(DEVICE) for hlc in hlcs)
    assert clocks["name"] == hlcs[1] and clocks["parent_id"] == hlcs[0]
    assert last is not None and last.value == hlcs[1]


def test_local_blob_refs_are_ignored_until_they_become_remote_with_parts_folded(factory: sessionmaker[Session]) -> None:
    async def scenario() -> None:
        await SQLiteAssetRepository(factory).add(make_asset("asset_1"))
        catalog = SQLiteBlobRefCatalog(factory, FixedClock())
        local = BlobRef(
            id="blob_1", asset_id="asset_1", backend=StorageBackend.LOCAL, kind=BlobKind.ORIGINAL, object_key="o/1", size_bytes=128
        )
        clear(factory)
        await catalog.add(local)
        assert ops(factory) == []
        await catalog.add(remote_blob("asset_1", parts=2))
        await catalog.add(remote_blob("asset_1", parts=3))

    asyncio.run(scenario())
    recorded = ops(factory)
    assert [item[:3] for item in recorded] == [("blob", "blob_1", "upsert"), ("blob", "blob_1", "upsert")]
    full, update_only = recorded[0][3], recorded[1][3]
    assert set(full) == {
        "asset_id", "kind", "size_bytes", "sha256", "encryption_mode", "key_epoch", "format_version",
        "cipher_header_sha256", "parts",
    }
    assert full["parts"] == [
        {"index": 0, "channel_id": -1001, "message_id": 10, "size_bytes": 100},
        {"index": 1, "channel_id": -1001, "message_id": 11, "size_bytes": 100},
    ]
    assert set(update_only) == {"parts", "asset_id", "kind"} and len(update_only["parts"]) == 3


def test_deleting_blob_refs_purges_only_remote_ones(factory: sessionmaker[Session]) -> None:
    async def scenario() -> None:
        await SQLiteAssetRepository(factory).add(make_asset("asset_1"))
        catalog = SQLiteBlobRefCatalog(factory, FixedClock())
        await catalog.add(remote_blob("asset_1", blob_id="blob_remote"))
        await catalog.add(
            BlobRef(id="blob_local", asset_id="asset_1", backend=StorageBackend.LOCAL, kind=BlobKind.THUMBNAIL, object_key="t/1", size_bytes=1)
        )
        clear(factory)
        with session_scope(factory) as session:
            session.delete(session.get(BlobRefModel, "blob_remote"))
            session.delete(session.get(BlobRefModel, "blob_local"))

    asyncio.run(scenario())
    assert ops(factory) == [("blob", "blob_remote", "purge", {})]


def test_album_saves_net_bulk_replaced_items_into_adds_and_removals(factory: sessionmaker[Session]) -> None:
    async def scenario() -> None:
        assets = SQLiteAssetRepository(factory)
        for asset_id in ("asset_a", "asset_b", "asset_c"):
            await assets.add(make_asset(asset_id, sha256=asset_id[-1] * 64))
        albums = SQLiteAlbumRepository(factory)
        album = Album(id="album_1", title="Viaje", asset_ids=frozenset(), created_at=NOW, updated_at=NOW)
        await albums.add(album)
        album = replace(album, asset_ids=frozenset({"asset_a", "asset_b"}))
        await albums.save(album)
        clear(factory)
        await albums.save(replace(album, title="Viaje 2", asset_ids=frozenset({"asset_b", "asset_c"}), updated_at=NOW.replace(hour=14)))

    asyncio.run(scenario())
    recorded = sorted(ops(factory), key=lambda item: item[1])
    assert recorded == [
        ("album", "album_1", "upsert", {"title": "Viaje 2"}),
        ("album_item", "album_1:asset_a", "upsert", {"removed": True, "album_id": "album_1", "asset_id": "asset_a"}),
        (
            "album_item",
            "album_1:asset_c",
            "upsert",
            {"album_id": "album_1", "asset_id": "asset_c", "created_at": NOW.replace(hour=14).isoformat(), "removed": False},
        ),
    ]


def test_thumbnails_carry_their_asset_and_blob_ids(factory: sessionmaker[Session]) -> None:
    async def scenario() -> None:
        await SQLiteAssetRepository(factory).add(make_asset("asset_1"))
        clear(factory)
        catalog = SQLiteBlobRefCatalog(factory, FixedClock())
        thumb = BlobRef(id="blob_t", asset_id="asset_1", backend=StorageBackend.LOCAL, kind=BlobKind.THUMBNAIL, object_key="t/1", size_bytes=9)
        await SQLiteThumbnailCatalog(factory, FixedClock(), catalog).add(asset_id="asset_1", blob_ref=thumb, width=64, height=48)

    asyncio.run(scenario())
    [(entity, _, kind, fields)] = ops(factory)
    assert (entity, kind) == ("thumbnail", "upsert")
    assert fields == {"asset_id": "asset_1", "blob_id": "blob_t", "width": 64, "height": 48}


def test_bulk_orm_updates_of_synced_columns_are_captured(factory: sessionmaker[Session]) -> None:
    async def scenario() -> None:
        await SQLiteAssetRepository(factory).add(make_asset("asset_1"))
        clear(factory)
        with session_scope(factory) as session:
            session.execute(update(AssetModel).where(AssetModel.id == "asset_1").values(favorite=True, processing_state="failed"))
        with session_scope(factory) as session:
            session.execute(update(AssetModel).where(AssetModel.id == "asset_1").values(processing_state="indexed"))

    asyncio.run(scenario())
    assert ops(factory) == [("asset", "asset_1", "upsert", {"favorite": True})]


def test_sync_apply_sessions_and_detached_vaults_are_never_captured(factory: sessionmaker[Session]) -> None:
    with session_scope(factory) as session:
        session.info[SYNC_APPLY] = True
        session.add(FolderModel(id="folder_remote", name="Remota", created_at=NOW, updated_at=NOW))
    assert ops(factory) == []

    with session_scope(factory) as session:
        session.delete(session.get(SyncStateModel, "capture"))
    with session_scope(factory) as session:
        session.add(FolderModel(id="folder_offline", name="Sin vault", created_at=NOW, updated_at=NOW))
    assert ops(factory) == []


def test_factories_without_capture_installed_pay_nothing(tmp_path: Path) -> None:
    plain = migrated_session_factory(tmp_path)
    with session_scope(plain) as session:
        session.add(SyncStateModel(key="capture", value=json.dumps({"vault_id": "v", "device_id": DEVICE}), updated_at=NOW))
        session.add(FolderModel(id="folder_1", name="A", created_at=NOW, updated_at=NOW))
    assert ops(plain) == []


def test_asset_origin_stays_on_this_device(factory: sessionmaker[Session]) -> None:
    from bento.domain.assets import AssetOrigin

    async def scenario() -> None:
        imported = replace(make_asset("asset_imported"), origin=AssetOrigin.TELEGRAM_IMPORT)
        await SQLiteAssetRepository(factory).add(imported)
        await SQLiteBlobRefCatalog(factory, FixedClock()).add(remote_blob(imported.id))

    asyncio.run(scenario())
    captured = ops(factory)
    assert [entity for entity, entity_id, _, _ in captured if entity_id == "asset_imported"] == ["asset"]
    assert all("origin" not in fields for _, _, _, fields in captured)
