from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from tests.integration.db.test_migration_0004 import _columns, _config


def test_0006_adds_the_blob_binding_and_device_review_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "bento.sqlite3"
    config = _config(db_path)
    command.upgrade(config, "0005_asset_origin")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO devices (id, name, platform, public_key, added_at, is_current)"
            " VALUES ('dev_old', 'Viejo', 'linux', 'a2V5', '2026-01-01 00:00:00', 0)"
        )

    command.upgrade(config, "head")

    assert "cipher_header_sha256" in _columns(db_path, "blob_refs")
    assert {"introduced_by", "first_seen_at", "reviewed_at"} <= _columns(db_path, "devices")
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT introduced_by, first_seen_at, reviewed_at FROM devices WHERE id = 'dev_old'").fetchone()
    assert row == (None, "2026-01-01 00:00:00", "2026-01-01 00:00:00")  # existing devices count as reviewed

    command.downgrade(config, "0005_asset_origin")
    assert "cipher_header_sha256" not in _columns(db_path, "blob_refs")
    assert "reviewed_at" not in _columns(db_path, "devices")
    command.upgrade(config, "head")
