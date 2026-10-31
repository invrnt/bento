"""Sender-authenticated keys grants (architecture § Keys messages) with in-memory doubles."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest

from bento.adapters.security import VaultCrypto
from bento.application.pairing import b64url_encode
from bento.application.sync.keys import (
    KeysGrant,
    KeysGrantApplier,
    KeysMessage,
    build_keys_message,
    grant_auth_payload,
    parse_keys_message,
)
from bento.application.sync.state import REMOVED_DEVICES, SyncStateValues
from bento.domain.account import TelegramAccount
from bento.domain.devices import Device, DevicePlatform
from bento.domain.errors import IntegrityError
from bento.domain.security import DeviceIdentity, VaultKeyring
from bento.domain.vault import VaultLayout
from bento.ports.vault import VaultContext
from tests.unit.pairing.pairing_doubles import MemoryDevices

CRYPTO = VaultCrypto()
LAYOUT = VaultLayout(vault_id="vlt_keys", files_channel_id=-1001, sync_channel_id=-1002, inbox_channel_id=-1003)
ACCOUNT = TelegramAccount(user_id=1, display_name="Ana")
NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)
KEYRING = CRYPTO.generate_keyring(LAYOUT.vault_id)


class MemoryState:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get_value(self, key: str) -> str | None:
        return self.values.get(key)

    async def set_value(self, key: str, value: str) -> None:
        self.values[key] = value

    async def delete_value(self, key: str) -> None:
        self.values.pop(key, None)

    async def is_batch_applied(self, batch_id: str) -> bool:
        return False


class CountingDevices(MemoryDevices):
    def __init__(self) -> None:
        super().__init__()
        self.saves: list[Device] = []

    async def save(self, device: Device) -> None:
        self.saves.append(device)
        await super().save(device)


class Clock:
    def now(self) -> datetime:
        return NOW


@dataclass
class World:
    applier: KeysGrantApplier
    devices: CountingDevices
    state: MemoryState
    me: DeviceIdentity
    laptop: DeviceIdentity
    phone: DeviceIdentity

    def context(self, keyring: VaultKeyring = KEYRING) -> VaultContext:
        return VaultContext(layout=LAYOUT, keyring=keyring, device=self.me, account=ACCOUNT)

    async def register(self, identity: DeviceIdentity, *, removed_at: datetime | None = None, current: bool = False) -> None:
        await self.devices.save(
            Device(id=identity.device_id, name="Equipo", platform=DevicePlatform.LINUX,
                   public_key=b64url_encode(identity.public_key), added_at=NOW, removed_at=removed_at, current=current)
        )

    def removed(self) -> list[str]:
        return json.loads(self.state.values.get(REMOVED_DEVICES, "[]"))


def world() -> World:
    me, laptop, phone = (CRYPTO.generate_device_identity() for _ in range(3))
    devices, state = CountingDevices(), MemoryState()
    result = World(
        applier=KeysGrantApplier(crypto=CRYPTO, devices=devices, values=SyncStateValues(state), clock=Clock()),
        devices=devices, state=state, me=me, laptop=laptop, phone=phone,
    )

    async def setup() -> None:
        await result.register(me, current=True)
        await result.register(laptop)
        await result.register(phone)
        devices.saves.clear()

    asyncio.run(setup())
    return result


def grant(
    sender: DeviceIdentity, keyring: VaultKeyring, *recipients: DeviceIdentity, removed: tuple[str, ...] = ()
) -> KeysMessage:
    raw = build_keys_message(
        CRYPTO, sender, keyring, {item.device_id: item.public_key for item in recipients}, removed_device_ids=removed
    )
    return parse_keys_message(raw)


def attacker_keyring() -> VaultKeyring:
    """Keeps the epoch-1 key (a removed device knows it) and adds an attacker-chosen epoch 2."""
    return VaultKeyring(vault_id=LAYOUT.vault_id, current_epoch=2, keys={1: KEYRING.keys[1], 2: b"x" * 32})


def rejected(world: World, message: KeysMessage, what: str, keyring: VaultKeyring = KEYRING) -> None:
    with pytest.raises(IntegrityError) as caught:
        asyncio.run(world.applier.apply(message, world.context(keyring)))
    assert caught.value.details == {"what": what}


def test_grant_from_an_active_device_applies_and_records_its_removals() -> None:
    w = world()
    rotated = CRYPTO.rotate_keyring(KEYRING)
    message = grant(w.laptop, rotated, w.me, w.laptop, removed=(w.phone.device_id,))

    merged = asyncio.run(w.applier.apply(message, w.context()))

    assert merged == rotated
    assert w.removed() == [w.phone.device_id]
    assert [(item.id, item.removed_at) for item in w.devices.saves] == [(w.phone.device_id, NOW)]
    # Replays bring nothing new and emit no duplicate removal.
    assert asyncio.run(w.applier.apply(message, w.context(rotated))) is None
    assert len(w.devices.saves) == 1 and w.removed() == [w.phone.device_id]


def test_removal_already_known_locally_is_not_saved_again() -> None:
    w = world()
    asyncio.run(w.register(w.phone, removed_at=datetime(2026, 10, 30, tzinfo=UTC)))
    w.devices.saves.clear()
    asyncio.run(w.applier.apply(grant(w.laptop, CRYPTO.rotate_keyring(KEYRING), w.me, removed=(w.phone.device_id,)), w.context()))
    assert w.devices.saves == []
    assert w.removed() == [w.phone.device_id]
    assert w.devices.items[w.phone.device_id].removed_at == datetime(2026, 10, 30, tzinfo=UTC)


def test_grant_from_an_unknown_device_is_rejected() -> None:
    w = world()
    stranger = CRYPTO.generate_device_identity()
    rejected(w, grant(stranger, attacker_keyring(), w.me, removed=(w.laptop.device_id,)), "keys_sender_unknown")
    assert w.devices.saves == [] and REMOVED_DEVICES not in w.state.values


def test_grant_from_a_device_removed_in_the_registry_is_rejected() -> None:
    w = world()
    asyncio.run(w.register(w.phone, removed_at=NOW))
    rejected(w, grant(w.phone, attacker_keyring(), w.me), "keys_sender_removed")


def test_device_removed_by_an_applied_message_stays_rejected_when_its_row_is_reactivated() -> None:
    w = world()
    rotated = CRYPTO.rotate_keyring(KEYRING)
    asyncio.run(w.applier.apply(grant(w.laptop, rotated, w.me, removed=(w.phone.device_id,)), w.context()))
    # A stale or forged-HLC `device` op could bring the row back; the remembered removal still wins.
    asyncio.run(w.register(w.phone))
    forged = VaultKeyring(vault_id=LAYOUT.vault_id, current_epoch=3, keys={1: KEYRING.keys[1], 3: b"x" * 32})
    rejected(w, grant(w.phone, forged, w.me, removed=(w.laptop.device_id,)), "keys_sender_removed", rotated)
    assert w.removed() == [w.phone.device_id]
    assert w.devices.items[w.laptop.device_id].removed_at is None


def test_tampered_grants_are_rejected_before_anything_is_recorded() -> None:
    w = world()
    rotated = CRYPTO.rotate_keyring(KEYRING)
    message = grant(w.laptop, rotated, w.me, w.laptop, removed=(w.phone.device_id,))
    mine = message.grants[w.me.device_id]
    other_box = grant(w.laptop, attacker_keyring(), w.me).grants[w.me.device_id].sealed
    flipped = mine.auth[:-2] + ("A" if mine.auth[-2] != "A" else "B") + mine.auth[-1]

    tampered = [
        replace(message, grants={**message.grants, w.me.device_id: replace(mine, auth=flipped)}),
        replace(message, grants={**message.grants, w.me.device_id: replace(mine, sealed=other_box)}),
        replace(message, grants={**message.grants, w.me.device_id: message.grants[w.laptop.device_id]}),
        replace(message, removed_device_ids=(w.phone.device_id, "dev_victim")),
        replace(message, removed_device_ids=()),
        replace(message, sender_device_id=w.phone.device_id),
    ]
    for item in tampered:
        rejected(w, item, "keys_grant_auth")
    # Epochs move one step at a time: a skipped epoch is refused before any tag is checked.
    rejected(w, replace(message, epoch=3), "keys_epoch_gap")
    assert w.devices.saves == [] and REMOVED_DEVICES not in w.state.values
    assert asyncio.run(w.applier.apply(message, w.context())) == rotated


def test_authentic_grant_that_conflicts_with_held_keys_is_still_rejected() -> None:
    w = world()
    conflicting = VaultKeyring(vault_id=LAYOUT.vault_id, current_epoch=2, keys={1: b"z" * 32, 2: b"y" * 32})
    rejected(w, grant(w.laptop, conflicting, w.me, removed=(w.phone.device_id,)), "keys_grant")
    assert w.devices.saves == [] and REMOVED_DEVICES not in w.state.values


def test_own_messages_are_checked_against_this_device_identity() -> None:
    w = world()
    w.devices.items.pop(w.me.device_id)
    rotated = CRYPTO.rotate_keyring(KEYRING)
    assert asyncio.run(w.applier.apply(grant(w.me, rotated, w.me, removed=(w.phone.device_id,)), w.context())) == rotated
    impostor = grant(w.laptop, attacker_keyring(), w.me)
    rejected(w, replace(impostor, sender_device_id=w.me.device_id), "keys_grant_auth")


def test_messages_without_a_grant_here_or_for_another_vault_change_nothing() -> None:
    w = world()
    rotated = CRYPTO.rotate_keyring(KEYRING)
    assert asyncio.run(w.applier.apply(grant(w.laptop, rotated, w.laptop, removed=(w.phone.device_id,)), w.context())) is None
    other_vault = replace(grant(w.laptop, rotated, w.me), vault_id="vlt_other")
    assert asyncio.run(w.applier.apply(other_vault, w.context())) is None
    assert w.devices.saves == [] and REMOVED_DEVICES not in w.state.values


def test_unreadable_sealed_box_with_a_valid_tag_is_rejected() -> None:
    w = world()
    message = grant(w.laptop, CRYPTO.rotate_keyring(KEYRING), w.me)
    sealed = "not-base64!"
    auth = CRYPTO.grant_auth(w.laptop, w.me.public_key, grant_auth_payload(message, recipient_device_id=w.me.device_id, sealed=sealed))
    rejected(w, replace(message, grants={w.me.device_id: KeysGrant(sealed=sealed, auth=auth)}), "keys_grant")


def test_stale_epochs_are_rejected_and_the_current_one_brings_nothing_new() -> None:
    w = world()
    rotated = CRYPTO.rotate_keyring(KEYRING)
    assert asyncio.run(w.applier.apply(grant(w.laptop, rotated, w.me), w.context(rotated))) is None
    rejected(w, grant(w.laptop, KEYRING, w.me), "keys_epoch_stale", rotated)


def test_a_rotation_without_this_device_from_an_active_peer_means_it_was_removed() -> None:
    w = world()
    rotated = CRYPTO.rotate_keyring(KEYRING)
    stranger = CRYPTO.generate_device_identity()

    def removes(message: KeysMessage, keyring: VaultKeyring = KEYRING) -> bool:
        return asyncio.run(w.applier.removes_this_device(message, w.context(keyring)))

    assert removes(grant(w.laptop, rotated, w.laptop))
    assert removes(grant(w.laptop, rotated, w.laptop, removed=(w.me.device_id,)))
    assert not removes(grant(w.laptop, rotated, w.me, w.laptop))
    assert not removes(grant(stranger, rotated, w.laptop)), "unknown senders remove nobody"
    assert not removes(grant(w.me, rotated, w.laptop)), "never this device's own message"
    assert not removes(grant(w.laptop, rotated, w.laptop), rotated), "only a newer epoch"
    asyncio.run(w.applier.apply(grant(w.laptop, rotated, w.me, removed=(w.phone.device_id,)), w.context()))
    assert not removes(grant(w.phone, CRYPTO.rotate_keyring(rotated), w.laptop), rotated), "removed senders remove nobody"
