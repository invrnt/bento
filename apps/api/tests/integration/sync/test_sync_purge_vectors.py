"""A synced asset purge deletes its chunk vectors explicitly, in every space, even without the FK cascade."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.search.sqlite_vec import pack_vector
from bento.adapters.sync import SQLiteSyncApplier, install_change_capture
from bento.domain.sync import SyncEntity, SyncOperation, SyncOpKind
from bento.infrastructure.db.engine import session_scope, sqlite_url
from bento.infrastructure.db.models import SyncStateModel
from tests.integration.db.support import NOW, migrated_session_factory
from tests.integration.search.vector_support import space, unit

PEER = "dev_peer"
ISO = NOW.isoformat()
SPACE_A = space("model-a", 3)
SPACE_B = space("model-b", 3)
ASSET_FIELDS = {
    "kind": "pdf",
    "mode": "drive",
    "folder_id": None,
    "filename": "factura.pdf",
    "original_filename": "factura.pdf",
    "mime_type": "application/pdf",
    "size_bytes": 10,
    "sha256": "b" * 64,
    "taken_at": None,
    "exif": None,
    "favorite": False,
    "created_at": ISO,
    "deleted_at": None,
}


def _op(entity_id: str, ms: int, *, purge: bool = False) -> SyncOperation:
    return SyncOperation(
        op_id=f"op-{entity_id}-{ms}",
        hlc=f"{ms:016d}-000000-{PEER}",
        device_id=PEER,
        entity=SyncEntity.ASSET,
        entity_id=entity_id,
        kind=SyncOpKind.PURGE if purge else SyncOpKind.UPSERT,
        fields={} if purge else dict(ASSET_FIELDS),
    )


def _factory_without_foreign_keys(tmp_path: Path) -> sessionmaker[Session]:
    migrated_session_factory(tmp_path, session_hooks=False)
    engine = create_engine(sqlite_url(tmp_path / "bento.sqlite3"), future=True)  # no `PRAGMA foreign_keys=ON`
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    install_change_capture(factory, now_ms=lambda: 1_000, now=lambda: NOW)
    with session_scope(factory) as session:
        session.add(SyncStateModel(key="capture", value=json.dumps({"vault_id": "vlt_t", "device_id": "dev_local"}), updated_at=NOW))
    return factory


def _chunk_rows(factory: sessionmaker[Session], asset_id: str) -> int:
    with session_scope(factory) as session:
        return int(
            session.execute(
                text("SELECT COUNT(*) FROM asset_embedding_chunks WHERE asset_id = :asset_id"), {"asset_id": asset_id}
            ).scalar()
            or 0
        )


def test_purge_deletes_chunk_vectors_of_every_space(tmp_path: Path) -> None:
    factory = _factory_without_foreign_keys(tmp_path)
    applier = SQLiteSyncApplier(factory, now_ms=lambda: 1_000, now=lambda: NOW)
    asyncio.run(applier.apply_batch("batch-1", 1, (_op("asset_1", 10), _op("asset_2", 11))))
    vector = pack_vector(unit(1.0, 0.0, 0.0))
    with session_scope(factory) as session:
        for space_id in (SPACE_A.id, SPACE_B.id):
            for asset_id in ("asset_1", "asset_2"):
                for chunk_no in range(2):
                    session.execute(
                        text(
                            "INSERT INTO asset_embedding_chunks (space_id, asset_id, chunk_no, page, vector, created_at) "
                            "VALUES (:space, :asset, :chunk, :page, :vector, :created)"
                        ),
                        {"space": space_id, "asset": asset_id, "chunk": chunk_no, "page": chunk_no + 1, "vector": vector, "created": ISO},
                    )
    assert _chunk_rows(factory, "asset_1") == 4

    assert asyncio.run(applier.apply_batch("batch-2", 2, (_op("asset_1", 50, purge=True),))) == 1

    assert _chunk_rows(factory, "asset_1") == 0
    assert _chunk_rows(factory, "asset_2") == 4  # other assets keep their vectors

