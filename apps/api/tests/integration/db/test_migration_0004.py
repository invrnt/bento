from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, func, select

from bento.adapters.media.catalog import SQLiteBlobRefCatalog, SQLiteThumbnailCatalog
from bento.adapters.repositories.assets import SQLiteAssetRepository
from bento.adapters.repositories.devices import SQLiteDeviceRepository
from bento.domain.devices import Device, DevicePlatform
from bento.domain.security import EncryptionMetadata, EncryptionMode
from bento.domain.storage import BlobKind, BlobPart, BlobRef, StorageBackend
from bento.infrastructure.db.engine import create_session_factory, session_scope, sqlite_url
from bento.infrastructure.db.models import Base, BlobPartModel
from tests.integration.db.support import NOW, FixedClock, make_asset, migrated_session_factory

NEW_TABLES = {
    "blob_parts",
    "sync_outbox",
    "sync_field_clocks",
    "sync_purged",
    "sync_applied_batches",
    "sync_state",
    "devices",
    "backup_sources",
    "backup_files",
    "upload_sessions",
    "cache_entries",
    "inbox_items",
}
NEW_BLOB_COLUMNS = {"key_epoch", "format_version", "remote_deleted_at"}


def _config(db_path: Path) -> Config:
    api_root = Path(__file__).parents[3]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "migrations"))
    config.set_main_option("sqlalchemy.url", sqlite_url(db_path))
    return config


