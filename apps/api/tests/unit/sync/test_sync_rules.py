"""Pure sync rules: hold-rule planning, batch limits, keys grants, codecs, envelope prefix, folder cycles."""

from __future__ import annotations

import json
import struct
from datetime import UTC, datetime

import pytest

from bento.application.sync.batching import plan_flush, split_batches
from bento.application.sync.codec import b64url_decode, b64url_encode, decode_vector, encode_vector
from bento.application.sync.envelope import envelope_epoch
from bento.application.sync.keys import merge_granted_keyring, parse_keys_message
from bento.application.sync.merge import cycle_breaker, find_folder_cycle
from bento.application.sync.ports import AssetHoldState
from bento.application.sync.snapshot import parse_snapshot, snapshot_payload
from bento.domain.errors import IntegrityError, ValidationFailedError
from bento.domain.security import VaultKeyring
from bento.domain.sync import SyncEntity, SyncOperation, SyncOpKind
from bento.ports.sync import EntityState, OutboxEntry

KEY_A, KEY_B, KEY_C = b"a" * 32, b"b" * 32, b"c" * 32


def entry(seq: int, entity: SyncEntity, entity_id: str, fields: dict[str, object] | None = None, *, purge: bool = False, size: int = 100) -> OutboxEntry:
    operation = SyncOperation(
        op_id=f"op{seq}",
        hlc=f"{seq:016d}-000000-dev_a",
        device_id="dev_a",
        entity=entity,
        entity_id=entity_id,
        kind=SyncOpKind.PURGE if purge else SyncOpKind.UPSERT,
        fields={} if purge else dict(fields or {}),
    )
    return OutboxEntry(seq=seq, operation=operation, size_bytes=size)


def seqs(batches: tuple[tuple[OutboxEntry, ...], ...]) -> list[list[int]]:
    return [[item.seq for item in batch] for batch in batches]


def test_hold_rule_withholds_asset_scoped_ops_until_the_remote_original_and_orders_them_after_it() -> None:
    entries = [
        entry(1, SyncEntity.FOLDER, "folder_1", {"name": "A"}),
        entry(2, SyncEntity.ASSET, "asset_1", {"filename": "a.jpg"}),
        entry(3, SyncEntity.THUMBNAIL, "thumb_1", {"asset_id": "asset_1"}),
        entry(4, SyncEntity.ALBUM_ITEM, "album_1:asset_1", {"removed": False}),
        entry(5, SyncEntity.ASSET_INDEX, "asset_1", {"ocr_text": "x"}),
        entry(6, SyncEntity.ASSET, "asset_2", {"filename": "b.jpg"}),
        entry(7, SyncEntity.BLOB, "blob_1", {"asset_id": "asset_1", "kind": "original"}),
        entry(8, SyncEntity.ASSET, "asset_gone", {"filename": "x"}),
        entry(9, SyncEntity.ASSET, "asset_gone", purge=True),
        entry(10, SyncEntity.BLOB, "blob_thumb", {"asset_id": "asset_2", "kind": "thumbnail"}),
    ]
    states = {"asset_1": AssetHoldState.REMOTE, "asset_2": AssetHoldState.LOCAL, "asset_gone": AssetHoldState.MISSING}

    plan = plan_flush(entries, states)

    assert seqs(plan.batches) == [[1, 7, 2, 3, 4, 5, 9, 10]]
    assert plan.held == (6,)
    assert plan.dropped == (8,)


def test_assets_already_released_publish_in_place() -> None:
    plan = plan_flush([entry(1, SyncEntity.ASSET, "asset_1", {"favorite": True})], {"asset_1": AssetHoldState.REMOTE})
    assert seqs(plan.batches) == [[1]] and plan.held == () and plan.dropped == ()


def test_batches_split_by_op_count_and_json_size() -> None:
    many = [entry(index, SyncEntity.FOLDER, f"folder_{index}") for index in range(1, 601)]
    assert [len(batch) for batch in split_batches(many)] == [256, 256, 88]
    big = [entry(1, SyncEntity.FOLDER, "a", size=300_000), entry(2, SyncEntity.FOLDER, "b", size=300_000), entry(3, SyncEntity.FOLDER, "c", size=600_000)]
    assert seqs(split_batches(big)) == [[1], [2], [3]]


