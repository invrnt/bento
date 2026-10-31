"""Device removal: Telegram session termination and vault key rotation on the fake cloud."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bento.adapters.fake_telegram import FakeTelegramCloud
from bento.application.devices import DeviceIsCurrentError, telegram_device_model
from bento.application.pairing import b64url_decode, b64url_encode
from bento.application.sync.keys import grant_auth_payload, parse_keys_message
from bento.domain.devices import Device, DevicePlatform
from bento.domain.errors import DeviceNotFoundError, IntegrityError, RecoveryCodeInvalidError
from bento.domain.security import SealPurpose
from bento.domain.sync import SyncMessageKind
from bento.domain.vault import VaultHeader
from tests.integration.pairing.pairing_support import PairingDevice, make_pairing_device


async def _vault_with_three_devices(
    tmp_path: Path, **host_options: object
) -> tuple[PairingDevice, PairingDevice, PairingDevice, str]:
    """A vault created by `host`; `laptop` and `desktop` hold the keyring and are listed on the host."""
    cloud_dir = tmp_path / "cloud"
    host = make_pairing_device(tmp_path, cloud_dir, "host", **host_options)  # type: ignore[arg-type]
    await host.sign_in()
    recovery_code = await host.vault.create_vault()
    keyring = await host.vault.keyring()
    assert keyring is not None and host.vault.layout is not None
    others = []
    for name in ("laptop", "desktop"):
        device = make_pairing_device(tmp_path, cloud_dir, name)
        await device.sign_in()
        await device.vault.install(host.vault.layout, keyring)
        await host.devices.save(
            Device(
                id=device.device_id,
                name=f"{name} · Linux",
                platform=DevicePlatform.LINUX,
                public_key=b64url_encode(device.identity.public_key),
                added_at=datetime.now(UTC),
            )
        )
        others.append(device)
    return host, others[0], others[1], recovery_code


async def _keys_messages(device: PairingDevice) -> list[dict[str, object]]:
    layout = device.vault.layout
    assert layout is not None
    refs = await device.runtime.transport.list_sync_messages(layout, after_message_id=0)
    return [
        json.loads(await device.runtime.transport.download_sync_document(layout, ref.message_id))
        for ref in refs
        if ref.kind == SyncMessageKind.KEYS
    ]


def test_removing_a_device_rotates_keys_for_the_remaining_devices(tmp_path: Path) -> None:
    async def scenario() -> None:
        host, removed, kept, old_recovery = await _vault_with_three_devices(tmp_path)
        old_keyring = await host.vault.keyring()
        assert old_keyring is not None and host.vault.layout is not None
        layout = host.vault.layout

        removal = await host.device_service.remove(removed.device_id)

        assert removal.device.id == removed.device_id and removal.device.removed_at is not None
        assert removal.telegram_session_closed is True
        assert removal.recovery_code != old_recovery
        assert not (await removed.runtime.account.status()).authorized
        models = {item.device_model for item in FakeTelegramCloud(tmp_path / "cloud").authorizations()}
        assert telegram_device_model(removed.device_id) not in models
        assert telegram_device_model(kept.device_id) in models

        new_keyring = await host.vault.keyring()
        assert new_keyring is not None
        assert new_keyring.current_epoch == old_keyring.current_epoch + 1
        assert new_keyring.keys[old_keyring.current_epoch] == old_keyring.keys[old_keyring.current_epoch]

        [keys] = await _keys_messages(host)
        assert keys["bento"] == "keys" and keys["v"] == 2 and keys["vault_id"] == layout.vault_id
        assert keys["epoch"] == new_keyring.current_epoch
        assert keys["sender_device_id"] == host.device_id
        assert keys["removed_device_ids"] == [removed.device_id]
        message = parse_keys_message(json.dumps(keys).encode())
        assert set(message.grants) == {host.device_id, kept.device_id}
        kept_grant = message.grants[kept.device_id]
        auth_payload = grant_auth_payload(message, recipient_device_id=kept.device_id, sealed=kept_grant.sealed)
        assert kept.crypto.verify_grant_auth(kept.identity, host.identity.public_key, auth_payload, kept_grant.auth)
        assert not kept.crypto.verify_grant_auth(kept.identity, removed.identity.public_key, auth_payload, kept_grant.auth)
        granted = kept.crypto.open_sealed(
            kept.identity, b64url_decode(kept_grant.sealed, max_bytes=65536), aad=layout.vault_id.encode()
        )
        assert kept.crypto.keyring_from_bytes(granted) == new_keyring
        for grant in message.grants.values():
            with pytest.raises(IntegrityError):
                removed.crypto.open_sealed(
                    removed.identity, b64url_decode(grant.sealed, max_bytes=65536), aad=layout.vault_id.encode()
                )

        batch = host.crypto.seal(new_keyring, SealPurpose.SYNC, b"new batch after removal")
        removed_keyring = await removed.vault.keyring()
        assert removed_keyring is not None
        with pytest.raises(IntegrityError):
            removed.crypto.open(removed_keyring, SealPurpose.SYNC, batch)
        assert kept.crypto.open(kept.crypto.keyring_from_bytes(granted), SealPurpose.SYNC, batch) == b"new batch after removal"

        text = await host.runtime.transport.read_header_text(layout)
        assert text is not None
        header = VaultHeader.from_json(text)
        assert header.current_epoch == new_keyring.current_epoch
        assert host.crypto.verify_header_mac(new_keyring, header.canonical_unsigned_bytes(), header.mac)
        with pytest.raises(RecoveryCodeInvalidError):
            host.crypto.unwrap_with_recovery(header.recovery, old_recovery, vault_id=layout.vault_id)
        assert host.crypto.unwrap_with_recovery(header.recovery, removal.recovery_code, vault_id=layout.vault_id) == new_keyring

        listed = await host.device_service.list()
        assert {device.id for device in listed} == {host.device_id, kept.device_id}
        assert [device.current for device in listed if device.id == host.device_id] == [True]
        everything = await host.device_service.list(include_removed=True)
        assert removed.device_id in {device.id for device in everything}

    asyncio.run(scenario())


def test_removal_continues_when_telegram_says_the_session_is_too_new(tmp_path: Path) -> None:
    async def scenario() -> None:
        host, removed, _, _ = await _vault_with_three_devices(tmp_path, session_too_new=True)
        removal = await host.device_service.remove(removed.device_id)
        assert removal.telegram_session_closed is False
        assert (await removed.runtime.account.status()).authorized
        keyring = await host.vault.keyring()
        assert keyring is not None and keyring.current_epoch == 2

        # Retrying the removal rotates again and returns another recovery code.
        retry = await host.device_service.remove(removed.device_id)
        assert retry.recovery_code != removal.recovery_code
        keyring = await host.vault.keyring()
        assert keyring is not None and keyring.current_epoch == 3
        assert len(await _keys_messages(host)) == 2

    asyncio.run(scenario())


def test_removal_guards(tmp_path: Path) -> None:
    async def scenario() -> None:
        host, _, _, _ = await _vault_with_three_devices(tmp_path)
        with pytest.raises(DeviceIsCurrentError):
            await host.device_service.remove(host.device_id)
        with pytest.raises(DeviceNotFoundError):
            await host.device_service.remove("dev_missing")
        keyring = await host.vault.keyring()
        assert keyring is not None and keyring.current_epoch == 1

    asyncio.run(scenario())


def test_rename_validates_and_persists(tmp_path: Path) -> None:
    async def scenario() -> None:
        host, laptop, _, _ = await _vault_with_three_devices(tmp_path)
        renamed = await host.device_service.rename(laptop.device_id, "  Portátil   de Ana ")
        assert renamed.name == "Portátil de Ana"
        stored = await host.devices.get(laptop.device_id)
        assert stored is not None and stored.name == "Portátil de Ana"
        current = await host.device_service.rename(host.device_id, "Oficina")
        assert current.current and current.last_seen_at is not None

    asyncio.run(scenario())
