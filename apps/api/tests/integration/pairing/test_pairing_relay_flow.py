"""Two in-process devices pairing over the relay double and the fake Telegram cloud."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from bento.adapters.fake_telegram import FakeTelegramCloud
from bento.application.devices import telegram_device_model
from bento.application.pairing import PairingTimeouts, b64url_encode
from bento.domain.errors import TelegramAccountError
from bento.domain.pairing import PairingCode, PairingError, PairingState
from bento.domain.vault import VaultState
from tests.integration.fake_telegram.support import ManualClock
from tests.integration.pairing.pairing_support import FAST, PairingDevice, make_pairing_device, wait_for_state
from tests.integration.pairing.relay_double import RelayDouble


async def _devices(
    tmp_path: Path,
    relay: RelayDouble,
    *,
    clock: ManualClock | None = None,
    guest_timeouts: PairingTimeouts = FAST,
) -> tuple[PairingDevice, PairingDevice]:
    url = await relay.start()
    cloud_dir = tmp_path / "cloud"
    host = make_pairing_device(tmp_path, cloud_dir, "host", relay_url=url, clock=clock)
    guest = make_pairing_device(tmp_path, cloud_dir, "guest", relay_url=url, clock=clock, timeouts=guest_timeouts)
    await host.sign_in()
    await host.vault.create_vault()
    return host, guest


async def _until_both_awaiting(host: PairingDevice, guest: PairingDevice, host_id: str, guest_id: str) -> None:
    host_view = await wait_for_state(lambda: host.pairing.get(host_id), PairingState.AWAITING_APPROVAL)
    guest_view = await wait_for_state(lambda: guest.pairing.get(guest_id), PairingState.AWAITING_APPROVAL)
    assert host_view.session.sas is not None and len(host_view.session.sas) == 4
    assert host_view.session.sas == guest_view.session.sas
    assert host_view.session.peer is not None and host_view.session.peer.device_name == "guest · Linux"


def test_guest_without_telegram_is_signed_in_by_the_host_and_receives_the_vault(tmp_path: Path) -> None:
    async def scenario() -> None:
        relay = RelayDouble()
        host, guest = await _devices(tmp_path, relay)
        try:
            assert (await guest.vault.status()).state == VaultState.SIGNED_OUT
            hosted = await host.pairing.host()
            assert hosted.session.state == PairingState.WAITING and hosted.session.code is not None
            joined = await guest.pairing.join(hosted.session.code.link())
            assert joined.session.code is None

            await _until_both_awaiting(host, guest, hosted.session.id, joined.session.id)
            approving = await host.pairing.approve(hosted.session.id)
            assert approving.session.state == PairingState.APPROVING

            done_host = await wait_for_state(lambda: host.pairing.get(hosted.session.id), PairingState.COMPLETED)
            done_guest = await wait_for_state(lambda: guest.pairing.get(joined.session.id), PairingState.COMPLETED)
            assert done_host.session.code is None and done_guest.session.error_code is None

            assert (await guest.runtime.account.status()).authorized
            assert await guest.vault.keyring() == await host.vault.keyring()
            assert guest.vault.installs[0][0] == host.vault.layout
            assert (await guest.vault.status()).state == VaultState.READY

            recorded = await host.devices.get(guest.device_id)
            assert recorded is not None and not recorded.current and recorded.active
            assert recorded.public_key == b64url_encode(guest.identity.public_key)
            authorizations = FakeTelegramCloud(tmp_path / "cloud").authorizations()
            guest_session = next(item for item in authorizations if item.device_model == telegram_device_model(guest.device_id))
            assert recorded.telegram_auth_hash == guest_session.hash
            assert len(host.account.accepted_tokens) == 1
        finally:
            await host.pairing.close()
            await guest.pairing.close()
            await relay.stop()

    asyncio.run(scenario())


def test_wrong_code_fails_on_both_sides_and_burns_the_room(tmp_path: Path) -> None:
    async def scenario() -> None:
        relay = RelayDouble()
        host, guest = await _devices(tmp_path, relay)
        await guest.sign_in()
        try:
            hosted = await host.pairing.host()
            code = hosted.session.code
            assert code is not None
            wrong_secret = "0000000Z" if code.secret != "0000000Z" else "0000000Y"
            joined = await guest.pairing.join(PairingCode(code.nameplate, wrong_secret).format())

            failed_guest = await wait_for_state(lambda: guest.pairing.get(joined.session.id), PairingState.FAILED)
            failed_host = await wait_for_state(lambda: host.pairing.get(hosted.session.id), PairingState.FAILED)
            assert failed_guest.session.error_code == "pairing_code_mismatch"
            assert failed_host.session.error_code == "pairing_code_mismatch"
            assert failed_host.session.sas is None and failed_guest.session.sas is None
            assert relay.rooms[code.nameplate].burned

            with pytest.raises(PairingError) as retry:
                await guest.pairing.join(code.format())
            assert retry.value.code == "pairing_room_full"
            assert await host.devices.get(guest.device_id) is None
            assert (await guest.vault.status()).state == VaultState.LOCKED
        finally:
            await host.pairing.close()
            await guest.pairing.close()
            await relay.stop()

    asyncio.run(scenario())


def test_rejection_ends_both_sessions(tmp_path: Path) -> None:
    async def scenario() -> None:
        relay = RelayDouble()
        host, guest = await _devices(tmp_path, relay)
        try:
            hosted = await host.pairing.host()
            assert hosted.session.code is not None
            joined = await guest.pairing.join(hosted.session.code.format())
            await _until_both_awaiting(host, guest, hosted.session.id, joined.session.id)

            rejected = await host.pairing.reject(hosted.session.id)
            assert rejected.session.state == PairingState.REJECTED
            guest_view = await wait_for_state(lambda: guest.pairing.get(joined.session.id), PairingState.REJECTED)
            assert guest_view.session.sas is None
            assert host.account.accepted_tokens == []
            assert await host.devices.get(guest.device_id) is None
            assert not (await guest.runtime.account.status()).authorized
        finally:
            await host.pairing.close()
            await guest.pairing.close()
            await relay.stop()

    asyncio.run(scenario())


def test_expired_login_token_is_refreshed_on_request(tmp_path: Path) -> None:
    async def scenario() -> None:
        relay = RelayDouble()
        clock = ManualClock()
        # The guest polls rarely, so a fresh token only arrives because the host asks for one.
        host, guest = await _devices(tmp_path, relay, clock=clock, guest_timeouts=replace(FAST, login_poll_interval=3.0))
        try:
            hosted = await host.pairing.host()
            assert hosted.session.code is not None
            joined = await guest.pairing.join(hosted.session.code.format())
            await _until_both_awaiting(host, guest, hosted.session.id, joined.session.id)

            clock.advance(120)  # the forwarded QR token is now expired
            await host.pairing.approve(hosted.session.id)
            await wait_for_state(lambda: host.pairing.get(hosted.session.id), PairingState.COMPLETED)
            await wait_for_state(lambda: guest.pairing.get(joined.session.id), PairingState.COMPLETED)

            assert len(host.account.accepted_tokens) >= 2
            assert len(set(host.account.accepted_tokens)) == len(host.account.accepted_tokens)
            assert (await guest.runtime.account.status()).authorized
        finally:
            await host.pairing.close()
            await guest.pairing.close()
            await relay.stop()

    asyncio.run(scenario())


def test_telegram_login_failed_falls_back_to_the_guest_qr(tmp_path: Path) -> None:
    async def scenario() -> None:
        relay = RelayDouble()
        host, guest = await _devices(tmp_path, relay)
        host.account.accept_error = TelegramAccountError("telegram_network", "Network down")
        try:
            hosted = await host.pairing.host()
            assert hosted.session.code is not None
            joined = await guest.pairing.join(hosted.session.code.format())
            await _until_both_awaiting(host, guest, hosted.session.id, joined.session.id)
            await host.pairing.approve(hosted.session.id)

            needs = await wait_for_state(lambda: guest.pairing.get(joined.session.id), PairingState.NEEDS_TELEGRAM_LOGIN)
            assert needs.telegram_login_url is not None and needs.telegram_login_url.startswith("tg://login?token=")
            assert needs.session.needs_telegram_qr
            await wait_for_state(lambda: host.pairing.get(hosted.session.id), PairingState.NEEDS_TELEGRAM_LOGIN)

            assert FakeTelegramCloud(tmp_path / "cloud").approve_pending_logins() == 1  # the phone scans it
            await wait_for_state(lambda: guest.pairing.get(joined.session.id), PairingState.COMPLETED)
            await wait_for_state(lambda: host.pairing.get(hosted.session.id), PairingState.COMPLETED)
            assert await guest.vault.keyring() == await host.vault.keyring()
            recorded = await host.devices.get(guest.device_id)
            assert recorded is not None and recorded.telegram_auth_hash is None
        finally:
            await host.pairing.close()
            await guest.pairing.close()
            await relay.stop()

    asyncio.run(scenario())
