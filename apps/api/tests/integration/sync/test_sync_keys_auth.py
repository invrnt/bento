"""Sender-authenticated `.bkeys` grants between three devices of one account on the fake cloud.

The phone is removed while its Telegram session stays alive (no session matches its device model, like
"session too new"), so it can still post to the Sync channel with the old keys and every public key.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest
from sqlalchemy import text

from bento.application.drive import CreateFolderCommand
from bento.application.sync.codec import b64url_decode, b64url_encode
from bento.application.sync.keys import build_keys_message, parse_keys_message
from bento.domain.security import DeviceIdentity, VaultKeyring
from bento.domain.sync import SyncEntity, SyncMessageKind
from bento.domain.vault import canonical_json
from bento.infrastructure.db.engine import session_scope
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


@pytest.fixture
def trio(tmp_path: Path) -> Trio:
    clock = SyncClock()
    cloud = tmp_path / "cloud"
    laptop, desktop, phone = (make_cloud_device(tmp_path, cloud, name, clock) for name in ("laptop", "desktop", "phone"))

    async def setup() -> None:
        await create_vault(laptop)
        await laptop.register()
        for device in (desktop, phone):
            await join_vault(device, laptop)
            await device.register()
        for _ in range(2):
            for device in (laptop, desktop, phone):
                await device.sync()
        for device in (laptop, desktop, phone):
            assert {item.id for item in await device.devices.list()} == {laptop.device_id, desktop.device_id, phone.device_id}

    asyncio.run(setup())
    return laptop, desktop, phone


async def post_keys(
    poster: SyncDevice,
    sender: DeviceIdentity,
    keyring: VaultKeyring,
    recipients: Iterable[SyncDevice],
    *,
    removed: Iterable[str] = (),
) -> bytes:
    """Any device signed in to the account can post to the Sync channel."""
    payload = build_keys_message(
        CRYPTO, sender, keyring, {item.device_id: item.vault.identity.public_key for item in recipients}, removed_device_ids=removed
    )
    await post_raw(poster, payload)
    return payload


async def post_raw(poster: SyncDevice, payload: bytes) -> None:
    context = await poster.context()
    await poster.runtime.transport.post_sync_document(context.layout, SyncMessageKind.KEYS, payload)


def forged_keyring(known: VaultKeyring, epoch: int) -> VaultKeyring:
    """Agrees with every key the attacker knows, adds one it chose: the merge rules alone would accept it."""
    return VaultKeyring(vault_id=known.vault_id, current_epoch=epoch, keys={**known.keys, epoch: b"\x66" * 32})


def epochs(device: SyncDevice) -> tuple[int, set[int]]:
    assert device.vault.keyring is not None
    return device.vault.keyring.current_epoch, set(device.vault.keyring.keys)


async def remembered_removals(device: SyncDevice) -> list[str]:
    raw = await device.adapters.state.get_value("removed_device_ids")
    return json.loads(raw) if raw is not None else []


async def device_ops(device: SyncDevice, device_id: str) -> list[Mapping[str, object]]:
    return [
        entry.operation.fields
        for entry in await device.adapters.outbox.page()
        if entry.operation.entity == SyncEntity.DEVICE and entry.operation.entity_id == device_id
    ]


def assert_box_opens(raw: bytes, recipient: SyncDevice, expected: VaultKeyring) -> None:
    """The forged sealed box itself is valid: only the sender authentication can stop it."""
    message = parse_keys_message(raw)
    sealed = b64url_decode(message.grants[recipient.device_id].sealed)
    opened = CRYPTO.open_sealed(recipient.vault.identity, sealed, aad=message.vault_id.encode())
    assert CRYPTO.keyring_from_bytes(opened) == expected


def test_removal_rotation_reaches_the_remaining_devices_end_to_end(trio: Trio) -> None:
    laptop, desktop, phone = trio

    async def scenario() -> None:
        removal = await laptop.device_service.remove(phone.device_id)
        assert removal.telegram_session_closed is False
        assert (await phone.runtime.account.status()).authorized

        # The keys message reaches the desktop before the laptop flushes its removal op.
        await desktop.pull()
        assert epochs(desktop) == (2, {1, 2})
        phone_row = await desktop.devices.get(phone.device_id)
        assert phone_row is not None and phone_row.removed_at is not None
        assert await remembered_removals(desktop) == [phone.device_id]
        assert len(await device_ops(desktop, phone.device_id)) == 1

        # The laptop applies its own message: already removed locally, so no duplicate op.
        assert len(await device_ops(laptop, phone.device_id)) == 1
        await laptop.pull()
        assert len(await device_ops(laptop, phone.device_id)) == 1
        assert await remembered_removals(laptop) == [phone.device_id]

        from_laptop = await laptop.drive.create_folder(CreateFolderCommand(name="Después de quitar el teléfono"))
        from_desktop = await desktop.drive.create_folder(CreateFolderCommand(name="Escritorio en época 2"))
        for _ in range(2):
            for device in (laptop, desktop):
                await device.push()
            for device in (laptop, desktop):
                await device.pull()
        assert synced_state(laptop.factory) == synced_state(desktop.factory)
        assert {from_laptop.id, from_desktop.id} <= set(synced_state(desktop.factory)["folders"])

        # The phone sees a rotation without a grant for it: it stops syncing and forgets the vault keys.
        await phone.pull()
        assert phone.vault.keyring is None
        flag = json.loads(await phone.adapters.state.get_value("device_removed") or "{}")
        assert flag["device_id"] == phone.device_id and flag["epoch"] == 2 and flag["by"] == laptop.device_id
        assert not {from_laptop.id, from_desktop.id} & set(synced_state(phone.factory)["folders"])

    asyncio.run(scenario())


def test_forged_grant_from_the_removed_device_is_rejected(trio: Trio) -> None:
    laptop, desktop, phone = trio

    async def scenario() -> None:
        await laptop.device_service.remove(phone.device_id)
        await laptop.push()
        await desktop.pull()
        assert epochs(desktop) == (2, {1, 2})

        assert phone.vault.keyring is not None
        forged = forged_keyring(phone.vault.keyring, 3)
        raw = await post_keys(phone, phone.vault.identity, forged, [desktop, laptop], removed=[])
        assert_box_opens(raw, desktop, forged)
        await desktop.pull()
        await laptop.pull()
        assert epochs(desktop) == epochs(laptop) == (2, {1, 2})

    asyncio.run(scenario())


def test_forged_grant_from_an_unknown_device_is_rejected(trio: Trio) -> None:
    laptop, desktop, phone = trio

    async def scenario() -> None:
        stranger = CRYPTO.generate_device_identity()
        assert desktop.vault.keyring is not None
        forged = forged_keyring(desktop.vault.keyring, 2)
        raw = await post_keys(phone, stranger, forged, [laptop, desktop], removed=[phone.device_id])
        assert_box_opens(raw, desktop, forged)
        await desktop.pull()
        await laptop.pull()
        assert epochs(desktop) == epochs(laptop) == (1, {1})
        for device in (laptop, desktop):
            row = await device.devices.get(phone.device_id)
            assert row is not None and row.removed_at is None, "an unauthenticated message removes nobody"
            assert await remembered_removals(device) == []

    asyncio.run(scenario())


def test_tampered_grants_from_an_active_device_are_rejected(trio: Trio) -> None:
    laptop, desktop, phone = trio

    async def scenario() -> None:
        context = await laptop.context()
        rotated = CRYPTO.rotate_keyring(context.keyring)
        genuine = build_keys_message(
            CRYPTO, laptop.vault.identity, rotated, {desktop.device_id: desktop.vault.identity.public_key}
        )
        data = json.loads(genuine)
        grant = data["grants"][desktop.device_id]
        forged = forged_keyring(context.keyring, 2)
        other_box = CRYPTO.seal_for_device(
            desktop.vault.identity.public_key, CRYPTO.keyring_to_bytes(forged), aad=context.layout.vault_id.encode()
        )
        auth = b64url_decode(grant["auth"])
        tampered = [
            {**data, "grants": {desktop.device_id: {**grant, "sealed": b64url_encode(other_box)}}},
            {**data, "grants": {desktop.device_id: {**grant, "auth": b64url_encode(bytes([auth[0] ^ 1]) + auth[1:])}}},
            {**data, "removed_device_ids": [phone.device_id]},
            {**data, "sender_device_id": phone.device_id},
        ]
        for item in tampered:
            await post_raw(phone, canonical_json(item))
        await desktop.pull()
        assert epochs(desktop) == (1, {1})
        row = await desktop.devices.get(phone.device_id)
        assert row is not None and row.removed_at is None

        await post_raw(laptop, genuine)
        await desktop.pull()
        assert epochs(desktop) == (2, {1, 2})
        assert desktop.vault.keyring == rotated

    asyncio.run(scenario())


def test_removal_arriving_after_the_keys_message_still_blocks_later_grants(trio: Trio) -> None:
    laptop, desktop, phone = trio

    async def scenario() -> None:
        assert phone.vault.keyring is not None
        old = phone.vault.keyring
        await laptop.device_service.remove(phone.device_id)  # removal op stays in the laptop's outbox
        await post_keys(phone, phone.vault.identity, forged_keyring(old, 3), [desktop], removed=[laptop.device_id])
        await desktop.pull()
        assert epochs(desktop) == (2, {1, 2})

        await laptop.push()  # the removal op arrives after the keys message and the forged grant
        await desktop.pull()
        phone_row = await desktop.devices.get(phone.device_id)
        assert phone_row is not None and phone_row.removed_at is not None

        # A stale or forged-HLC op re-activates the phone's row: the remembered removal still rejects it.
        with session_scope(desktop.factory) as session:
            session.execute(text("UPDATE devices SET removed_at = NULL WHERE id = :id"), {"id": phone.device_id})
        reactivated = await desktop.devices.get(phone.device_id)
        assert reactivated is not None and reactivated.active
        await post_keys(phone, phone.vault.identity, forged_keyring(old, 4), [desktop], removed=[laptop.device_id])
        await desktop.pull()
        assert epochs(desktop) == (2, {1, 2})
        assert await remembered_removals(desktop) == [phone.device_id]
        laptop_row = await desktop.devices.get(laptop.device_id)
        assert laptop_row is not None and laptop_row.active

    asyncio.run(scenario())


def test_v1_keys_messages_are_rejected(trio: Trio) -> None:
    laptop, desktop, _ = trio

    async def scenario() -> None:
        context = await laptop.context()
        rotated = CRYPTO.rotate_keyring(context.keyring)
        sealed = CRYPTO.seal_for_device(
            desktop.vault.identity.public_key, CRYPTO.keyring_to_bytes(rotated), aad=context.layout.vault_id.encode()
        )
        v1 = {"bento": "keys", "v": 1, "vault_id": context.layout.vault_id, "epoch": 2,
              "grants": {desktop.device_id: b64url_encode(sealed)}}
        await post_raw(laptop, canonical_json(v1))
        await desktop.pull()
        assert epochs(desktop) == (1, {1})

    asyncio.run(scenario())
