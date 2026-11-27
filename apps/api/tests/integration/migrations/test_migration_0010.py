from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from alembic import command

from bento.adapters.jobs import SQLiteJobQueue
from bento.domain.jobs import JobStatus, JobType
from bento.infrastructure.db.clock import SystemClock
from bento.infrastructure.db.engine import create_session_factory, sqlite_url
from tests.integration.db.test_migration_0004 import _config

BEFORE = "0009_smart_search"
REVISION = "0010_text_extraction_backfill"
_ASSET = (
    "INSERT INTO assets (id, kind, mode, filename, original_filename, mime_type, size_bytes, sha256, processing_state,"
    " favorite, created_at, updated_at, origin, deleted_at) VALUES (?, ?, 'drive', ?, ?, ?, 10, ?, 'indexed', 0,"
    " '2026-01-01 00:00:00', '2026-01-01 00:00:00', ?, ?)"
)


def _database(tmp_path: Path) -> Path:
    db_path = tmp_path / "db" / "bento.sqlite3"
    db_path.parent.mkdir(parents=True)
    command.upgrade(_config(db_path), BEFORE)
    return db_path


def _asset(db_path: Path, asset_id: str, mime: str, *, origin: str | None = "device", deleted: bool = False) -> None:
    kind = "pdf" if mime == "application/pdf" else "document" if mime.startswith("text/") else "image"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            _ASSET,
            (asset_id, kind, f"{asset_id}.bin", f"{asset_id}.bin", mime, asset_id.ljust(64, "0")[:64], origin,
             "2026-01-02 00:00:00" if deleted else None),
        )


def _backfill_jobs(db_path: Path) -> list[tuple[str, str, int, dict[str, object]]]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT type, status, priority, payload FROM jobs ORDER BY created_at").fetchall()
    return [(row[0], row[1], row[2], json.loads(row[3])) for row in rows]


def test_0010_queues_one_text_only_reindex_for_a_library_with_documents(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    _asset(db_path, "asset_txt", "text/plain; charset=utf-8")
    _asset(db_path, "asset_pdf", "application/pdf")

    command.upgrade(_config(db_path), "head")

    assert _backfill_jobs(db_path) == [("reindex", "queued", 2, {"text_only": True})]
    # The queue reads it like any job (timestamps and payload in the app's formats).
    queue = SQLiteJobQueue(create_session_factory(sqlite_url(db_path)), SystemClock())
    claimed = asyncio.run(queue.claim_next("worker-test"))
    assert claimed is not None and claimed.type is JobType.REINDEX and claimed.payload == {"text_only": True}
    assert claimed.status is JobStatus.RUNNING

    command.downgrade(_config(db_path), BEFORE)
    assert len(_backfill_jobs(db_path)) == 1  # a job that already started is left alone


def test_0010_queues_nothing_without_own_live_documents(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    _asset(db_path, "asset_img", "image/jpeg")
    _asset(db_path, "asset_inbox", "text/plain", origin="telegram_inbox")
    _asset(db_path, "asset_peer", "application/pdf", origin=None)
    _asset(db_path, "asset_trash", "text/plain", deleted=True)

    command.upgrade(_config(db_path), "head")

    assert _backfill_jobs(db_path) == []


def test_0010_downgrade_removes_a_backfill_that_has_not_run(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    _asset(db_path, "asset_md", "text/markdown")
    command.upgrade(_config(db_path), REVISION)
    assert len(_backfill_jobs(db_path)) == 1

    command.downgrade(_config(db_path), BEFORE)

    assert _backfill_jobs(db_path) == []