def test_keys_messages_parse_strictly() -> None:
    message = parse_keys_message(json.dumps({"bento": "keys", "v": 1, "vault_id": "vlt_1", "epoch": 2, "grants": {"dev_a": "xyz"}}).encode())
    assert (message.vault_id, message.epoch, dict(message.grants)) == ("vlt_1", 2, {"dev_a": "xyz"})
    for bad in (b"not json", b"[]", json.dumps({"bento": "keys", "v": 2}).encode(),
                json.dumps({"bento": "keys", "v": 1, "vault_id": "v", "epoch": True, "grants": {}}).encode(),
                json.dumps({"bento": "keys", "v": 1, "vault_id": "v", "epoch": 2, "grants": {"dev_a": 3}}).encode()):
        with pytest.raises(ValidationFailedError):
            parse_keys_message(bad)


def test_granted_keyrings_must_extend_the_local_one() -> None:
    current = VaultKeyring(vault_id="vlt_1", current_epoch=1, keys={1: KEY_A})
    granted = VaultKeyring(vault_id="vlt_1", current_epoch=2, keys={1: KEY_A, 2: KEY_B})

    merged = merge_granted_keyring(current, granted, epoch=2)
    assert merged is not None and merged.current_epoch == 2 and merged.keys == {1: KEY_A, 2: KEY_B}
    assert merge_granted_keyring(merged, granted, epoch=2) is None
    without_old = VaultKeyring(vault_id="vlt_1", current_epoch=2, keys={2: KEY_B})
    assert merge_granted_keyring(current, without_old, epoch=2).keys == {1: KEY_A, 2: KEY_B}  # type: ignore[union-attr]
    with pytest.raises(IntegrityError):
        merge_granted_keyring(current, VaultKeyring(vault_id="vlt_1", current_epoch=2, keys={1: KEY_C, 2: KEY_B}), epoch=2)
    with pytest.raises(IntegrityError):
        merge_granted_keyring(current, VaultKeyring(vault_id="vlt_other", current_epoch=2, keys={2: KEY_B}), epoch=2)
    with pytest.raises(IntegrityError):
        merge_granted_keyring(current, granted, epoch=3)


def test_codecs_are_strict_and_round_trip() -> None:
    assert b64url_decode(b64url_encode(b"\xff\x00grant")) == b"\xff\x00grant"
    for bad in ("abc=", "a+b/", "a", "ab$"):
        with pytest.raises(ValidationFailedError):
            b64url_decode(bad)
    vector = (0.5, -1.25, 3.0)
    assert decode_vector(encode_vector(vector), 3) == vector
    with pytest.raises(ValidationFailedError):
        decode_vector(encode_vector(vector), 4)
    with pytest.raises(ValidationFailedError):
        decode_vector(b64url_encode(struct.pack("<f", float("nan"))), 1)


def test_envelope_epoch_reads_the_public_prefix() -> None:
    envelope = b"BENV" + bytes([1, 1]) + struct.pack(">I", 7) + b"\x00" * 12 + b"ciphertext"
    assert envelope_epoch(envelope) == 7
    assert envelope_epoch(b"XXXX" + envelope[4:]) is None
    assert envelope_epoch(b"BENV") is None


def test_folder_cycle_detection_and_deterministic_breaker() -> None:
    parents = {"a": "b", "b": "c", "c": "a", "d": "a", "e": None}
    assert set(find_folder_cycle("d", parents.get) or ()) == {"a", "b", "c"}
    assert find_folder_cycle("e", parents.get) is None
    assert cycle_breaker(("a", "b", "c"), {"a": "0002", "b": "0009", "c": "0005"}) == "b"
    assert cycle_breaker(("a", "b"), {"a": "0001", "b": "0001"}) == "b"


def test_snapshot_payload_round_trips_and_rejects_unsynced_fields() -> None:
    state = EntityState(SyncEntity.FOLDER, "folder_1", {"name": "A"}, {"name": "0001-000000-dev_a"})
    payload = snapshot_payload(
        snapshot_id="s1", device_id="dev_a", vault_id="vlt_1", covers_through_message_id=9,
        created_at=datetime(2026, 1, 1, tzinfo=UTC), states=[state], purged=[("asset", "asset_9", "0002-000000-dev_a")],
    )
    parsed = parse_snapshot(json.loads(json.dumps(payload)))
    assert parsed.states == (state,) and parsed.purged == (("asset", "asset_9", "0002-000000-dev_a"),)
    assert parsed.covers_through_message_id == 9
    payload["states"][0]["fields"]["processing_state"] = "indexed"
    with pytest.raises(ValidationFailedError):
        parse_snapshot(payload)
