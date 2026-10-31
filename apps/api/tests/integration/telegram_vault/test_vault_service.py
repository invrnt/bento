from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from bento.adapters.settings import SQLiteSettingsRepository
from bento.application.vault import (
    BOOTSTRAP_PENDING_KEY,
    LAYOUT_KEY,
    RecoveryGroupMismatchError,
)
from bento.domain.errors import (
    IntegrityError,
    RecoveryCodeInvalidError,
    TelegramAccountError,
    TelegramNotAvailableError,
    ValidationFailedError,
    VaultAlreadyExistsError,
    VaultLockedError,
    VaultNotFoundError,
)
from bento.domain.vault import VaultHeader, VaultState
from bento.ports.key_store import VAULT_KEYRING
from tests.integration.telegram_vault.support import VaultDevice, make_vault_device

RECOVERY_CODE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{4}(-[0-9A-HJKMNP-TV-Z]{4}){8}$")


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


async def _first_device(tmp_path: Path) -> tuple[VaultDevice, str]:
    device = make_vault_device(tmp_path, tmp_path / "cloud", "desk")
    await device.sign_in()
    created = await device.vault.create()
    return device, created.recovery_code


def test_status_reflects_local_signed_out_and_no_vault(tmp_path: Path) -> None:
    async def scenario() -> None:
        local = make_vault_device(tmp_path, tmp_path / "cloud", "local", telegram=False)
        assert (await local.vault.status()).state == VaultState.LOCAL_ONLY
        assert await local.vault.current() is None
        with pytest.raises(VaultNotFoundError):
            await local.vault.require()

        device = make_vault_device(tmp_path, tmp_path / "cloud", "desk")
        assert (await device.vault.status()).state == VaultState.SIGNED_OUT
        with pytest.raises(TelegramAccountError) as raised:
            await device.vault.require()
        assert raised.value.code == "telegram_not_authorized"
        await device.sign_in()
        assert (await device.vault.status()).state == VaultState.NO_VAULT
        with pytest.raises(VaultNotFoundError):
            await device.vault.require()

    run(scenario())


def test_missing_build_credentials_report_signed_out(tmp_path: Path) -> None:
    device = make_vault_device(tmp_path, tmp_path / "cloud", "desk")

    def unavailable() -> None:
        raise TelegramNotAvailableError()

    device.vault._telegram = unavailable  # type: ignore[assignment]

    assert run(device.vault.status()).state == VaultState.SIGNED_OUT
    assert run(device.vault.current()) is None


def test_create_builds_vault_header_device_and_one_time_recovery_code(tmp_path: Path) -> None:
    async def scenario() -> None:
        device, code = await _first_device(tmp_path)

        assert RECOVERY_CODE.match(code)
        status = await device.vault.status()
        assert status.state == VaultState.READY
        assert status.vault_id is not None and status.vault_id.startswith("vlt_")
        assert status.created_at is not None and status.devices_count == 1
        assert status.recovery_kit_saved is False and status.other_vaults == 0

        context = await device.vault.require()
        header = await device.vault.read_header()
        assert header is not None and header.vault_id == status.vault_id
        assert header.layout == context.layout and header.current_epoch == 1
        assert device.crypto.verify_header_mac(context.keyring, header.canonical_unsigned_bytes(), header.mac)
        # The pinned header carries the recovery wrap, never the keyring or the code.
        pinned = device.cloud.chat(context.layout.sync_channel_id).pinned_message_id
        text = device.cloud.message(context.layout.sync_channel_id, pinned).text or ""
        assert code not in text and json.loads(text)["recovery"]["alg"] == "hkdf-aesgcm-v1"

        [registered] = await device.devices.list()
        assert registered.current and registered.id == context.device.device_id
        assert registered.name == "desk · Linux"
        assert len(registered.public_key) == 43 and "=" not in registered.public_key
        # Telegram lists this session as "Bento (<last 6 chars of the device id>)".
        models = {item.device_model for item in device.cloud.authorizations()}
        assert f"Bento ({context.device.device_id[-6:]})" in models
        assert await device.state.get_value(BOOTSTRAP_PENDING_KEY) == "0"
        with pytest.raises(VaultAlreadyExistsError):
            await device.vault.create()

    run(scenario())


