"""Vault-wide recovery kit confirmation and deletion of superseded headers, on the fake cloud."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bento.adapters.security import VaultCrypto
from bento.application.vault import RECOVERY_KIT_SAVED_KEY
from bento.domain.errors import IntegrityError, RecoveryCodeInvalidError, StorageUnavailableError
from bento.domain.security import RecoveryWrap
from bento.domain.sync import SyncMessageKind
from bento.domain.vault import VaultHeader, VaultLayout
from tests.integration.telegram_vault.support import VaultDevice, make_vault_device


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


def _last_group(code: str) -> str:
    return code.split("-")[-1]


async def _two_devices(tmp_path: Path) -> tuple[VaultDevice, VaultDevice, str]:
    """A creates the vault; B joins through a pairing grant (no recovery code involved)."""
    first = make_vault_device(tmp_path, tmp_path / "cloud", "desk")
    await first.sign_in()
    code = (await first.vault.create()).recovery_code
    second = make_vault_device(tmp_path, tmp_path / "cloud", "laptop")
    await second.sign_in()
    context = await first.vault.require()
    await second.vault.install(context.layout, context.keyring)
    return first, second, code


async def _saved(device: VaultDevice) -> bool:
    device.vault.invalidate()  # other devices' header changes are picked up after a short cache
    return (await device.vault.status()).recovery_kit_saved


def _header_messages(device: VaultDevice, layout: VaultLayout) -> list[tuple[int, str]]:
    _, messages = device.cloud.read_chat(layout.sync_channel_id)
    return [
        (message.id, message.text)
        for message in messages
        if message.media is None and message.text and SyncMessageKind.from_text(message.text) == SyncMessageKind.HEADER
    ]


def test_confirming_the_kit_on_one_device_clears_the_reminder_everywhere(tmp_path: Path) -> None:
    async def scenario() -> None:
        first, second, code = await _two_devices(tmp_path)
        assert await _saved(first) is False and await _saved(second) is False

        await first.vault.confirm_recovery_kit(_last_group(code))

        assert await _saved(first) is True and await _saved(second) is True
        header = await second.vault.read_header()
        assert header is not None and header.recovery.confirmed_at is not None

        # A new code (rotation; device removal works the same way) starts unconfirmed on every device.
        new_code = await first.vault.rotate_recovery_code()
        assert (await first.vault.status()).recovery_kit_saved is False
        assert await _saved(second) is False
        await first.vault.confirm_recovery_kit(_last_group(new_code))
        assert await _saved(second) is True

    run(scenario())


def test_a_confirmation_never_marks_a_code_rotated_elsewhere(tmp_path: Path) -> None:
    async def scenario() -> None:
        first, second, code = await _two_devices(tmp_path)
        await second.vault.rotate_recovery_code()

        # The first device still holds the check of the code it showed, which no longer opens the vault.
        await first.vault.confirm_recovery_kit(_last_group(code))

        assert await _saved(first) is False and await _saved(second) is False

    run(scenario())


def test_unlocking_with_the_code_proves_the_kit_was_saved(tmp_path: Path) -> None:
    async def scenario() -> None:
        first = make_vault_device(tmp_path, tmp_path / "cloud", "desk")
        await first.sign_in()
        code = (await first.vault.create()).recovery_code
        fresh = make_vault_device(tmp_path, tmp_path / "cloud", "fresh")
        await fresh.sign_in()

        assert (await fresh.vault.unlock(code)).recovery_kit_saved is True
        assert await _saved(first) is True

    run(scenario())


def test_the_local_flag_answers_when_the_header_cannot_be_read(tmp_path: Path) -> None:
    async def scenario() -> None:
        first, _, code = await _two_devices(tmp_path)
        await first.vault.confirm_recovery_kit(_last_group(code))
        assert await first.state.get_value(RECOVERY_KIT_SAVED_KEY) == "1"
        transport = first.runtime.transport

        async def offline(layout):  # type: ignore[no-untyped-def]
            raise StorageUnavailableError("telegram")

        transport.read_header_text = offline  # type: ignore[method-assign]
        assert await _saved(first) is True
        await first.state.set_value(RECOVERY_KIT_SAVED_KEY, "0")
        assert await _saved(first) is False

    run(scenario())


def test_confirmed_at_is_mac_covered_and_optional_on_the_wire() -> None:
    crypto = VaultCrypto()
    keyring = crypto.generate_keyring("vlt_header")
    layout = VaultLayout(vault_id="vlt_header", files_channel_id=-1001, sync_channel_id=-1002, inbox_channel_id=-1003)
    unsigned = VaultHeader(
        vault_id="vlt_header",
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        layout=layout,
        current_epoch=1,
        recovery=RecoveryWrap(alg="hkdf-aesgcm-v1", nonce="bm9uY2U", wrapped_keyring="d3JhcHBlZA"),
    )
    # Headers without the field serialize exactly as before it existed, so their MACs still verify.
    assert "confirmed_at" not in json.loads(unsigned.canonical_unsigned_bytes())["recovery"]
    confirmed = replace(unsigned, recovery=replace(unsigned.recovery, confirmed_at=datetime(2026, 10, 2, tzinfo=UTC)))
    signed = replace(confirmed, mac=crypto.header_mac(keyring, confirmed.canonical_unsigned_bytes()))

    parsed = VaultHeader.from_json(signed.to_json())
    assert parsed == signed and parsed.recovery.confirmed_at == datetime(2026, 10, 2, tzinfo=UTC)
    assert crypto.verify_header_mac(keyring, parsed.canonical_unsigned_bytes(), parsed.mac)
    stripped = replace(parsed, recovery=replace(parsed.recovery, confirmed_at=None))
    assert not crypto.verify_header_mac(keyring, stripped.canonical_unsigned_bytes(), parsed.mac)


def test_rotation_leaves_no_header_the_old_code_can_open(tmp_path: Path) -> None:
    async def scenario() -> None:
        first, second, old_code = await _two_devices(tmp_path)
        layout = (await first.vault.require()).layout
        await first.vault.confirm_recovery_kit(_last_group(old_code))
        await second.vault.update_header(lambda header: replace(header, snapshot=None))  # a no-op: nothing posted
        assert len(_header_messages(first, layout)) == 1

        new_code = await first.vault.rotate_recovery_code()

        headers = _header_messages(first, layout)
        pinned = first.cloud.chat(layout.sync_channel_id).pinned_message_id
        assert [message_id for message_id, _ in headers] == [pinned]
        old = first.crypto.normalize_recovery_code(old_code)
        for _, text in headers:
            header = VaultHeader.from_json(text)
            with pytest.raises((RecoveryCodeInvalidError, IntegrityError)):
                first.crypto.unwrap_with_recovery(header.recovery, old, vault_id=header.vault_id)
            assert first.crypto.unwrap_with_recovery(header.recovery, new_code, vault_id=header.vault_id)

    run(scenario())


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def test_header_cleanup_is_best_effort_and_catches_up_later(tmp_path: Path) -> None:
    records = _Records()

    async def scenario() -> None:
        first, second, code = await _two_devices(tmp_path)
        logger = logging.getLogger("bento.vault")
        logger.disabled = False  # migrations run Alembic's fileConfig, which disables existing loggers
        logger.addHandler(records)
        layout = (await first.vault.require()).layout
        transport = first.runtime.transport
        original = transport.delete_sync_messages

        async def refusing(layout, message_ids):  # type: ignore[no-untyped-def]
            raise StorageUnavailableError("telegram")

        transport.delete_sync_messages = refusing  # type: ignore[method-assign]
        rotated_code = await first.vault.rotate_recovery_code()
        assert len(_header_messages(first, layout)) == 2
        logged = "\n".join(records.messages)
        assert "superseded vault header" in logged
        assert code not in logged and rotated_code not in logged and str(layout.vault_id) not in logged

        # The next header update (any device) deletes what the failed cleanup left behind.
        transport.delete_sync_messages = original  # type: ignore[method-assign]
        await second.vault.rotate_recovery_code()
        newest = second.cloud.chat(layout.sync_channel_id).pinned_message_id
        assert [message_id for message_id, _ in _header_messages(first, layout)] == [newest]

    try:
        run(scenario())
    finally:
        logging.getLogger("bento.vault").removeHandler(records)
