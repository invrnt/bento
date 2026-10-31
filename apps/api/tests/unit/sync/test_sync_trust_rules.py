"""Bounded clocks and registry rules of the sync apply path (architecture § Operations, § Devices).

A peer holding the vault keys can send any op; these rules keep one op from freezing an entity forever,
from rewriting the device registry that key grants trust, or from failing this device's own writes.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories import SQLiteFolderRepository
from bento.adapters.repositories.devices import SQLiteDeviceRepository
from bento.adapters.sync import SQLiteHlcSource, SQLiteSyncApplier, install_change_capture
from bento.application.sync.snapshot import trusted_states
from bento.domain.devices import Device, DevicePlatform
from bento.domain.drive import Folder
from bento.domain.errors import ValidationFailedError
from bento.domain.sync import (
    MAX_CLOCK_SKEW_MS,
    MAX_HLC_PHYSICAL_MS,
    Hlc,
    SyncEntity,
    SyncOperation,
    SyncOpKind,
    hlc_limit_ms,
    hlc_receive,
    hlc_tick,
    hlc_within,
)
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import (
    DeviceModel,
    FolderModel,
    SyncFieldClockModel,
    SyncOutboxModel,
    SyncStateModel,
)
from bento.ports.sync import EntityState
from tests.integration.db.support import NOW, migrated_session_factory

LOCAL = "dev_local"
PEER = "dev_peer"
NOW_MS = int(NOW.timestamp() * 1000)
POISON = "9999999999999999-999999-dev_zzzz"
ISO = NOW.isoformat()
FOLDER_FIELDS = {"name": "Docs", "parent_id": None, "created_at": ISO, "deleted_at": None}


def hlc(offset_ms: int = 0, counter: int = 0, device: str = PEER) -> str:
    return f"{NOW_MS + offset_ms:016d}-{counter:06d}-{device}"


def op(entity: SyncEntity, entity_id: str, at: str, fields: dict[str, Any] | None = None, *, purge: bool = False) -> SyncOperation:
    return SyncOperation(
        op_id=f"op-{entity_id}-{at}",
        hlc=at,
        device_id=at.rsplit("-", 1)[-1],
        entity=entity,
        entity_id=entity_id,
        kind=SyncOpKind.PURGE if purge else SyncOpKind.UPSERT,
        fields={} if purge else dict(fields or {}),
    )


@pytest.fixture
def factory(tmp_path: Path) -> sessionmaker[Session]:
    session_factory = migrated_session_factory(tmp_path, session_hooks=False)
    install_change_capture(session_factory, now_ms=lambda: NOW_MS, now=lambda: NOW)
    with session_scope(session_factory) as session:
        session.add(SyncStateModel(key="capture", value=json.dumps({"vault_id": "vlt_t", "device_id": LOCAL}), updated_at=NOW))
    return session_factory


def apply(factory: sessionmaker[Session], *operations: SyncOperation, sender: str = PEER) -> int:
    applier = SQLiteSyncApplier(factory, now_ms=lambda: NOW_MS, now=lambda: NOW)
    return asyncio.run(applier.apply_batch(f"batch-{operations[0].op_id}", 1, operations, sender=sender))


def clock_of(factory: sessionmaker[Session], entity: SyncEntity, entity_id: str, field: str) -> str | None:
    with session_scope(factory) as session:
        row = session.get(SyncFieldClockModel, (entity.value, entity_id, field))
        return row.hlc if row is not None else None


def poison_clock(factory: sessionmaker[Session], entity: SyncEntity, entity_id: str, field: str) -> None:
    """A clock stored before remote clocks were bounded."""
    with session_scope(factory) as session:
        row = session.get(SyncFieldClockModel, (entity.value, entity_id, field))
        assert row is not None
        row.hlc = POISON


# Domain


def test_hlc_saturates_instead_of_overflowing_the_wire_format() -> None:
    top = Hlc(MAX_HLC_PHYSICAL_MS, 999_999, "dev_a")
    for value in (hlc_tick(top, 0), hlc_receive(top, top, 0), hlc_tick(Hlc(0, 0, "dev_a"), MAX_HLC_PHYSICAL_MS + 5)):
        assert Hlc.parse(value.format()) == value and len(value.format().split("-")[0]) == 16
    assert hlc_tick(Hlc(MAX_HLC_PHYSICAL_MS - 1, 999_999, "dev_a"), 0) == Hlc(MAX_HLC_PHYSICAL_MS, 0, "dev_a")
    with pytest.raises(ValidationFailedError):
        Hlc(MAX_HLC_PHYSICAL_MS + 1, 0, "dev_a")


def test_remote_clock_limit_is_the_earliest_reference_plus_skew() -> None:
    assert hlc_limit_ms(10_000, 2_000) == 2_000 + MAX_CLOCK_SKEW_MS
    assert hlc_limit_ms(1_000, 2_000, None) == 1_000 + MAX_CLOCK_SKEW_MS
    limit = hlc_limit_ms(NOW_MS)
    assert hlc_within(hlc(MAX_CLOCK_SKEW_MS), limit)
    assert not hlc_within(hlc(MAX_CLOCK_SKEW_MS + 1), limit)
    for malformed in (POISON[:-1] + "!", "0001-000000-dev_a", "", "zzzz"):
        assert not hlc_within(malformed, MAX_HLC_PHYSICAL_MS)


def test_snapshot_states_lose_fields_whose_clocks_run_ahead() -> None:
    states = (
        EntityState(SyncEntity.FOLDER, "folder_1", dict(FOLDER_FIELDS), {name: hlc() for name in FOLDER_FIELDS}),
        EntityState(SyncEntity.FOLDER, "folder_2", dict(FOLDER_FIELDS), {"name": POISON, "created_at": "zzzz"}),
    )
    purged = (("asset", "asset_ok", hlc()), ("asset", "asset_poison", POISON))

    kept, kept_purged, dropped = trusted_states(states, purged, limit_ms=hlc_limit_ms(NOW_MS))

    assert kept[0] == states[0]
    assert set(kept[1].fields) == {"parent_id", "deleted_at"} and kept[1].clocks == {}
    assert kept_purged == (("asset", "asset_ok", hlc()),) and dropped == 3


# Apply


def test_ops_ahead_of_the_local_clock_are_skipped_without_moving_any_clock(factory: sessionmaker[Session]) -> None:
    apply(factory, op(SyncEntity.FOLDER, "folder_1", hlc(), FOLDER_FIELDS))
    assert apply(factory, op(SyncEntity.FOLDER, "folder_1", POISON, {"name": "Congelada"})) == 0
    assert apply(factory, op(SyncEntity.FOLDER, "folder_1", hlc(10), {"name": "Papeles"})) == 1
    with session_scope(factory) as session:
        assert session.get(FolderModel, "folder_1").name == "Papeles"  # type: ignore[union-attr]
        last = session.get(SyncStateModel, "last_hlc")
    assert last is not None and last.value < hlc(MAX_CLOCK_SKEW_MS)


def test_a_poisoned_stored_clock_is_repaired_by_the_next_genuine_op(factory: sessionmaker[Session]) -> None:
    apply(factory, op(SyncEntity.FOLDER, "folder_1", hlc(), FOLDER_FIELDS))
    poison_clock(factory, SyncEntity.FOLDER, "folder_1", "name")

    assert apply(factory, op(SyncEntity.FOLDER, "folder_1", hlc(5), {"name": "Recuperada"})) == 1

    assert clock_of(factory, SyncEntity.FOLDER, "folder_1", "name") == hlc(5)
    with session_scope(factory) as session:
        assert session.get(FolderModel, "folder_1").name == "Recuperada"  # type: ignore[union-attr]


def test_local_writes_never_fail_on_a_poisoned_clock_and_repair_it(factory: sessionmaker[Session]) -> None:
    apply(factory, op(SyncEntity.FOLDER, "folder_1", hlc(), FOLDER_FIELDS))
    poison_clock(factory, SyncEntity.FOLDER, "folder_1", "name")
    with session_scope(factory) as session:
        last_hlc = session.get(SyncStateModel, "last_hlc")
        assert last_hlc is not None
        last_hlc.value = f"{10**16}-000000-{LOCAL}"  # 17 digits: what overflowing `_bump` used to store

    folders = SQLiteFolderRepository(factory)
    folder = asyncio.run(folders.get("folder_1"))
    assert isinstance(folder, Folder)
    asyncio.run(folders.save(folder.rename("Local", NOW + timedelta(seconds=1))))

    with session_scope(factory) as session:
        [outbox] = list(session.scalars(select(SyncOutboxModel)))
        last = session.get(SyncStateModel, "last_hlc")
    assert Hlc.parse(outbox.hlc).physical_ms == NOW_MS and outbox.hlc.endswith(LOCAL)
    assert clock_of(factory, SyncEntity.FOLDER, "folder_1", "name") == outbox.hlc
    assert last is not None and last.value == outbox.hlc
    assert asyncio.run(SQLiteHlcSource(factory, now_ms=lambda: NOW_MS, now=lambda: NOW).next()) > outbox.hlc


def test_snapshot_states_with_untrusted_clocks_are_not_applied(factory: sessionmaker[Session]) -> None:
    async def states() -> AsyncIterator[EntityState]:
        yield EntityState(SyncEntity.FOLDER, "folder_1", dict(FOLDER_FIELDS), {"name": POISON, "created_at": hlc()})

    applier = SQLiteSyncApplier(factory, now_ms=lambda: NOW_MS, now=lambda: NOW)
    asyncio.run(applier.apply_snapshot(states(), (("folder", "folder_9", POISON),)))

    assert clock_of(factory, SyncEntity.FOLDER, "folder_1", "name") is None
    assert clock_of(factory, SyncEntity.FOLDER, "folder_1", "created_at") == hlc()
    assert apply(factory, op(SyncEntity.FOLDER, "folder_9", hlc(1), FOLDER_FIELDS)) > 0  # no tombstone was recorded


# Device registry


def device_fields(public_key: str = "a2V5", **overrides: Any) -> dict[str, Any]:
    return {"name": "Teléfono", "platform": "linux", "public_key": public_key, "telegram_auth_hash": None,
            "added_at": ISO, "removed_at": None, **overrides}


def device_row(factory: sessionmaker[Session], device_id: str) -> DeviceModel | None:
    with session_scope(factory) as session:
        return session.get(DeviceModel, device_id)


def test_device_public_keys_are_write_once(factory: sessionmaker[Session]) -> None:
    apply(factory, op(SyncEntity.DEVICE, "dev_phone", hlc(), device_fields()))
    apply(factory, op(SyncEntity.DEVICE, "dev_phone", hlc(10), {"public_key": "YXR0YWNrZXI", "name": "Renombrado"}))

    row = device_row(factory, "dev_phone")
    assert row is not None and row.public_key == "a2V5" and row.name == "Renombrado"
    assert clock_of(factory, SyncEntity.DEVICE, "dev_phone", "public_key") == hlc()


def test_this_device_row_only_takes_removed_at_from_peers(factory: sessionmaker[Session]) -> None:
    asyncio.run(
        SQLiteDeviceRepository(factory).save(
            Device(id=LOCAL, name="Mío", platform=DevicePlatform.LINUX, public_key="bWlv", added_at=NOW, current=True)
        )
    )
    apply(factory, op(SyncEntity.DEVICE, LOCAL, hlc(10), device_fields("YXR0YWNrZXI", name="Pirata", removed_at=ISO)))

    row = device_row(factory, LOCAL)
    assert row is not None and (row.name, row.public_key, row.is_current) == ("Mío", "bWlv", True)
    assert row.removed_at is not None


def test_devices_are_never_purged_or_reactivated_by_peers(factory: sessionmaker[Session]) -> None:
    apply(factory, op(SyncEntity.DEVICE, "dev_phone", hlc(), device_fields()))
    assert apply(factory, op(SyncEntity.DEVICE, "dev_phone", hlc(5), purge=True)) == 0
    assert device_row(factory, "dev_phone") is not None

    with session_scope(factory) as session:
        session.add(SyncStateModel(key="removed_device_ids", value=json.dumps(["dev_phone"]), updated_at=NOW))
    apply(factory, op(SyncEntity.DEVICE, "dev_phone", hlc(6), {"removed_at": ISO}))
    apply(factory, op(SyncEntity.DEVICE, "dev_phone", hlc(7, device="dev_phone"), {"removed_at": None}), sender="dev_phone")

    row = device_row(factory, "dev_phone")
    assert row is not None and row.removed_at is not None


def test_devices_first_seen_through_sync_need_review_unless_they_predate_this_device(factory: sessionmaker[Session]) -> None:
    apply(factory, op(SyncEntity.DEVICE, "dev_new", hlc(), device_fields()), sender="dev_peer")

    new = asyncio.run(SQLiteDeviceRepository(factory).get("dev_new"))
    assert new is not None and new.introduced_by == "dev_peer" and new.first_seen_at == NOW
    assert new.reviewed_at is None and new.needs_review

    async def states() -> AsyncIterator[EntityState]:
        yield EntityState(SyncEntity.DEVICE, "dev_old", device_fields(), {name: hlc() for name in device_fields()})

    applier = SQLiteSyncApplier(factory, now_ms=lambda: NOW_MS, now=lambda: NOW)
    asyncio.run(applier.apply_snapshot(states(), (), source="dev_peer"))
    old = asyncio.run(SQLiteDeviceRepository(factory).get("dev_old"))
    assert old is not None and old.introduced_by == "dev_peer" and not old.needs_review

    with session_scope(factory) as session:
        session.add(SyncStateModel(key="bootstrap", value='{"done":0,"total":0}', updated_at=NOW))
    apply(factory, op(SyncEntity.DEVICE, "dev_during_bootstrap", hlc(1), device_fields()))
    during = asyncio.run(SQLiteDeviceRepository(factory).get("dev_during_bootstrap"))
    assert during is not None and not during.needs_review