def test_recovery_kit_confirmation_needs_the_last_group(tmp_path: Path) -> None:
    async def scenario() -> None:
        device, code = await _first_device(tmp_path)

        with pytest.raises(RecoveryGroupMismatchError) as raised:
            await device.vault.confirm_recovery_kit("ZZZZ")
        assert raised.value.code == "recovery_group_mismatch"
        status = await device.vault.confirm_recovery_kit(code.split("-")[-1].lower())
        assert status.recovery_kit_saved is True

    run(scenario())


def test_second_device_unlocks_with_the_recovery_code(tmp_path: Path) -> None:
    async def scenario() -> None:
        first, code = await _first_device(tmp_path)
        laptop = make_vault_device(tmp_path, tmp_path / "cloud", "laptop")
        await laptop.sign_in()

        locked = await laptop.vault.status()
        assert locked.state == VaultState.LOCKED
        assert locked.vault_id == (await first.vault.status()).vault_id
        with pytest.raises(VaultLockedError):
            await laptop.vault.require()
        with pytest.raises(RecoveryCodeInvalidError):
            await laptop.vault.unlock("not a code")
        wrong = first.crypto.generate_recovery_code()
        with pytest.raises(RecoveryCodeInvalidError):
            await laptop.vault.unlock(wrong)
        assert await laptop.vault.verify_recovery_code(wrong) is False
        assert await laptop.vault.verify_recovery_code(code) is True

        unlocked = await laptop.vault.unlock(code.lower().replace("-", " "))

        assert unlocked.state == VaultState.BOOTSTRAPPING and unlocked.recovery_kit_saved is True
        first_context, laptop_context = await first.vault.require(), await laptop.vault.require()
        assert laptop_context.keyring.keys == first_context.keyring.keys
        assert laptop_context.layout == first_context.layout
        assert laptop_context.device.device_id != first_context.device.device_id
        [registered] = await laptop.devices.list()
        assert registered.id == laptop_context.device.device_id and registered.current
        # The sync engine clears the bootstrap flag once caught up.
        await laptop.state.set_value(BOOTSTRAP_PENDING_KEY, "0")
        assert (await laptop.vault.status()).state == VaultState.READY
        # Unlocking again keeps the device ready.
        assert (await laptop.vault.unlock(code)).state == VaultState.READY

    run(scenario())


def test_tampered_header_is_rejected(tmp_path: Path) -> None:
    async def scenario() -> None:
        first, code = await _first_device(tmp_path)
        layout = (await first.vault.require()).layout
        header = await first.vault.read_header()
        assert header is not None
        forged = replace(header, created_at=header.created_at.replace(year=2020))
        await first.runtime.transport.publish_header_text(layout, forged.to_json())

        assert await first.vault.read_header() is None
        with pytest.raises(IntegrityError):
            await first.vault.update_header(lambda current: current)
        fresh = make_vault_device(tmp_path, tmp_path / "cloud", "fresh")
        await fresh.sign_in()
        with pytest.raises(IntegrityError):
            await fresh.vault.unlock(code)
        assert await fresh.key_store.get(VAULT_KEYRING) is None

    run(scenario())


def test_rotating_the_recovery_code_invalidates_the_old_one(tmp_path: Path) -> None:
    async def scenario() -> None:
        first, old_code = await _first_device(tmp_path)
        await first.vault.confirm_recovery_kit(old_code.split("-")[-1])

        new_code = await first.vault.rotate_recovery_code()

        assert new_code != old_code and RECOVERY_CODE.match(new_code)
        assert (await first.vault.status()).recovery_kit_saved is False
        with pytest.raises(RecoveryGroupMismatchError):
            await first.vault.confirm_recovery_kit(old_code.split("-")[-1])
        assert await first.vault.verify_recovery_code(old_code) is False
        assert await first.vault.verify_recovery_code(new_code) is True
        other = make_vault_device(tmp_path, tmp_path / "cloud", "other")
        await other.sign_in()
        with pytest.raises(RecoveryCodeInvalidError):
            await other.vault.unlock(old_code)
        assert (await other.vault.unlock(new_code)).state == VaultState.BOOTSTRAPPING

    run(scenario())


