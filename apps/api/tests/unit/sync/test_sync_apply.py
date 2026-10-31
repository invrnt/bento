"""Applying remote ops: field-level LWW, trash vs rename, restore, terminal purges, folder cycles, idempotency."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.sync import SQLiteHlcSource, SQLiteSyncApplier, install_change_capture
from bento.domain.sync import SyncEntity, SyncOperation, SyncOpKind
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import (
    AlbumAssetModel,
    AssetModel,
    BlobRefModel,
    FolderModel,
    SyncOutboxModel,
    SyncPurgedModel,
    SyncStateModel,
    ThumbnailModel,
)
from bento.ports.sync import EntityState
from tests.integration.db.support import NOW, migrated_session_factory

LOCAL = "dev_local"
PEER = "dev_peer"
ISO = NOW.isoformat()


def hlc(ms: int, counter: int = 0, device: str = PEER) -> str:
    return f"{ms:016d}-{counter:06d}-{device}"


def op(entity: SyncEntity, entity_id: str, at: str, fields: dict[str, Any] | None = None, *, purge: bool = False) -> SyncOperation:
    return SyncOperation(
        op_id=f"op-{entity_id}-{at}",
        hlc=at,
        device_id=at.rsplit("-", 1)[-1] if at.count("-") == 2 else PEER,
        entity=entity,
        entity_id=entity_id,
        kind=SyncOpKind.PURGE if purge else SyncOpKind.UPSERT,
        fields={} if purge else dict(fields or {}),
    )


FOLDER_FIELDS = {"name": "Docs", "parent_id": None, "created_at": ISO, "deleted_at": None}
ASSET_FIELDS = {
    "kind": "image",
    "mode": "photos",
    "folder_id": None,
    "filename": "a.jpg",
    "original_filename": "a.jpg",
    "mime_type": "image/jpeg",
    "size_bytes": 10,
    "sha256": "a" * 64,
    "taken_at": None,
    "exif": {"camera": "x"},
    "favorite": False,
    "created_at": ISO,
    "deleted_at": None,
}


@pytest.fixture
def factory(tmp_path: Path) -> sessionmaker[Session]:
    session_factory = migrated_session_factory(tmp_path)
    install_change_capture(session_factory, now_ms=lambda: 1_000, now=lambda: NOW)
    with session_scope(session_factory) as session:
        session.add(SyncStateModel(key="capture", value=json.dumps({"vault_id": "vlt_t", "device_id": LOCAL}), updated_at=NOW))
    return session_factory


def apply(factory: sessionmaker[Session], *operations: SyncOperation, batch: str | None = None) -> int:
    applier = SQLiteSyncApplier(factory, now_ms=lambda: 1_000, now=lambda: NOW)
    return asyncio.run(applier.apply_batch(batch or f"batch-{operations[0].hlc}", 1, operations))


def asset(factory: sessionmaker[Session], asset_id: str = "asset_1") -> AssetModel | None:
    with session_scope(factory) as session:
        return session.get(AssetModel, asset_id)


def test_concurrent_edits_keep_the_newest_value_per_field_regardless_of_arrival_order(factory: sessionmaker[Session]) -> None:
    apply(factory, op(SyncEntity.ASSET, "asset_1", hlc(10), ASSET_FIELDS))
    newer_rename = op(SyncEntity.ASSET, "asset_1", hlc(30, device="dev_b"), {"filename": "b.jpg"})
    older_rename_and_favorite = op(SyncEntity.ASSET, "asset_1", hlc(20, device="dev_c"), {"filename": "c.jpg", "favorite": True})

    assert apply(factory, newer_rename) == 1
    assert apply(factory, older_rename_and_favorite) == 1  # only `favorite` is newer than its clock
    row = asset(factory)
    assert row is not None and (row.filename, row.favorite) == ("b.jpg", True)


def test_equal_clocks_break_ties_by_device_id(factory: sessionmaker[Session]) -> None:
    apply(factory, op(SyncEntity.FOLDER, "folder_1", hlc(10), FOLDER_FIELDS))
    apply(
        factory,
        op(SyncEntity.FOLDER, "folder_1", hlc(20, 0, "dev_b"), {"name": "B"}),
        op(SyncEntity.FOLDER, "folder_1", hlc(20, 0, "dev_a"), {"name": "A"}),
    )
    with session_scope(factory) as session:
        assert session.get(FolderModel, "folder_1").name == "B"  # type: ignore[union-attr]


def test_trash_and_rename_both_apply_and_restore_with_newer_clock_wins(factory: sessionmaker[Session]) -> None:
    apply(factory, op(SyncEntity.ASSET, "asset_1", hlc(10), ASSET_FIELDS))
    apply(factory, op(SyncEntity.ASSET, "asset_1", hlc(20, device="dev_a"), {"deleted_at": ISO}))
    apply(factory, op(SyncEntity.ASSET, "asset_1", hlc(19, device="dev_b"), {"filename": "renamed.jpg"}))
    row = asset(factory)
    assert row is not None and row.deleted_at is not None and row.filename == "renamed.jpg"

    apply(factory, op(SyncEntity.ASSET, "asset_1", hlc(15, device="dev_b"), {"deleted_at": None}))
    assert asset(factory).deleted_at is not None  # type: ignore[union-attr]  # older restore loses
    apply(factory, op(SyncEntity.ASSET, "asset_1", hlc(25, device="dev_b"), {"deleted_at": None}))
    assert asset(factory).deleted_at is None  # type: ignore[union-attr]


def test_purge_is_terminal_and_cascades_like_the_schema(factory: sessionmaker[Session]) -> None:
    apply(
        factory,
        op(SyncEntity.ASSET, "asset_1", hlc(10), ASSET_FIELDS),
        op(SyncEntity.BLOB, "blob_1", hlc(11), {"asset_id": "asset_1", "kind": "original", "size_bytes": 5, "sha256": None,
                                                "encryption_mode": "aes_gcm_stream", "key_epoch": 1, "format_version": 2,
                                                "parts": [{"index": 0, "channel_id": -100, "message_id": 4, "size_bytes": 5}]}),
        op(SyncEntity.THUMBNAIL, "thumb_1", hlc(12), {"asset_id": "asset_1", "blob_id": "blob_t", "width": 1, "height": 1}),
        op(SyncEntity.ALBUM_ITEM, "album_1:asset_1", hlc(13), {"album_id": "album_1", "asset_id": "asset_1", "created_at": ISO, "removed": False}),
    )
    assert apply(factory, op(SyncEntity.ASSET, "asset_1", hlc(50), purge=True)) == 1
    assert apply(factory, op(SyncEntity.ASSET, "asset_1", hlc(90), {"filename": "zombie.jpg"})) == 0
    assert apply(factory, op(SyncEntity.ASSET, "asset_1", hlc(91), purge=True)) == 0
    assert apply(factory, op(SyncEntity.ASSET_INDEX, "asset_1", hlc(92), {"ocr_text": "x"})) == 0
    with session_scope(factory) as session:
        assert session.get(AssetModel, "asset_1") is None
        assert session.get(ThumbnailModel, "thumb_1") is None
        assert list(session.scalars(select(AlbumAssetModel))) == []
        blob = session.get(BlobRefModel, "blob_1")
        assert blob is not None and blob.asset_id is None and len(blob.parts) == 1
        assert session.get(SyncPurgedModel, ("asset", "asset_1")).hlc == hlc(50)  # type: ignore[union-attr]


def test_applied_ops_are_never_captured_but_advance_the_local_hlc(factory: sessionmaker[Session]) -> None:
    apply(factory, op(SyncEntity.FOLDER, "folder_1", hlc(5_000), FOLDER_FIELDS))
    with session_scope(factory) as session:
        assert list(session.scalars(select(SyncOutboxModel))) == []
        last = session.get(SyncStateModel, "last_hlc")
    assert last is not None and last.value > hlc(5_000) and last.value.endswith(LOCAL)
    next_local = asyncio.run(SQLiteHlcSource(factory, now_ms=lambda: 1_000, now=lambda: NOW).next())
    assert next_local > hlc(5_000)


def test_reapplying_a_batch_or_its_ops_changes_nothing(factory: sessionmaker[Session]) -> None:
    operations = (op(SyncEntity.FOLDER, "folder_1", hlc(10), FOLDER_FIELDS), op(SyncEntity.FOLDER, "folder_1", hlc(11), {"name": "B"}))
    assert apply(factory, *operations, batch="batch-1") == 5
    assert apply(factory, *operations, batch="batch-1") == 0
    assert apply(factory, *operations, batch="batch-resent") == 0


def test_folder_cycles_move_the_latest_mover_to_the_root_in_any_order(tmp_path: Path) -> None:
    def converge(order: list[int], directory: Path) -> dict[str, str | None]:
        directory.mkdir()
        session_factory = migrated_session_factory(directory)
        with session_scope(session_factory) as session:
            session.add(SyncStateModel(key="capture", value=json.dumps({"vault_id": "v", "device_id": LOCAL}), updated_at=NOW))
        apply(
            session_factory,
            op(SyncEntity.FOLDER, "folder_a", hlc(1), {**FOLDER_FIELDS, "name": "A"}),
            op(SyncEntity.FOLDER, "folder_b", hlc(2), {**FOLDER_FIELDS, "name": "B"}),
            op(SyncEntity.FOLDER, "folder_c", hlc(3), {**FOLDER_FIELDS, "name": "C"}),
        )
        moves = [
            op(SyncEntity.FOLDER, "folder_a", hlc(10, device="dev_a"), {"parent_id": "folder_b"}),
            op(SyncEntity.FOLDER, "folder_b", hlc(11, device="dev_b"), {"parent_id": "folder_c"}),
            op(SyncEntity.FOLDER, "folder_c", hlc(12, device="dev_c"), {"parent_id": "folder_a"}),
        ]
        for index in order:
            apply(session_factory, moves[index])
        with session_scope(session_factory) as session:
            return {row.id: row.parent_id for row in session.scalars(select(FolderModel))}

    results = [converge(order, tmp_path / str(position)) for position, order in enumerate([[0, 1, 2], [2, 1, 0], [1, 2, 0]])]
    assert results[0] == results[1] == results[2] == {"folder_a": "folder_b", "folder_b": "folder_c", "folder_c": None}


def test_parent_pointing_to_a_purged_folder_moves_to_the_root_with_a_notice(factory: sessionmaker[Session]) -> None:
    apply(factory, op(SyncEntity.FOLDER, "folder_p", hlc(1), FOLDER_FIELDS), op(SyncEntity.FOLDER, "folder_c", hlc(2), FOLDER_FIELDS))
    apply(factory, op(SyncEntity.FOLDER, "folder_p", hlc(5), purge=True))
    apply(factory, op(SyncEntity.FOLDER, "folder_c", hlc(4, device="dev_late"), {"parent_id": "folder_p"}))
    with session_scope(factory) as session:
        assert session.get(FolderModel, "folder_c").parent_id is None  # type: ignore[union-attr]
        notice = session.get(SyncStateModel, "last_notice")
    assert notice is not None and json.loads(notice.value)["reason"] == "purged_parent"


def test_unknown_references_are_applied_as_is(factory: sessionmaker[Session]) -> None:
    apply(
        factory,
        op(SyncEntity.ASSET, "asset_1", hlc(10), {**ASSET_FIELDS, "folder_id": "folder_not_yet_here"}),
        op(SyncEntity.THUMBNAIL, "thumb_1", hlc(11), {"asset_id": "asset_unknown", "blob_id": "blob_unknown", "width": 2, "height": 2}),
    )
    with session_scope(factory) as session:
        assert session.get(AssetModel, "asset_1").folder_id == "folder_not_yet_here"  # type: ignore[union-attr]
        assert session.get(ThumbnailModel, "thumb_1").blob_ref_id == "blob_unknown"  # type: ignore[union-attr]


def test_album_item_removal_beats_older_adds_and_snapshots_honour_tombstones(factory: sessionmaker[Session]) -> None:
    key = "album_1:asset_1"
    item = {"album_id": "album_1", "asset_id": "asset_1", "created_at": ISO, "removed": False}
    apply(factory, op(SyncEntity.ALBUM_ITEM, key, hlc(10), item))
    apply(factory, op(SyncEntity.ALBUM_ITEM, key, hlc(20), {"removed": True, "album_id": "album_1", "asset_id": "asset_1"}))
    apply(factory, op(SyncEntity.ALBUM_ITEM, key, hlc(15, device="dev_stale"), item))
    with session_scope(factory) as session:
        assert list(session.scalars(select(AlbumAssetModel))) == []

    async def states() -> AsyncIterator[EntityState]:
        yield EntityState(SyncEntity.ALBUM_ITEM, key, item, {name: hlc(12) for name in item})

    applier = SQLiteSyncApplier(factory, now_ms=lambda: 1_000, now=lambda: NOW)
    asyncio.run(applier.apply_snapshot(states(), ()))
    with session_scope(factory) as session:
        assert list(session.scalars(select(AlbumAssetModel))) == []


def test_hlc_source_is_monotonic_across_restarts_and_clock_regressions(factory: sessionmaker[Session]) -> None:
    times = iter([5_000, 5_000, 4_000, 3_000, 9_000])
    issued = []
    for _ in range(3):
        source = SQLiteHlcSource(factory, now_ms=lambda: next(times), now=lambda: NOW)  # a new process each time
        issued.append(asyncio.run(source.next()))
    source = SQLiteHlcSource(factory, now_ms=lambda: next(times), now=lambda: NOW)
    asyncio.run(source.observe(hlc(8_000, 7)))
    issued.append(asyncio.run(source.next()))
    assert issued == sorted(issued) and len(set(issued)) == len(issued)
    assert issued[-1] > hlc(8_000, 7)
    assert issued[0].startswith("0000000000005000-000000")


def test_assets_from_peers_have_unknown_provenance_and_are_never_indexed_here(factory: sessionmaker[Session]) -> None:
    from bento.adapters.repositories.mappers import asset_from_model
    from bento.domain.errors import ValidationFailedError

    with pytest.raises(ValidationFailedError):  # `origin` is device-local: it is not a field on the wire
        op(SyncEntity.ASSET, "asset_1", hlc(10), {**ASSET_FIELDS, "origin": "device"})
    apply(factory, op(SyncEntity.ASSET, "asset_1", hlc(10), ASSET_FIELDS))

    row = asset(factory)
    assert row is not None and row.origin is None
    remote = asset_from_model(row)
    assert remote.origin is None and not remote.ai_indexing_allowed
