"""Vault session trust rules (architecture § Header, § Devices): headers are current only at this device's epoch,
older ones never pass their recovery wrap (or unverified snapshot pointer) forward, discovery never trusts the
unauthenticated `created_at`, and a removed device locks itself out and joins again under a fresh identity."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bento.adapters.fake_telegram import FakeTelegramCloud
from bento.application.devices import DeviceService
from bento.application.sync.state import DEVICE_REMOVED
from bento.application.vault import LAYOUT_KEY
from bento.domain.errors import IntegrityError, RecoveryCodeInvalidError, VaultLockedError
from bento.domain.security import VaultKeyring
from bento.domain.vault import DEVICE_REMOVED_REASON, SnapshotPointer, VaultHeader, VaultLayout, VaultState
from bento.ports.key_store import VAULT_KEYRING
from tests.integration.telegram_vault.support import VaultDevice, make_vault_device


DIGEST = "LXEWQrcmsEQBYnyp-6wy9chTD7GQPMTbAiWHF5IaSIE"


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


def _last_group(code: str) -> str:
    return code.split("-")[-1]


def _devices(device: VaultDevice) -> DeviceService:
    return DeviceService(
        devices=device.devices,
        vault=device.vault,
        account=device.runtime.account,
        transport=device.runtime.transport,
        crypto=device.crypto,
        clock=device.clock.now,
    )


async def _host_and_guest(tmp_path: Path) -> tuple[VaultDevice, VaultDevice, str]:
    host = make_vault_device(tmp_path, tmp_path / "cloud", "desk")
    await host.sign_in()
    code = (await host.vault.create()).recovery_code
    guest = make_vault_device(tmp_path, tmp_path / "cloud", "laptop")
    await guest.sign_in()
    context = await host.vault.require()
    await guest.vault.install(context.layout, context.keyring)
    [guest_row] = await guest.devices.list()
    await host.devices.save(replace(guest_row, current=False))
    return host, guest, code


async def _pin_forged_header(
    device: VaultDevice, layout: VaultLayout, keyring: VaultKeyring, *, snapshot: SnapshotPointer | None = None
) -> str:
    """What a removed device can still do: MAC a header with the epoch it kept and pin it, with its own kit."""
    code = device.crypto.generate_recovery_code()
    header = VaultHeader(
        vault_id=layout.vault_id,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        layout=layout,
        current_epoch=keyring.current_epoch,
        recovery=device.crypto.wrap_for_recovery(keyring, code),
        snapshot=snapshot,
    )
    signed = replace(header, mac=device.crypto.header_mac(keyring, header.canonical_unsigned_bytes()))
    await device.runtime.transport.publish_header_text(layout, signed.to_json())
    return code


def test_an_older_epoch_header_is_never_current_and_never_carries_its_kit_forward(tmp_path: Path) -> None:
    async def scenario() -> None:
        host, guest, _ = await _host_and_guest(tmp_path)
        old = await guest.vault.require()
        removal = await _devices(host).remove(old.device.device_id)
        await guest.sign_in()  # its session was closed, but the account itself is still at hand
        layout = old.layout
        attacker_code = await _pin_forged_header(
            guest, layout, old.keyring, snapshot=SnapshotPointer(message_id=1, covers_through_message_id=999, created_at=host.clock.now())
        )
        host.vault.invalidate()

        assert await host.vault.read_header() is None
        status = await host.vault.status()
        assert status.recovery_kit_saved is False and status.recovery_kit_stale is True
        assert await host.vault.verify_recovery_code(attacker_code) is False
        with pytest.raises(IntegrityError) as raised:
            await host.vault.update_header(lambda header: replace(header, snapshot=None))
        assert raised.value.details["what"] == "vault_header_stale"

        # "Genera un nuevo kit": a fresh wrap may build one epoch back, without the forged snapshot pointer.
        fresh = await host.vault.rotate_recovery_code()
        header = await host.vault.read_header()
        assert header is not None and header.current_epoch == 2 and header.snapshot is None
        assert await host.vault.verify_recovery_code(fresh) is True
        assert await host.vault.verify_recovery_code(removal.recovery_code) is False
        assert (await host.vault.status()).recovery_kit_stale is False

        # Two epochs back is never a base, not even for a fresh kit.
        await _pin_forged_header(guest, layout, old.keyring)
        rotated = host.crypto.rotate_keyring((await host.vault.require()).keyring)
        await host.vault.update_keyring(rotated)
        with pytest.raises(IntegrityError) as raised:
            await host.vault.rotate_recovery_code()
        assert raised.value.details["what"] == "vault_header"

    run(scenario())


def test_the_rotating_device_keeps_the_snapshot_pointer_it_verified(tmp_path: Path) -> None:
    async def scenario() -> None:
        host, guest, _ = await _host_and_guest(tmp_path)
        pointer = SnapshotPointer(message_id=3, covers_through_message_id=2, created_at=host.clock.now(), sha256=DIGEST)
        await host.vault.update_header(lambda header: replace(header, snapshot=pointer))

        await _devices(host).remove((await guest.vault.require()).device.device_id)

        header = await host.vault.read_header()
        assert header is not None and header.current_epoch == 2 and header.snapshot == pointer

    run(scenario())


def test_published_headers_never_carry_a_snapshot_pointer_without_its_digest(tmp_path: Path) -> None:
    async def scenario() -> None:
        host, _, _ = await _host_and_guest(tmp_path)
        legacy = SnapshotPointer(message_id=3, covers_through_message_id=2, created_at=host.clock.now())

        await host.vault.update_header(lambda header: replace(header, snapshot=legacy))

        header = await host.vault.read_header()
        assert header is not None and header.snapshot is None

    run(scenario())


def test_the_rotated_kit_can_be_confirmed_on_the_removing_device(tmp_path: Path) -> None:
    async def scenario() -> None:
        host, guest, _ = await _host_and_guest(tmp_path)
        removal = await _devices(host).remove((await guest.vault.require()).device.device_id)

        status = await host.vault.confirm_recovery_kit(_last_group(removal.recovery_code))

        assert status.recovery_kit_saved is True

    run(scenario())


def test_discovery_ignores_naive_timestamps_and_unlock_opens_the_header_the_code_unwraps(tmp_path: Path) -> None:
    async def scenario() -> None:
        host = make_vault_device(tmp_path, tmp_path / "cloud", "desk")
        await host.sign_in()
        code = (await host.vault.create()).recovery_code
        genuine = (await host.vault.require()).layout

        # Anyone with the account can create a look-alike vault with a newer (unauthenticated) `created_at`.
        decoy_layout = await host.runtime.transport.create_vault("vlt_decoy")
        decoy_keyring = host.crypto.generate_keyring("vlt_decoy")
        decoy = VaultHeader(
            vault_id="vlt_decoy",
            created_at=datetime(2030, 1, 1, tzinfo=UTC),
            layout=decoy_layout,
            current_epoch=1,
            recovery=host.crypto.wrap_for_recovery(decoy_keyring, host.crypto.generate_recovery_code()),
        )
        decoy = replace(decoy, mac=host.crypto.header_mac(decoy_keyring, decoy.canonical_unsigned_bytes()))
        await host.runtime.transport.publish_header_text(decoy_layout, decoy.to_json())
        naive_layout = await host.runtime.transport.create_vault("vlt_naive")
        naive = json.loads(replace(decoy, vault_id="vlt_naive", layout=naive_layout).to_json())
        naive["created_at"] = "2031-01-01T00:00:00"
        await host.runtime.transport.publish_header_text(naive_layout, json.dumps(naive))

        observer = make_vault_device(tmp_path, tmp_path / "cloud", "observer")
        await observer.sign_in()
        locked = await observer.vault.status()
        assert locked.state == VaultState.LOCKED and locked.vault_id == "vlt_decoy" and locked.other_vaults == 1

        await observer.vault.unlock(code)

        assert (await observer.vault.require()).layout == genuine
        # A device holding keys picks the vault its keyring authenticates, whatever the timestamps say.
        await host.state.delete_value(LAYOUT_KEY)
        host.vault.invalidate()
        assert (await host.vault.status()).vault_id == genuine.vault_id
        with pytest.raises(RecoveryCodeInvalidError):
            await observer.vault.unlock(host.crypto.generate_recovery_code())

    run(scenario())


def test_a_removed_device_locks_itself_out_and_rejoins_with_a_fresh_identity(tmp_path: Path) -> None:
    async def scenario() -> None:
        host, guest, _ = await _host_and_guest(tmp_path)
        old = await guest.vault.require()
        await _devices(host).remove(old.device.device_id)
        await guest.sign_in()  # a session younger than 24 h cannot be closed by the other device
        # What the sync engine does when a keys message rotates the vault without this device.
        await guest.state.set_value(DEVICE_REMOVED, json.dumps({"device_id": old.device.device_id, "epoch": 2}))
        await guest.vault.forget_keys_after_removal()

        assert await guest.key_store.get(VAULT_KEYRING) is None
        status = await guest.vault.status()
        assert status.state == VaultState.LOCKED and status.reason == DEVICE_REMOVED_REASON
        assert status.vault_id == old.layout.vault_id
        assert await guest.vault.current() is None
        with pytest.raises(VaultLockedError):
            await guest.vault.require()

        # Joining again (pairing reads the identity first) uses a new id peers never saw removed.
        fresh = await guest.vault.device_identity()
        assert fresh.device_id != old.device.device_id
        assert (await guest.vault.device_identity()) == fresh
        await guest.vault.install(old.layout, (await host.vault.require()).keyring)

        assert (await guest.vault.status()).state in {VaultState.READY, VaultState.BOOTSTRAPPING}
        assert await guest.state.get_value(DEVICE_REMOVED) is None
        context = await guest.vault.require()
        assert context.device == fresh and context.keyring.current_epoch == 2
        current = [device for device in await guest.devices.list() if device.current]
        assert [device.id for device in current] == [fresh.device_id]

    run(scenario())


def test_recovery_unlock_of_a_removed_device_installs_a_fresh_identity(tmp_path: Path) -> None:
    async def scenario() -> None:
        host, guest, code = await _host_and_guest(tmp_path)
        old = await guest.vault.require()
        [own] = [device for device in await guest.devices.list() if device.current]
        # The removal op reached the guest; the person then opens the vault with the kit.
        await guest.devices.save(replace(own, removed_at=guest.clock.now() - timedelta(minutes=1)))
        await guest.key_store.delete(VAULT_KEYRING)
        guest.vault.invalidate()

        await guest.vault.unlock(code)

        context = await guest.vault.require()
        assert context.device.device_id != old.device.device_id
        registered = {device.id: device for device in await guest.devices.list(include_removed=True)}
        assert registered[context.device.device_id].current and registered[context.device.device_id].active
        assert registered[old.device.device_id].removed_at is not None

    run(scenario())


def test_an_edited_pinned_header_is_not_a_header_at_all(tmp_path: Path) -> None:
    """Bento never edits the header; a removed device with a live session can, so an edited header is invalid."""

    async def scenario() -> None:
        host, _, code = await _host_and_guest(tmp_path)
        context = await host.vault.require()
        layout = context.layout
        cloud = FakeTelegramCloud(tmp_path / "cloud")
        assert await host.vault.read_header() is not None
        pinned = cloud.chat(layout.sync_channel_id).pinned_message_id
        text = await host.runtime.transport.read_header_text(layout)
        assert pinned is not None and text is not None

        cloud.edit_message(layout.sync_channel_id, pinned, text=text)  # even unchanged

        host.vault.invalidate()
        assert await host.vault.read_header() is None
        with pytest.raises(IntegrityError):
            await host.vault.update_header(lambda header: header)
        assert not await host.vault.verify_recovery_code(code)
        stranger = make_vault_device(tmp_path, tmp_path / "cloud", "tablet")
        await stranger.sign_in()
        assert (await stranger.vault.status()).state == VaultState.NO_VAULT

    run(scenario())