def test_keyring_rotation_then_header_update_uses_the_new_epoch(tmp_path: Path) -> None:
    """Device removal stores the rotated keyring first, then publishes the new header."""

    async def scenario() -> None:
        first, _ = await _first_device(tmp_path)
        context = await first.vault.require()
        rotated = first.crypto.rotate_keyring(context.keyring)

        with pytest.raises(ValidationFailedError):
            await first.vault.update_keyring(replace(rotated, keys={2: rotated.keys[2]}, current_epoch=2))
        await first.vault.update_keyring(rotated)
        assert await first.vault.read_header() is not None  # still verified with the epoch it declares
        code = first.crypto.generate_recovery_code()
        wrap = first.crypto.wrap_for_recovery(rotated, code)

        header = await first.vault.update_header(lambda current: replace(current, recovery=wrap))

        assert header.current_epoch == 2
        assert first.crypto.verify_header_mac(rotated, header.canonical_unsigned_bytes(), header.mac)
        assert (await first.vault.read_header()) == header
        with pytest.raises(ValidationFailedError):
            await first.vault.update_header(lambda current: replace(current, vault_id="vlt_other"))
        joiner = make_vault_device(tmp_path, tmp_path / "cloud", "joiner")
        await joiner.sign_in()
        await joiner.vault.unlock(code)
        assert (await joiner.vault.require()).keyring.current_epoch == 2

    run(scenario())


def test_install_registers_the_device_and_merges_epochs(tmp_path: Path) -> None:
    async def scenario() -> None:
        first, _ = await _first_device(tmp_path)
        context = await first.vault.require()
        guest = make_vault_device(tmp_path, tmp_path / "cloud", "guest")
        with pytest.raises(TelegramAccountError):
            await guest.vault.install(context.layout, context.keyring)
        await guest.sign_in()
        with pytest.raises(ValidationFailedError):
            await guest.vault.install(replace(context.layout, vault_id="vlt_other"), context.keyring)

        status = await guest.vault.install(context.layout, context.keyring)

        assert status.state == VaultState.BOOTSTRAPPING and status.created_at is not None
        assert (await guest.vault.current()) is not None
        [row] = await guest.devices.list()
        assert row.current and row.public_key
        rotated = first.crypto.rotate_keyring(context.keyring)
        await guest.vault.install(context.layout, replace(rotated, keys={2: rotated.keys[2], 1: context.keyring.keys[1]}))
        assert set((await guest.vault.require()).keyring.keys) == {1, 2}

    run(scenario())


