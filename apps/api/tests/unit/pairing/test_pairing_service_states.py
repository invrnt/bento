"""`PairingService` state machine, timeouts, and hostile peers with in-memory doubles."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import pytest

from bento.adapters.security import PairingCryptoFactory, VaultCrypto
from bento.application.pairing import PairingService, PairingView, b64url_encode, join_request_message
from bento.domain.devices import DevicePlatform
from bento.domain.errors import TelegramAccountError, VaultLockedError
from bento.domain.pairing import PairingCode, PairingError, PairingRole, PairingState
from tests.unit.pairing.pairing_doubles import UNIT, MemoryRelay, make_unit_device, with_timeouts

CRYPTO = VaultCrypto()


async def _until(get: Callable[[], Awaitable[PairingView]], *states: PairingState, timeout: float = 5.0) -> PairingView:
    deadline = time.monotonic() + timeout
    view = await get()
    while view.session.state not in states:
        assert time.monotonic() < deadline, f"stuck in {view.session.state} ({view.session.error_code})"
        await asyncio.sleep(0.005)
        view = await get()
    return view


def _states_of(service: PairingService, pairing_id: str) -> list[PairingState]:
    """Record every state a session passes through."""
    seen: list[PairingState] = []
    session = service._sessions[pairing_id]  # observing the state machine
    original = service._notify

    def notify(target: object) -> None:
        if target is session:
            seen.append(session.state)
        original(target)  # type: ignore[arg-type]

    service._notify = notify  # type: ignore[method-assign]
    return seen


def test_relay_states_for_host_and_guest() -> None:
    async def scenario() -> None:
        relay = MemoryRelay()
        host = make_unit_device(relay, crypto=CRYPTO, keyring=CRYPTO.generate_keyring("vlt_unit"))
        guest = make_unit_device(relay, crypto=CRYPTO, keyring=None, authorized=False, name="Nuevo · Linux")
        host.account.on_accept = lambda _token: setattr(guest.account, "authorized", True)

        hosted = await host.service.host()
        host_states = _states_of(host.service, hosted.session.id)
        assert hosted.session.code is not None
        joined = await guest.service.join(hosted.session.code.format())
        guest_states = _states_of(guest.service, joined.session.id)

        await _until(lambda: host.service.get(hosted.session.id), PairingState.AWAITING_APPROVAL)
        await host.service.approve(hosted.session.id)
        await _until(lambda: host.service.get(hosted.session.id), PairingState.COMPLETED)
        await _until(lambda: guest.service.get(joined.session.id), PairingState.COMPLETED)

        assert host_states == [
            PairingState.CONNECTED,
            PairingState.AWAITING_APPROVAL,
            PairingState.APPROVING,
            PairingState.COMPLETED,
        ]
        assert guest_states == [
            PairingState.CONNECTED,
            PairingState.AWAITING_APPROVAL,
            PairingState.APPROVING,
            PairingState.BOOTSTRAPPING,
            PairingState.COMPLETED,
        ]
        assert host.account.accepted == [b"token-0"]
        assert guest.vault.keyring == host.vault.keyring
        recorded = host.devices.items[guest.vault.identity.device_id]
        assert recorded.telegram_auth_hash == 4242 and recorded.name == "Nuevo · Linux"
        await host.service.close()
        await guest.service.close()

    asyncio.run(scenario())


def test_host_without_guest_expires() -> None:
    async def scenario() -> None:
        relay = MemoryRelay()
        host = make_unit_device(
            relay, crypto=CRYPTO, keyring=CRYPTO.generate_keyring("vlt_unit"), timeouts=with_timeouts(UNIT, session_ttl=0.1)
        )
        hosted = await host.service.host()
        expired = await _until(lambda: host.service.get(hosted.session.id), PairingState.EXPIRED)
        assert expired.session.error_code == "pairing_expired" and expired.session.code is None
        assert expired.error_message
        nameplate = relay.opened[0][0]
        assert relay.rooms[nameplate].host is not None and relay.rooms[nameplate].host.closed

    asyncio.run(scenario())


def test_silent_host_times_out_the_guest_handshake() -> None:
    async def scenario() -> None:
        relay = MemoryRelay()
        guest = make_unit_device(relay, crypto=CRYPTO, keyring=None, timeouts=with_timeouts(UNIT, step=0.1))
        host_channel = await relay.open_room("K7Q2", PairingRole.HOST)
        joined = await guest.service.join("K7Q2-MXR9-T4WA")
        failed = await _until(lambda: guest.service.get(joined.session.id), PairingState.FAILED)
        assert failed.session.error_code == "pairing_timeout"
        assert host_channel.sent == []

    asyncio.run(scenario())


def test_wrong_state_operations_are_conflicts() -> None:
    async def scenario() -> None:
        relay = MemoryRelay()
        host = make_unit_device(relay, crypto=CRYPTO, keyring=CRYPTO.generate_keyring("vlt_unit"))
        hosted = await host.service.host()
        for operation in (host.service.approve, host.service.reject):
            with pytest.raises(PairingError) as conflict:
                await operation(hosted.session.id)
            assert conflict.value.code == "pairing_state_conflict"
        with pytest.raises(PairingError) as missing:
            await host.service.get("pair_missing")
        assert missing.value.code == "pairing_not_found"

        cancelled = await host.service.cancel(hosted.session.id)
        assert cancelled.session.state == PairingState.CANCELLED and cancelled.session.error_code is None
        assert (await host.service.cancel(hosted.session.id)).session.state == PairingState.CANCELLED
        room = relay.rooms[relay.opened[0][0]]
        assert room.burned

    asyncio.run(scenario())


def test_a_new_host_session_cancels_the_previous_one_and_taken_nameplates_regenerate() -> None:
    async def scenario() -> None:
        relay = MemoryRelay(taken=2)
        host = make_unit_device(relay, crypto=CRYPTO, keyring=CRYPTO.generate_keyring("vlt_unit"))
        first = await host.service.host()
        assert len(relay.opened) == 3
        second = await host.service.host()
        assert (await host.service.get(first.session.id)).session.state == PairingState.CANCELLED
        assert (await host.service.get(second.session.id)).session.state == PairingState.WAITING
        exhausted = make_unit_device(
            MemoryRelay(taken=99), crypto=CRYPTO, keyring=CRYPTO.generate_keyring("vlt_unit"), timeouts=UNIT
        )
        with pytest.raises(PairingError) as unavailable:
            await exhausted.service.host()
        assert unavailable.value.code == "pairing_relay_unavailable"
        await host.service.close()

    asyncio.run(scenario())


def test_locked_hosts_and_paired_guests_are_refused() -> None:
    async def scenario() -> None:
        relay = MemoryRelay()
        locked = make_unit_device(relay, crypto=CRYPTO, keyring=None)
        with pytest.raises(VaultLockedError):
            await locked.service.host()
        paired = make_unit_device(relay, crypto=CRYPTO, keyring=CRYPTO.generate_keyring("vlt_unit"))
        with pytest.raises(PairingError) as already:
            await paired.service.join("K7Q2-MXR9-T4WA")
        assert already.value.code == "pairing_already_paired"
        with pytest.raises(PairingError) as invalid:
            await locked.service.join("not a code")
        assert invalid.value.code == "pairing_code_invalid"

    asyncio.run(scenario())


def test_bootstrapping_cannot_be_cancelled_and_terminal_sessions_are_dropped() -> None:
    async def scenario() -> None:
        relay = MemoryRelay()
        host = make_unit_device(relay, crypto=CRYPTO, keyring=CRYPTO.generate_keyring("vlt_unit"))
        guest = make_unit_device(
            relay, crypto=CRYPTO, keyring=None, timeouts=with_timeouts(UNIT, terminal_retention=0.05)
        )
        guest.vault.install_gate = asyncio.Event()
        hosted = await host.service.host()
        assert hosted.session.code is not None
        joined = await guest.service.join(hosted.session.code.format())
        await _until(lambda: host.service.get(hosted.session.id), PairingState.AWAITING_APPROVAL)
        await host.service.approve(hosted.session.id)
        await _until(lambda: guest.service.get(joined.session.id), PairingState.BOOTSTRAPPING)
        with pytest.raises(PairingError) as conflict:
            await guest.service.cancel(joined.session.id)
        assert conflict.value.code == "pairing_state_conflict"
        guest.vault.install_gate.set()
        await _until(lambda: guest.service.get(joined.session.id), PairingState.COMPLETED)
        await asyncio.sleep(0.1)
        with pytest.raises(PairingError) as dropped:
            await guest.service.get(joined.session.id)
        assert dropped.value.code == "pairing_not_found"
        await host.service.close()

    asyncio.run(scenario())


async def _raw_guest(relay: MemoryRelay, code: PairingCode):  # type: ignore[no-untyped-def]
    channel = await relay.open_room(code.nameplate, PairingRole.GUEST)
    crypto = PairingCryptoFactory().guest_session(code.password)
    await channel.send(crypto.start())
    crypto.finish(await channel.receive(1))
    await channel.send(crypto.confirmation())
    crypto.verify_peer_confirmation(await channel.receive(1))
    return channel, crypto


@pytest.mark.parametrize("attack", ["wrong_direction", "garbage_frame", "replayed_frame", "impersonation", "unknown_type"])
def test_hostile_guests_fail_the_host_session(attack: str) -> None:
    async def scenario() -> None:
        relay = MemoryRelay()
        host = make_unit_device(relay, crypto=CRYPTO, keyring=CRYPTO.generate_keyring("vlt_unit"))
        hosted = await host.service.host()
        assert hosted.session.code is not None
        channel, crypto = await _raw_guest(relay, hosted.session.code)
        identity = host.vault.identity if attack == "impersonation" else CRYPTO.generate_device_identity()
        join = join_request_message(
            identity, name="Intruso", platform=DevicePlatform.LINUX, app_version="1", login_token=None
        )
        if attack == "wrong_direction":
            await channel.send(crypto.encrypt_message({"type": "vault_grant", "vault_id": "vlt_x", "layout": {}}))
        elif attack == "garbage_frame":
            await channel.send(b"\x03" + bytes(40))
        elif attack == "replayed_frame":
            frame = crypto.encrypt_message(join)
            await channel.send(frame)
            await _until(lambda: host.service.get(hosted.session.id), PairingState.AWAITING_APPROVAL)
            await channel.send(frame)
        elif attack == "unknown_type":
            await channel.send(crypto.encrypt_message(join))
            await _until(lambda: host.service.get(hosted.session.id), PairingState.AWAITING_APPROVAL)
            await channel.send(crypto.encrypt_message({"type": "give_me_everything"}))
        else:
            await channel.send(crypto.encrypt_message(join))
        failed = await _until(lambda: host.service.get(hosted.session.id), PairingState.FAILED)
        assert failed.session.error_code == "pairing_protocol"
        assert host.devices.items == {}
        assert not any(frame[0] == 0x03 and len(frame) > 200 for frame in relay.rooms[hosted.session.code.nameplate].host.sent)  # type: ignore[union-attr]

    asyncio.run(scenario())


def test_host_falls_back_when_the_login_token_keeps_expiring() -> None:
    async def scenario() -> None:
        relay = MemoryRelay()
        host = make_unit_device(relay, crypto=CRYPTO, keyring=CRYPTO.generate_keyring("vlt_unit"))
        guest = make_unit_device(relay, crypto=CRYPTO, keyring=None, authorized=False)
        host.account.accept_error = TelegramAccountError("telegram_login_expired", "expired")
        host.account.on_accept = lambda _token: guest.account.rotate_token()
        hosted = await host.service.host()
        assert hosted.session.code is not None
        joined = await guest.service.join(hosted.session.code.format())
        await _until(lambda: host.service.get(hosted.session.id), PairingState.AWAITING_APPROVAL)
        await host.service.approve(hosted.session.id)
        needs = await _until(lambda: guest.service.get(joined.session.id), PairingState.NEEDS_TELEGRAM_LOGIN)
        assert needs.telegram_login_url is not None
        assert host.account.accepted == [b"token-0", b"token-1", b"token-2"]
        guest.account.authorized = True  # the user scanned the guest's own QR with the phone
        await _until(lambda: guest.service.get(joined.session.id), PairingState.COMPLETED)
        await _until(lambda: host.service.get(hosted.session.id), PairingState.COMPLETED)
        assert host.devices.items[guest.vault.identity.device_id].telegram_auth_hash is None
        assert b64url_encode(guest.vault.identity.public_key) == host.devices.items[guest.vault.identity.device_id].public_key

    asyncio.run(scenario())


def test_codes_sas_tokens_and_keys_are_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    for name in ("bento.pairing", "bento.pairing.relay", "bento.devices"):
        logging.getLogger(name).disabled = False
    caplog.set_level(logging.DEBUG)

    async def scenario() -> list[str]:
        relay = MemoryRelay()
        host = make_unit_device(relay, crypto=CRYPTO, keyring=CRYPTO.generate_keyring("vlt_unit"))
        guest = make_unit_device(relay, crypto=CRYPTO, keyring=None, authorized=False)
        host.account.on_accept = lambda _token: setattr(guest.account, "authorized", True)
        hosted = await host.service.host()
        assert hosted.session.code is not None
        joined = await guest.service.join(hosted.session.code.format())
        waiting = await _until(lambda: host.service.get(hosted.session.id), PairingState.AWAITING_APPROVAL)
        await host.service.approve(hosted.session.id)
        await _until(lambda: guest.service.get(joined.session.id), PairingState.COMPLETED)
        assert host.vault.keyring is not None
        secrets = [hosted.session.code.format(), hosted.session.code.secret, hosted.session.code.nameplate]
        secrets += list(waiting.session.sas or ())
        secrets += [token.decode() for token in host.account.accepted]
        secrets += [b64url_encode(key) for key in host.vault.keyring.keys.values()]
        secrets += [b64url_encode(guest.vault.identity.private_key), b64url_encode(guest.vault.identity.public_key)]
        return secrets

    secrets = asyncio.run(scenario())
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "awaiting_approval" in text, "pairing events are logged"
    for secret in secrets:
        assert secret not in text
