from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest

from bento.adapters.security import VaultCrypto
from bento.application.devices import (
    DeviceRotationIncompleteError,
    DeviceService,
    keys_message,
    match_authorizations,
    telegram_device_model,
)
from bento.application.pairing import b64url_encode
from bento.domain.account import TelegramAuthorization
from bento.domain.devices import Device, DevicePlatform
from bento.domain.errors import StorageUnavailableError, TelegramAccountError
from bento.domain.sync import SyncMessageKind
from bento.domain.vault import VaultHeader
from tests.unit.pairing.pairing_doubles import LAYOUT, MemoryDevices, MemoryTransport, MemoryVault, StubAccount

NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)
DEVICE = Device(
    id="dev_0123456789abcdef0123456789abcdef",
    name="Portátil",
    platform=DevicePlatform.LINUX,
    public_key="",
    added_at=NOW,
)


def _authorization(hash_: int, model: str, *, current: bool = False) -> TelegramAuthorization:
    return TelegramAuthorization(
        hash=hash_, device_model=model, platform="linux", app_name="Bento", created_at=NOW, last_active_at=NOW, current=current
    )


def test_device_model_uses_the_last_six_characters_of_the_device_id() -> None:
    assert telegram_device_model(DEVICE.id) == "Bento (abcdef)"


def test_match_authorizations_by_hash_or_device_model() -> None:
    others = [
        _authorization(0, "Bento (abcdef)", current=True),
        _authorization(11, "Pixel 8"),
        _authorization(22, "Bento (abcdef)"),
        _authorization(33, "Bento (123456)"),
    ]
    assert [item.hash for item in match_authorizations(DEVICE, others)] == [22]
    assert [item.hash for item in match_authorizations(_with_hash(11), others)] == [11, 22]
    assert match_authorizations(_with_hash(0), [_authorization(0, "Bento (abcdef)", current=True)]) == ()
    assert match_authorizations(DEVICE, [_authorization(44, "Bento (abcdef) extra")]) == ()


def _with_hash(value: int) -> Device:
    return Device(
        id=DEVICE.id,
        name=DEVICE.name,
        platform=DEVICE.platform,
        public_key=DEVICE.public_key,
        added_at=DEVICE.added_at,
        telegram_auth_hash=value,
    )


def test_keys_message_is_canonical_json() -> None:
    payload = keys_message("vlt_x", 3, {"dev_b": "g2", "dev_a": "g1"})
    assert payload == b'{"bento":"keys","epoch":3,"grants":{"dev_a":"g1","dev_b":"g2"},"v":1,"vault_id":"vlt_x"}'
    assert SyncMessageKind.from_filename("x" + SyncMessageKind.KEYS.suffix) is SyncMessageKind.KEYS
    assert json.loads(payload)["grants"]["dev_a"] == "g1"


class _FailingHeaderVault(MemoryVault):
    async def update_header(self, mutate):  # type: ignore[no-untyped-def]
        raise StorageUnavailableError("telegram")


class _TerminatingAccount(StubAccount):
    def __init__(self, authorizations: tuple[TelegramAuthorization, ...], error: TelegramAccountError | None = None) -> None:
        super().__init__()
        self.authorizations = authorizations
        self.error = error
        self.terminated: list[int] = []

    async def list_authorizations(self) -> tuple[TelegramAuthorization, ...]:
        return self.authorizations

    async def terminate_authorization(self, authorization_hash: int) -> None:
        if self.error is not None:
            raise self.error
        self.terminated.append(authorization_hash)


def _service(vault: MemoryVault, account: StubAccount, devices: MemoryDevices, transport: MemoryTransport) -> DeviceService:
    return DeviceService(
        devices=devices,
        vault=vault,  # type: ignore[arg-type]
        account=account,  # type: ignore[arg-type]
        transport=transport,  # type: ignore[arg-type]
        crypto=VaultCrypto(),
        clock=lambda: NOW,
    )


def test_rotation_reports_an_incomplete_header_update_and_can_be_retried() -> None:
    async def scenario() -> None:
        crypto = VaultCrypto()
        vault = _FailingHeaderVault(crypto, keyring=crypto.generate_keyring(LAYOUT.vault_id))
        other = crypto.generate_device_identity()
        devices = MemoryDevices()
        await devices.save(
            Device(
                id=other.device_id,
                name="Otro",
                platform=DevicePlatform.MACOS,
                public_key=b64url_encode(other.public_key),
                added_at=NOW,
            )
        )
        await devices.save(
            Device(id="dev_broken", name="Sin clave", platform=DevicePlatform.OTHER, public_key="??", added_at=NOW)
        )
        account = _TerminatingAccount((_authorization(55, telegram_device_model(other.device_id)),))
        transport = MemoryTransport()
        service = _service(vault, account, devices, transport)

        with pytest.raises(DeviceRotationIncompleteError) as incomplete:
            await service.remove(other.device_id)
        assert incomplete.value.code == "device_rotation_incomplete"
        assert account.terminated == [55]
        assert devices.items[other.device_id].removed_at == NOW
        assert vault.keyring is not None and vault.keyring.current_epoch == 2
        [keys] = [transport.documents[ref.message_id] for ref in transport.messages if ref.kind is SyncMessageKind.KEYS]
        assert set(json.loads(keys)["grants"]) == {vault.identity.device_id}, "no grant for the removed or keyless device"

        working = MemoryVault(crypto, keyring=vault.keyring)
        working.identity = vault.identity
        header_box: list[VaultHeader] = []

        async def update_header(mutate):  # type: ignore[no-untyped-def]
            header = VaultHeader(
                vault_id=LAYOUT.vault_id,
                created_at=NOW,
                layout=LAYOUT,
                current_epoch=2,
                recovery=crypto.wrap_for_recovery(vault.keyring, crypto.generate_recovery_code()),  # type: ignore[arg-type]
            )
            header_box.append(mutate(header))
            return header_box[-1]

        working.update_header = update_header  # type: ignore[method-assign]
        retry = await _service(working, account, devices, transport).remove(other.device_id)
        assert retry.device.removed_at == NOW and retry.recovery_code
        assert header_box[-1].current_epoch == 3 and header_box[-1].mac is None
        assert crypto.unwrap_with_recovery(header_box[-1].recovery, retry.recovery_code, vault_id=LAYOUT.vault_id).current_epoch == 3

    asyncio.run(scenario())


def test_telegram_errors_do_not_block_removal_until_rotation() -> None:
    async def scenario() -> None:
        crypto = VaultCrypto()
        vault = _FailingHeaderVault(crypto, keyring=crypto.generate_keyring(LAYOUT.vault_id))
        devices = MemoryDevices()
        await devices.save(DEVICE)
        account = _TerminatingAccount(
            (_authorization(66, "Bento (abcdef)"),), error=TelegramAccountError("telegram_session_too_new", "too new")
        )
        with pytest.raises(DeviceRotationIncompleteError):
            await _service(vault, account, devices, MemoryTransport()).remove(DEVICE.id)
        assert devices.items[DEVICE.id].removed_at == NOW

    asyncio.run(scenario())