def _tables(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _columns(db_path: Path, table: str) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _indexes(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}


def test_0004_upgrades_existing_rows_and_downgrades_cleanly(tmp_path: Path) -> None:
    db_path = tmp_path / "bento.sqlite3"
    config = _config(db_path)
    command.upgrade(config, "0003_versioned_settings")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO blob_refs (id, asset_id, backend, kind, object_key, size_bytes, chat_id, message_id, file_id,"
            " encryption_mode, created_at) VALUES ('blob_legacy', NULL, 'telegram', 'original', 'raw/a', 12, '-100', '7',"
            " 'file-1', 'aes_gcm', '2026-01-01 00:00:00')"
        )

    command.upgrade(config, "head")

    assert NEW_TABLES <= _tables(db_path)
    assert NEW_BLOB_COLUMNS <= _columns(db_path, "blob_refs")
    assert {"ix_backup_files_state", "ix_cache_entries_last_accessed_at"} <= _indexes(db_path)
    catalog = SQLiteBlobRefCatalog(create_session_factory(sqlite_url(db_path)), FixedClock())
    legacy = asyncio.run(catalog.get("blob_legacy"))
    assert legacy is not None
    assert (legacy.chat_id, legacy.message_id, legacy.file_id, legacy.parts) == ("-100", "7", "file-1", ())
    assert (legacy.encryption.key_epoch, legacy.encryption.format_version) == (None, 1)

    command.downgrade(config, "0003_versioned_settings")

    assert not NEW_TABLES & _tables(db_path)
    assert not NEW_BLOB_COLUMNS & _columns(db_path, "blob_refs")
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT id, file_id FROM blob_refs").fetchall() == [("blob_legacy", "file-1")]
    command.upgrade(config, "head")
    assert NEW_TABLES <= _tables(db_path)


def test_migrated_schema_matches_orm_models(tmp_path: Path) -> None:
    db_path = tmp_path / "bento.sqlite3"
    command.upgrade(_config(db_path), "head")
    engine = create_engine(sqlite_url(db_path))
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            diffs = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    # FTS5 virtual tables are created by raw SQL in 0001 and have no ORM model.
    assert [diff for diff in diffs if not (_diff_table(diff) or "").startswith("asset_fts")] == []


def _diff_table(diff: object) -> str | None:
    entry = diff[0] if isinstance(diff, list) else diff
    for item in entry[1:]:  # type: ignore[index]
        if isinstance(item, str):
            return item
        if hasattr(item, "columns") and hasattr(item, "name"):
            return str(item.name)
        table = getattr(item, "table", None)
        if table is not None:
            return str(table.name)
    return None


def test_blob_parts_epoch_and_format_round_trip_through_the_catalog(tmp_path: Path) -> None:
    async def scenario() -> None:
        session_factory = migrated_session_factory(tmp_path)
        await SQLiteAssetRepository(session_factory).add(make_asset())
        catalog = SQLiteBlobRefCatalog(session_factory, FixedClock())
        thumbnails = SQLiteThumbnailCatalog(session_factory, FixedClock(), catalog)
        parts = (
            BlobPart(index=0, channel_id="-1001000000001", message_id="10", size_bytes=512),
            BlobPart(index=1, channel_id="-1001000000001", message_id="11", size_bytes=100),
        )
        blob_ref = BlobRef(
            id="blob_v2",
            asset_id="asset_1",
            backend=StorageBackend.TELEGRAM,
            kind=BlobKind.ORIGINAL,
            object_key="vault/blob_v2",
            size_bytes=580,
            sha256="b" * 64,
            encryption=EncryptionMetadata(mode=EncryptionMode.AES_GCM_STREAM, key_epoch=3, format_version=2),
            parts=parts,
        )

        await catalog.add(blob_ref)

        assert await catalog.get("blob_v2") == blob_ref
        assert await catalog.latest_for_asset("asset_1", BlobKind.ORIGINAL) == blob_ref

        reuploaded = replace(blob_ref, parts=(replace(parts[0], message_id="20"),))
        await catalog.add(reuploaded)
        assert await catalog.get("blob_v2") == reuploaded
        with session_scope(session_factory) as session:
            assert session.scalar(select(func.count()).select_from(BlobPartModel)) == 1

        thumbnail = replace(
            blob_ref, id="blob_thumb", kind=BlobKind.THUMBNAIL, object_key="vault/thumb", parts=(parts[0],)
        )
        await thumbnails.add(asset_id="asset_1", blob_ref=thumbnail, width=64, height=64)
        assert await thumbnails.latest_thumbnail_blob("asset_1") == thumbnail

        local = BlobRef(
            id="blob_local",
            asset_id="asset_1",
            backend=StorageBackend.LOCAL,
            kind=BlobKind.PREVIEW,
            object_key="previews/a.jpg",
            size_bytes=5,
        )
        await catalog.add(local)
        assert await catalog.get("blob_local") == local

        with sqlite3.connect(tmp_path / "bento.sqlite3") as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("DELETE FROM blob_refs WHERE id = 'blob_thumb'")
            assert connection.execute("SELECT COUNT(*) FROM blob_parts WHERE blob_ref_id = 'blob_thumb'").fetchone() == (0,)

    asyncio.run(scenario())


def test_device_repository_round_trip_and_single_current_device(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = SQLiteDeviceRepository(migrated_session_factory(tmp_path))
        laptop = Device(
            id="dev_laptop",
            name="Portátil de Ana",
            platform=DevicePlatform.LINUX,
            public_key="cHVibGljLWtleQ",
            added_at=NOW,
            telegram_auth_hash=-(2**62) + 7,
            current=True,
        )
        desktop = Device(
            id="dev_desktop",
            name="Escritorio",
            platform=DevicePlatform.WINDOWS,
            public_key="b3RoZXI",
            added_at=NOW + timedelta(minutes=5),
            last_seen_at=NOW + timedelta(hours=1),
        )

        await repository.save(laptop)
        await repository.save(desktop)

        assert await repository.get("dev_laptop") == laptop
        assert await repository.get("dev_missing") is None
        assert await repository.list() == (laptop, desktop)

        removed = replace(desktop, removed_at=NOW + timedelta(days=1))
        await repository.save(removed)
        assert await repository.list() == (laptop,)
        assert await repository.list(include_removed=True) == (laptop, removed)

        await repository.save(replace(removed, current=True))
        assert [device.id for device in await repository.list(include_removed=True) if device.current] == ["dev_desktop"]

    asyncio.run(scenario())


def test_device_repository_maps_unknown_platforms_to_other(tmp_path: Path) -> None:
    session_factory = migrated_session_factory(tmp_path)
    with sqlite3.connect(tmp_path / "bento.sqlite3") as connection:
        connection.execute(
            "INSERT INTO devices (id, name, platform, public_key, added_at, is_current)"
            " VALUES ('dev_phone', 'Teléfono', 'android', 'a2V5', '2026-01-01 12:00:00', 0)"
        )

    device = asyncio.run(SQLiteDeviceRepository(session_factory).get("dev_phone"))

    assert device is not None
    assert device.platform == DevicePlatform.OTHER
    assert device.added_at == NOW