def test_create_resumes_after_a_crash_before_the_header(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_vault_device(tmp_path, tmp_path / "cloud", "desk")
        await device.sign_in()
        transport = device.runtime.transport
        original = transport.publish_header_text

        async def crash(*_args: object) -> int:
            raise RuntimeError("power cut")

        transport.publish_header_text = crash  # type: ignore[method-assign]
        with pytest.raises(RuntimeError):
            await device.vault.create()
        assert (await device.vault.status()).state == VaultState.NO_VAULT
        assert await device.state.get_value(LAYOUT_KEY) is None
        transport.publish_header_text = original  # type: ignore[method-assign]

        created = await device.vault.create()

        assert len(await transport.find_vaults()) == 1
        assert created.status.state == VaultState.READY
        stored = device.crypto.keyring_from_bytes(await device.key_store.get(VAULT_KEYRING) or b"")
        assert created.status.vault_id == stored.vault_id

    run(scenario())


def test_create_refuses_when_the_account_already_has_a_vault(tmp_path: Path) -> None:
    async def scenario() -> None:
        await _first_device(tmp_path)
        other = make_vault_device(tmp_path, tmp_path / "cloud", "other")
        await other.sign_in()
        with pytest.raises(VaultAlreadyExistsError):
            await other.vault.create()

    run(scenario())


def test_discovery_picks_the_newest_vault_and_counts_the_others(tmp_path: Path) -> None:
    async def scenario() -> None:
        old, _ = await _first_device(tmp_path)
        old_id = (await old.vault.status()).vault_id
        newer = make_vault_device(tmp_path, tmp_path / "cloud", "newer")
        await newer.sign_in()
        # Simulate an account that already holds two vaults (e.g. created by two first-run devices).
        newer.clock.advance(days=3)
        newer.vault._discover = _no_vaults(newer.vault._discover)  # type: ignore[method-assign]
        created = await newer.vault.create()
        observer = make_vault_device(tmp_path, tmp_path / "cloud", "observer")
        await observer.sign_in()

        status = await observer.vault.status()

        assert status.state == VaultState.LOCKED
        assert status.vault_id == created.status.vault_id != old_id
        assert status.other_vaults == 1

    run(scenario())


def test_a_saved_local_choice_becomes_telegram_once_a_vault_exists(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_vault_device(tmp_path, tmp_path / "cloud", "desk")
        settings = SQLiteSettingsRepository(device.sessions, device.clock)
        await settings.compare_and_set(expected_revision=0, values={"storage_backend": json.dumps("local")}, secret_references={})
        await device.sign_in()

        await device.vault.create()

        persisted = await settings.load()
        assert json.loads(persisted.values["storage_backend"]) == "telegram"
        assert persisted.revision == 2

    run(scenario())


def test_a_different_account_does_not_reuse_the_stored_vault(tmp_path: Path) -> None:
    async def scenario() -> None:
        device, _ = await _first_device(tmp_path)
        raw = await device.state.get_value(LAYOUT_KEY)
        assert raw is not None
        await device.state.set_value(LAYOUT_KEY, json.dumps({**json.loads(raw), "account_user_id": 1}))

        assert (await device.vault.status()).state == VaultState.LOCKED
        assert await device.vault.current() is None

    run(scenario())


def _no_vaults(discover):  # type: ignore[no-untyped-def]
    async def wrapper(ports, *, fresh: bool = False):  # type: ignore[no-untyped-def]
        result = await discover(ports, fresh=fresh)
        return replace(result, layout=None, header=None, others=0)

    return wrapper


def test_header_json_round_trip_is_stable(tmp_path: Path) -> None:
    async def scenario() -> None:
        device, _ = await _first_device(tmp_path)
        header = await device.vault.read_header()
        assert header is not None
        assert VaultHeader.from_json(header.to_json()) == header

    run(scenario())


def test_device_removal_rotates_keys_through_the_real_vault_session(tmp_path: Path) -> None:
    from bento.application.devices import DeviceService

    async def scenario() -> None:
        first, old_code = await _first_device(tmp_path)
        context = await first.vault.require()
        guest = make_vault_device(tmp_path, tmp_path / "cloud", "guest")
        await guest.sign_in()
        await guest.vault.install(context.layout, context.keyring)
        [guest_row] = await guest.devices.list()
        await first.devices.save(replace(guest_row, current=False))
        service = DeviceService(
            devices=first.devices,
            vault=first.vault,
            account=first.runtime.account,
            transport=first.runtime.transport,
            crypto=first.crypto,
        )

        removal = await service.remove(guest_row.id)

        assert removal.device.removed_at is not None and RECOVERY_CODE.match(removal.recovery_code)
        # Telegram matched the guest's session by its announced "Bento (<suffix>)" name.
        assert removal.telegram_session_closed is True
        rotated = await first.vault.require()
        assert rotated.keyring.current_epoch == 2
        header = await first.vault.read_header()
        assert header is not None and header.current_epoch == 2
        assert await first.vault.verify_recovery_code(old_code) is False
        assert await first.vault.verify_recovery_code(removal.recovery_code) is True

    run(scenario())
