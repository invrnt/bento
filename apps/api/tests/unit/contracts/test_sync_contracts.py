from __future__ import annotations

import json
import random

import pytest

from bento.domain.errors import ValidationFailedError
from bento.domain.sync import (
    Hlc,
    SyncBatch,
    SyncEntity,
    SyncMessageKind,
    SyncOperation,
    SyncOpKind,
    fields_to_apply,
    hlc_receive,
    hlc_tick,
)

HLC_A = "0001730000000000-000001-dev_aa"


def test_hlc_format_parse_round_trip_and_rejects_malformed_values() -> None:
    clock = Hlc(1_730_000_000_123, 42, "dev_ab12")

    assert clock.format() == "0001730000000123-000042-dev_ab12"
    assert Hlc.parse(clock.format()) == clock
    for value in ("", "1730-000042-dev_ab12", "0001730000000123-42-dev_ab12", "0001730000000123-000042-ab12"):
        with pytest.raises(ValidationFailedError):
            Hlc.parse(value)
    with pytest.raises(ValidationFailedError):
        Hlc(0, 1_000_000, "dev_a")
    with pytest.raises(ValidationFailedError):
        Hlc(0, 0, "device")


def test_hlc_tick_uses_wall_clock_or_bumps_counter_and_carries_on_overflow() -> None:
    last = Hlc(1_000, 5, "dev_a")

    assert hlc_tick(last, 2_000) == Hlc(2_000, 0, "dev_a")
    assert hlc_tick(last, 1_000) == Hlc(1_000, 6, "dev_a")
    assert hlc_tick(last, 10) == Hlc(1_000, 6, "dev_a")
    assert hlc_tick(Hlc(1_000, 999_999, "dev_a"), 500) == Hlc(1_001, 0, "dev_a")


def test_hlc_receive_is_greater_than_local_and_remote() -> None:
    local = Hlc(1_000, 3, "dev_a")
    cases = [
        (Hlc(1_000, 9, "dev_b"), 900, Hlc(1_000, 10, "dev_a")),
        (Hlc(2_000, 4, "dev_b"), 1_500, Hlc(2_000, 5, "dev_a")),
        (Hlc(500, 4, "dev_b"), 800, Hlc(1_000, 4, "dev_a")),
        (Hlc(500, 4, "dev_b"), 3_000, Hlc(3_000, 0, "dev_a")),
    ]
    for remote, now_ms, expected in cases:
        received = hlc_receive(local, remote, now_ms)
        assert received == expected
        assert received.format() > local.format()
        assert (received.physical_ms, received.counter) > (remote.physical_ms, remote.counter)


def test_hlc_string_order_equals_tuple_order_with_device_tiebreak() -> None:
    generator = random.Random(7)
    clocks = [
        Hlc(generator.choice([0, 9, 10, 1_730_000_000_000]), generator.randrange(0, 1_000), f"dev_{generator.choice('abz')}")
        for _ in range(200)
    ]

    assert sorted(clocks) == sorted(clocks, key=lambda clock: clock.format())
    assert Hlc(5, 1, "dev_a").format() < Hlc(5, 1, "dev_b").format()


def test_monotonic_sequence_of_local_and_received_clocks() -> None:
    clock = Hlc.zero("dev_a")
    observed = [clock.format()]
    for step, now_ms in enumerate([5, 5, 4, 9, 9, 9]):
        clock = hlc_receive(clock, Hlc(now_ms + 1, step, "dev_b"), now_ms) if step % 2 else hlc_tick(clock, now_ms)
        observed.append(clock.format())

    assert observed == sorted(observed)
    assert len(set(observed)) == len(observed)


def test_fields_to_apply_keeps_only_strictly_newer_fields() -> None:
    op = SyncOperation(
        op_id="op-1",
        hlc="0001730000000005-000000-dev_b",
        device_id="dev_b",
        entity=SyncEntity.ASSET,
        entity_id="asset_1",
        kind=SyncOpKind.UPSERT,
        fields={"filename": "b.jpg", "favorite": True, "folder_id": None},
    )
    clocks = {
        "filename": "0001730000000004-000009-dev_z",
        "favorite": "0001730000000005-000000-dev_b",
        "folder_id": "0001730000000006-000000-dev_a",
    }

    assert fields_to_apply(op, clocks) == {"filename": "b.jpg"}
    assert fields_to_apply(op, {}) == op.fields


def test_sync_operation_validation() -> None:
    def make(**overrides: object) -> SyncOperation:
        values: dict[str, object] = {
            "op_id": "op-1",
            "hlc": HLC_A,
            "device_id": "dev_aa",
            "entity": SyncEntity.FOLDER,
            "entity_id": "folder_1",
            "kind": SyncOpKind.UPSERT,
            "fields": {"name": "Viajes"},
        }
        values.update(overrides)
        return SyncOperation(**values)  # type: ignore[arg-type]

    assert make().fields == {"name": "Viajes"}
    with pytest.raises(ValidationFailedError):
        make(hlc="not-an-hlc")
    with pytest.raises(ValidationFailedError):
        make(entity_id="  ")
    with pytest.raises(ValidationFailedError) as unsynced:
        make(fields={"name": "x", "processing_state": "indexed"})
    assert unsynced.value.details == {"fields": ["processing_state"]}
    with pytest.raises(ValidationFailedError):
        make(kind=SyncOpKind.PURGE)
    assert make(kind=SyncOpKind.PURGE, fields={}).kind == SyncOpKind.PURGE
    with pytest.raises(ValidationFailedError):
        SyncOperation.from_dict({"op": "x", "hlc": HLC_A, "device": "dev_aa", "entity": "nope", "id": "1", "kind": "upsert"})


def test_sync_batch_round_trips_through_json() -> None:
    op = SyncOperation(
        op_id="op-1",
        hlc=HLC_A,
        device_id="dev_aa",
        entity=SyncEntity.BLOB,
        entity_id="blob_1",
        kind=SyncOpKind.UPSERT,
        fields={"parts": [{"index": 0, "channel_id": -1001, "message_id": 7, "size_bytes": 10}], "key_epoch": 2},
    )
    batch = SyncBatch(batch_id="batch-1", device_id="dev_aa", ops=(op,))

    encoded = json.dumps(batch.to_dict())
    assert SyncBatch.from_dict(json.loads(encoded)) == batch
    with pytest.raises(ValidationFailedError):
        SyncBatch.from_dict({"bento": "sync-batch", "v": 2, "batch": "b", "device": "dev_aa", "ops": []})
    with pytest.raises(ValidationFailedError):
        SyncBatch.from_dict({"bento": "sync-batch", "v": 1, "device": "dev_aa", "ops": []})


def test_sync_message_kinds_from_filenames_and_text() -> None:
    assert SyncMessageKind.from_filename("1f0e.bsync") == SyncMessageKind.BATCH
    assert SyncMessageKind.from_filename("x.bsnap") == SyncMessageKind.SNAPSHOT
    assert SyncMessageKind.from_filename("x.bkeys") == SyncMessageKind.KEYS
    assert SyncMessageKind.from_filename("x.bpair") == SyncMessageKind.PAIRING
    assert SyncMessageKind.from_filename("photo.jpg") is None
    assert SyncMessageKind.from_text('{"bento": "vault-header", "v": 1}') == SyncMessageKind.HEADER
    assert SyncMessageKind.from_text('{"bento": "pair_request", "request_id": "r"}') == SyncMessageKind.PAIRING
    for text in ("hola", "[1, 2]", '{"type": "pair_request"}', '{"bento": 1}'):
        assert SyncMessageKind.from_text(text) is None
