"""Sync under a hostile Sync channel, three devices of one account on the fake cloud.

The phone plays the attacker the threat model allows: it holds the vault keys (before its removal, or the old
epochs after it), shares the Telegram account, and can post anything to the Sync channel.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from bento.adapters.backup.activity import SQLiteActivitySource
from bento.application.drive import CreateFolderCommand, RenameFolderCommand
from bento.application.sync import SyncPolicy
from bento.application.sync.keys import build_keys_message, parse_keys_message
from bento.application.sync.status import SyncStatusService
from bento.domain.security import SealPurpose, VaultKeyring
from bento.domain.sync import SyncBatch, SyncEntity, SyncMessageKind, SyncOperation, SyncOpKind, SyncState
from tests.integration.sync.support import (
    CRYPTO,
    SyncClock,
    SyncDevice,
    create_vault,
    join_vault,
    make_cloud_device,
    synced_state,
)

Trio = tuple[SyncDevice, SyncDevice, SyncDevice]
POISON = "9999999999999999-999999-dev_zzzz"


def make_trio(tmp_path: Path, clock: SyncClock, policy: SyncPolicy | None = None) -> Trio:
    cloud = tmp_path / "cloud"
    laptop, desktop, phone = (
        make_cloud_device(tmp_path, cloud, name, clock, policy=policy) for name in ("laptop", "desktop", "phone")
    )

    async def setup() -> None:
        await create_vault(laptop)
        await laptop.register()
        for device in (desktop, phone):
            await join_vault(device, laptop)
            await device.register()
        for _ in range(2):
            for device in (laptop, desktop, phone):
                await device.sync()

    asyncio.run(setup())
    return laptop, desktop, phone


@pytest.fixture
def trio(tmp_path: Path) -> Trio:
    return make_trio(tmp_path, SyncClock())


def raw_op(entity: SyncEntity, entity_id: str, hlc: str, fields: dict[str, Any], *, device: str) -> SyncOperation:
    return SyncOperation(
        op_id=str(uuid.uuid4()), hlc=hlc, device_id=device, entity=entity, entity_id=entity_id, kind=SyncOpKind.UPSERT, fields=fields
    )


async def post_batch(poster: SyncDevice, keyring: VaultKeyring, *operations: SyncOperation) -> int:
    """Seal and post a batch as the phone would, bypassing its outbox."""
    context = await poster.context() if poster.vault.keyring is not None else None
    layout = context.layout if context is not None else poster.vault.layout
    assert layout is not None
    batch = SyncBatch(batch_id=str(uuid.uuid4()), device_id=poster.device_id, ops=operations)
    envelope = CRYPTO.seal_json(keyring, SealPurpose.SYNC, batch.to_dict(), aad=layout.vault_id.encode())
    ref = await poster.runtime.transport.post_sync_document(layout, SyncMessageKind.BATCH, envelope)
    return ref.message_id


async def state_json(device: SyncDevice, key: str) -> Any:
    raw = await device.adapters.state.get_value(key)
    return json.loads(raw) if raw is not None else None


async def state_int(device: SyncDevice, key: str) -> int:
    return int(await device.adapters.state.get_value(key) or 0)


def folder_names(device: SyncDevice) -> dict[str, str]:
    return {folder_id: values[0] for folder_id, values in synced_state(device.factory)["folders"].items()}


def test_a_far_future_clock_cannot_freeze_folders_or_the_device_registry(trio: Trio) -> None:
    laptop, desktop, phone = trio

    async def scenario() -> None:
        folder = await laptop.drive.create_folder(CreateFolderCommand(name="Documentos"))
        await laptop.push()
        for device in (desktop, phone):
            await device.pull()
        assert phone.vault.keyring is not None
        keyring = phone.vault.keyring

        # One poisoned op used to win every later LWW comparison on every device (and overflow local HLCs).
        await post_batch(
            phone,
            keyring,
            raw_op(SyncEntity.FOLDER, folder.id, POISON, {"name": "Congelada"}, device="dev_zzzz"),
            raw_op(SyncEntity.DEVICE, phone.device_id, POISON, {"removed_at": None, "name": "Inamovible"}, device="dev_zzzz"),
        )
        for device in (laptop, desktop):
            await device.pull()
            assert folder_names(device)[folder.id] == "Documentos"
            assert await state_int(device, "skipped_ops") == 2

        laptop.clock.advance()
        await laptop.drive.rename_folder(RenameFolderCommand(folder_id=folder.id, name="Papeles"))
        removal = await laptop.device_service.remove(phone.device_id)
        await laptop.push()
        await desktop.pull()

        assert folder_names(desktop)[folder.id] == "Papeles"
        row = await desktop.devices.get(phone.device_id)
        assert row is not None and row.removed_at is not None and row.name != "Inamovible"
        assert removal.recovery_code
        assert desktop.vault.keyring is not None and desktop.vault.keyring.current_epoch == 2

    asyncio.run(scenario())


def test_ops_stamped_ahead_of_the_telegram_message_date_are_skipped(tmp_path: Path) -> None:
    # The shared device clock runs an hour ahead of the (real-time) fake cloud: every op is "from the future".
    clock = SyncClock(current=datetime.now(UTC) + timedelta(hours=1))
    cloud = tmp_path / "cloud"
    laptop, desktop = (make_cloud_device(tmp_path, cloud, name, clock) for name in ("laptop", "desktop"))

    async def scenario() -> None:
        await create_vault(laptop)
        await join_vault(desktop, laptop)
        await laptop.sync()
        await desktop.sync()
        folder = await laptop.drive.create_folder(CreateFolderCommand(name="Del futuro"))
        await laptop.push()
        await desktop.pull()

        assert folder.id not in folder_names(desktop)
        assert await state_int(desktop, "skipped_ops") >= 1
        assert int(await desktop.adapters.state.get_value("last_applied_message_id") or 0) > 0

    asyncio.run(scenario())


def test_a_key_holder_cannot_rewrite_keys_and_unknown_devices_can_be_left_out(trio: Trio) -> None:
    laptop, desktop, phone = trio

    async def scenario() -> None:
        assert phone.vault.keyring is not None
        laptop_key = (await desktop.devices.get(laptop.device_id)).public_key  # type: ignore[union-attr]
        phantom = CRYPTO.generate_device_identity()
        stamp = desktop.clock.now()
        hlc = f"{int(stamp.timestamp() * 1000):016d}-000001-{phone.device_id}"
        await post_batch(
            phone,
            phone.vault.keyring,
            raw_op(SyncEntity.DEVICE, laptop.device_id, hlc, {"public_key": "YXR0YWNrZXI"}, device=phone.device_id),
            raw_op(SyncEntity.DEVICE, desktop.device_id, hlc, {"name": "Pirata"}, device=phone.device_id),
            raw_op(
                SyncEntity.DEVICE,
                phantom.device_id,
                hlc,
                {"name": "Tablet", "platform": "linux", "public_key": phone_public_key(phone), "added_at": stamp.isoformat()},
                device=phone.device_id,
            ),
        )
        await desktop.pull()

        assert (await desktop.devices.get(laptop.device_id)).public_key == laptop_key  # type: ignore[union-attr]
        assert (await desktop.devices.get(desktop.device_id)).name == "desktop · Linux"  # type: ignore[union-attr]
        planted = await desktop.devices.get(phantom.device_id)
        assert planted is not None and planted.needs_review and planted.introduced_by == phone.device_id
        activity = await SQLiteActivitySource(desktop.factory).snapshot(now=desktop.clock.now())
        # The phone joined through the laptop, so the desktop first saw it through sync as well.
        assert {item.device_id for item in activity.new_devices} == {phantom.device_id, phone.device_id}

        service = desktop.device_service
        preview = await service.removal_preview(phone.device_id)
        assert [device.id for device in preview][0] == desktop.device_id
        assert {device.id for device in preview} == {desktop.device_id, laptop.device_id, phantom.device_id}

        removal = await service.remove(phone.device_id, exclude_device_ids=[phantom.device_id])

        assert [device.id for device in removal.excluded] == [phantom.device_id]
        keys = [ref for ref in await list_sync(desktop) if ref.kind == SyncMessageKind.KEYS][-1]
        message = parse_keys_message(await desktop.runtime.transport.download_sync_document(desktop.vault.layout, keys.message_id))  # type: ignore[arg-type]
        assert set(message.grants) == {desktop.device_id, laptop.device_id}
        assert {phone.device_id, phantom.device_id} <= set(message.removed_device_ids)
        acknowledged = await service.acknowledge(phantom.device_id)
        assert acknowledged.reviewed_at is not None and not acknowledged.needs_review

        await laptop.pull()
        assert laptop.vault.keyring is not None and laptop.vault.keyring.current_epoch == 2
        for device_id in (phone.device_id, phantom.device_id):
            row = await laptop.devices.get(device_id)
            assert row is not None and row.removed_at is not None

    asyncio.run(scenario())


def phone_public_key(phone: SyncDevice) -> str:
    from bento.application.pairing import b64url_encode

    return b64url_encode(phone.vault.identity.public_key)


async def list_sync(device: SyncDevice) -> list[Any]:
    assert device.vault.layout is not None
    return list(await device.runtime.transport.list_sync_messages(device.vault.layout, after_message_id=0, limit=1000))


def test_a_removed_device_locks_itself_out_and_forged_removals_do_not(trio: Trio) -> None:
    laptop, desktop, phone = trio

    async def scenario() -> None:
        # Forged "rotations" without a grant for the desktop: from a stranger, and later from the removed phone.
        stranger = CRYPTO.generate_device_identity()
        assert desktop.vault.keyring is not None and desktop.vault.layout is not None
        layout = desktop.vault.layout
        forged = VaultKeyring(vault_id=layout.vault_id, current_epoch=2, keys={**desktop.vault.keyring.keys, 2: b"\x01" * 32})
        await phone.runtime.transport.post_sync_document(
            layout, SyncMessageKind.KEYS, build_keys_message(CRYPTO, stranger, forged, {laptop.device_id: laptop.vault.identity.public_key})
        )
        await desktop.pull()
        assert await desktop.adapters.state.get_value("device_removed") is None

        await laptop.device_service.remove(phone.device_id)
        await desktop.pull()
        assert desktop.vault.keyring is not None and desktop.vault.keyring.current_epoch == 2
        assert phone.vault.keyring is not None
        stale = VaultKeyring(vault_id=layout.vault_id, current_epoch=3, keys={**phone.vault.keyring.keys, 3: b"\x02" * 32})
        await phone.runtime.transport.post_sync_document(
            layout,
            SyncMessageKind.KEYS,
            build_keys_message(CRYPTO, phone.vault.identity, stale, {laptop.device_id: laptop.vault.identity.public_key}),
        )
        await desktop.pull()
        assert await desktop.adapters.state.get_value("device_removed") is None
        assert desktop.vault.keyring.current_epoch == 2

        cursor_before = int(await phone.adapters.state.get_value("last_applied_message_id") or 0)
        context = await phone.context()
        _, result = await phone.engine.pull(context)

        assert result.device_removed and phone.vault.keyring is None
        flag = await state_json(phone, "device_removed")
        assert flag["device_id"] == phone.device_id and flag["by"] == laptop.device_id and flag["epoch"] == 2
        # The keys message stays after the cursor: re-joining reads it again (and raises the floor then).
        cursor = int(await phone.adapters.state.get_value("last_applied_message_id") or 0)
        assert cursor_before <= cursor < flag["message_id"]
        status = await SyncStatusService(
            enabled=True, state=phone.adapters.state, outbox=phone.adapters.outbox, clock=phone.clock
        ).status()
        assert status.state == SyncState.PAUSED and status.error_code == "device_removed"
        await phone.drive.create_folder(CreateFolderCommand(name="Sin sincronizar"))
        assert await phone.engine.flush(context, force=True) == 0
        _, again = await phone.engine.pull(context)
        assert again.device_removed and again.messages == 0

    asyncio.run(scenario())


def test_bootstrap_sets_the_epoch_floor_from_the_snapshot(tmp_path: Path) -> None:
    clock = SyncClock()
    laptop, desktop, phone = make_trio(tmp_path, clock)
    tablet = make_cloud_device(tmp_path, tmp_path / "cloud", "tablet", clock)

    async def scenario() -> None:
        assert phone.vault.keyring is not None
        old_keyring = phone.vault.keyring
        await laptop.drive.create_folder(CreateFolderCommand(name="Antes"))
        await laptop.device_service.remove(phone.device_id)
        await laptop.sync()
        await desktop.sync()
        context = await laptop.context()
        assert context.keyring.current_epoch == 2
        await laptop.engine.pull(context)
        assert await laptop.engine.maybe_snapshot(context, force=True)
        header = await laptop.vault.read_header()
        assert header is not None and header.snapshot is not None

        # After the snapshot, the removed phone posts with the epoch it kept.
        evil_hlc = f"{clock.now_ms():016d}-000009-{phone.device_id}"
        await post_batch(phone, old_keyring, raw_op(SyncEntity.FOLDER, "folder_evil", evil_hlc, {"name": "evil", "created_at": clock.now().isoformat()}, device=phone.device_id))

        await join_vault(tablet, laptop)
        await tablet.sync()

        floor = await state_json(tablet, "epoch_floor")
        assert floor == {"epoch": 2, "message_id": header.snapshot.covers_through_message_id}
        names = folder_names(tablet)
        assert "folder_evil" not in names and "Antes" in names.values()
        assert (await state_json(tablet, "last_skipped"))["reason"] == "below_epoch_floor"

    asyncio.run(scenario())


class CountingCrypto:
    """Counts decryptions; delegates everything else."""

    def __init__(self) -> None:
        self.opened: list[int] = []

    def open_json(self, keyring: VaultKeyring, purpose: SealPurpose, envelope: bytes, **kwargs: Any) -> Any:
        self.opened.append(len(envelope))
        return CRYPTO.open_json(keyring, purpose, envelope, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(CRYPTO, name)


def test_oversized_bombs_and_below_floor_documents_are_skipped_cheaply_and_never_retried(tmp_path: Path) -> None:
    policy = SyncPolicy(post_interval_seconds=0, max_batch_document_bytes=4096, max_keys_document_bytes=2048, max_batch_json_bytes=8192)
    laptop, desktop, phone = make_trio(tmp_path, SyncClock(), policy=policy)

    async def scenario() -> None:
        assert phone.vault.keyring is not None and desktop.vault.layout is not None
        layout = desktop.vault.layout
        old_keyring = phone.vault.keyring
        await laptop.device_service.remove(phone.device_id)
        await desktop.pull()
        crypto = CountingCrypto()
        desktop.engine._crypto = crypto  # type: ignore[assignment]
        downloads: list[int] = []
        original = desktop.runtime.transport.download_sync_document

        async def counting(layout: Any, message_id: int, **kwargs: Any) -> bytes:
            downloads.append(message_id)
            return await original(layout, message_id, **kwargs)

        desktop.runtime.transport.download_sync_document = counting  # type: ignore[method-assign]
        stamp = desktop.clock.now_ms()
        big = await phone.runtime.transport.post_sync_document(layout, SyncMessageKind.BATCH, b"BENV" + b"\x00" * 8192)
        bomb_ops = tuple(
            raw_op(SyncEntity.FOLDER, f"folder_{index}", f"{stamp:016d}-{index:06d}-{laptop.device_id}", {"name": "x" * 900}, device=laptop.device_id)
            for index in range(12)
        )
        assert desktop.vault.keyring is not None
        bomb = await post_batch(laptop, desktop.vault.keyring, *bomb_ops)
        below = await post_batch(phone, old_keyring, raw_op(SyncEntity.FOLDER, "folder_evil", f"{stamp:016d}-000001-{phone.device_id}", {"name": "evil"}, device=phone.device_id))
        big_keys = await phone.runtime.transport.post_sync_document(layout, SyncMessageKind.KEYS, b"{" + b" " * 4096 + b"}")
        good = await laptop.drive.create_folder(CreateFolderCommand(name="Después"))
        await laptop.push()

        await desktop.pull()

        assert big.message_id not in downloads and big_keys.message_id not in downloads
        assert bomb in downloads and below in downloads
        assert len(crypto.opened) == 2  # the bomb (inflation capped) and the genuine batch; never the below-floor one
        assert good.id in folder_names(desktop) and "folder_evil" not in folder_names(desktop)
        assert not any(name.startswith("folder_") and len(name) < 12 for name in folder_names(desktop))
        assert await state_int(desktop, "skipped_messages") == 4
        cursor = int(await desktop.adapters.state.get_value("last_applied_message_id") or 0)
        assert cursor >= max(big.message_id, bomb, below, big_keys.message_id)

        downloads.clear()
        await desktop.pull()
        assert downloads == [] and await state_int(desktop, "skipped_messages") == 4

    asyncio.run(scenario())


def test_own_batches_are_tracked_until_pulled(trio: Trio) -> None:
    laptop, desktop, _ = trio

    async def scenario() -> None:
        await laptop.drive.create_folder(CreateFolderCommand(name="Propia"))
        await laptop.push()
        own = await state_json(laptop, "own_batch_message_ids")
        assert isinstance(own, list) and len(own) == 1
        await laptop.pull()
        assert await state_json(laptop, "own_batch_message_ids") == []
        await desktop.pull()
        assert "Propia" in folder_names(desktop).values()

    asyncio.run(scenario())


def test_snapshot_device_rows_need_no_review_on_a_bootstrapping_device(tmp_path: Path) -> None:
    clock = SyncClock()
    laptop, desktop, _ = make_trio(tmp_path, clock)
    tablet = make_cloud_device(tmp_path, tmp_path / "cloud", "tablet", clock)

    async def scenario() -> None:
        context = await laptop.context()
        await laptop.engine.pull(context)
        assert await laptop.engine.maybe_snapshot(context, force=True)
        await join_vault(tablet, laptop)
        await tablet.register()
        await tablet.sync()

        rows = {device.id: device for device in await tablet.devices.list()}
        assert {laptop.device_id, desktop.device_id} <= set(rows)
        assert not any(device.needs_review for device in rows.values())
        assert (await SQLiteActivitySource(tablet.factory).snapshot(now=clock.now())).new_devices == ()

    asyncio.run(scenario())
