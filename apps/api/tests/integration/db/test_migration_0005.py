from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from alembic import command

from bento.adapters.repositories import SQLiteAssetRepository
from bento.domain.assets import AssetOrigin
from bento.infrastructure.db.engine import create_session_factory, sqlite_url
from tests.integration.db.test_migration_0004 import _columns, _config

_ASSET = (
    "INSERT INTO assets (id, kind, mode, filename, original_filename, mime_type, size_bytes, sha256, processing_state,"
    " favorite, created_at, updated_at) VALUES (?, 'image', 'photos', ?, ?, 'image/jpeg', 10, ?, 'indexed', 0,"
    " '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
)


def test_0005_backfills_origin_and_downgrades_cleanly(tmp_path: Path) -> None:
    db_path = tmp_path / "bento.sqlite3"
    config = _config(db_path)
    command.upgrade(config, "0004_telegram_first")
    with sqlite3.connect(db_path) as connection:
        connection.execute(_ASSET, ("asset_own", "own.jpg", "own.jpg", "a" * 64))
        connection.execute(_ASSET, ("asset_inbox", "forwarded.jpg", "forwarded.jpg", "b" * 64))
        connection.execute(
            "INSERT INTO inbox_items (message_id, state, asset_id, created_at, updated_at)"
            " VALUES (7, 'done', 'asset_inbox', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )
        connection.execute(
            "INSERT INTO inbox_items (message_id, state, asset_id, created_at, updated_at)"
            " VALUES (8, 'failed', NULL, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )

    command.upgrade(config, "head")

    assert "origin" in _columns(db_path, "assets")
    repository = SQLiteAssetRepository(create_session_factory(sqlite_url(db_path)))
    own = asyncio.run(repository.get("asset_own"))
    forwarded = asyncio.run(repository.get("asset_inbox"))
    assert own is not None and own.origin == AssetOrigin.DEVICE and own.ai_indexing_allowed
    assert forwarded is not None and forwarded.origin == AssetOrigin.TELEGRAM_INBOX and not forwarded.ai_indexing_allowed

    command.downgrade(config, "0004_telegram_first")

    assert "origin" not in _columns(db_path, "assets")
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT id FROM assets ORDER BY id").fetchall() == [("asset_inbox",), ("asset_own",)]
    command.upgrade(config, "head")
    assert "origin" in _columns(db_path, "assets")
