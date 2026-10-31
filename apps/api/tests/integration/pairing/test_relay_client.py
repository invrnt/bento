"""`WebSocketPairingRelay` against the relay double (pairing-relay-contract behaviors)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from bento.adapters.pairing import WebSocketPairingRelay
from bento.adapters.pairing.frames import MAX_FRAME_BYTES, MAX_FRAMES_PER_SIDE
from bento.domain.errors import ValidationFailedError
from bento.domain.pairing import PairingError, PairingRole
from tests.integration.pairing.relay_double import RelayDouble

Scenario = Callable[[RelayDouble, WebSocketPairingRelay], Awaitable[None]]


def _run(scenario: Scenario, **relay_options: object) -> None:
    async def main() -> None:
        relay = RelayDouble(**relay_options)  # type: ignore[arg-type]
        url = await relay.start()
        try:
            await scenario(relay, WebSocketPairingRelay(url, open_timeout=5.0))
        finally:
            await relay.stop()

    asyncio.run(main())


def test_host_and_guest_exchange_binary_frames_both_ways() -> None:
    async def scenario(relay: RelayDouble, client: WebSocketPairingRelay) -> None:
        host = await client.open_room("K7Q2", PairingRole.HOST)
        assert host.expires_at is not None
        assert await host.wait_for_peer(0.05) is False
        guest = await client.open_room("K7Q2", PairingRole.GUEST)
        assert await guest.wait_for_peer(1) is True
        assert await host.wait_for_peer(1) is True

        await host.send(b"\x01hello")
        assert await guest.receive(1) == b"\x01hello"
        await guest.send(b"\x02" + bytes(range(256)) * 4)
        assert await host.receive(1) == b"\x02" + bytes(range(256)) * 4
        with pytest.raises(PairingError) as timeout:
            await host.receive(0.05)
        assert timeout.value.code == "pairing_timeout"

        await guest.send(b"\x03last")
        await guest.close()
        assert await host.receive(1) == b"\x03last", "frames sent before the peer left are delivered first"
        with pytest.raises(PairingError) as left:
            await host.receive(1)
        assert left.value.code == "pairing_peer_left"
        with pytest.raises(PairingError):
            await host.receive(0.01)
        assert relay.rooms["K7Q2"].burned
        assert relay.text_frames_seen == ['{"type":"close"}']
        await host.close()
        await guest.close()

    _run(scenario)


def test_room_errors_map_to_pairing_codes() -> None:
    async def scenario(relay: RelayDouble, client: WebSocketPairingRelay) -> None:
        with pytest.raises(PairingError) as missing:
            await client.open_room("ABCD", PairingRole.GUEST)
        assert missing.value.code == "pairing_room_not_found"

        host = await client.open_room("ABCD", PairingRole.HOST)
        with pytest.raises(PairingError) as taken:
            await client.open_room("ABCD", PairingRole.HOST)
        assert taken.value.code == "pairing_nameplate_taken"

        guest = await client.open_room("ABCD", PairingRole.GUEST)
        with pytest.raises(PairingError) as full:
            await client.open_room("ABCD", PairingRole.GUEST)
        assert full.value.code == "pairing_room_full"
        await guest.close()
        await host.close()
        with pytest.raises(PairingError) as burned:
            await client.open_room("ABCD", PairingRole.GUEST)
        assert burned.value.code == "pairing_room_full"
        with pytest.raises(PairingError) as reused:
            await client.open_room("ABCD", PairingRole.HOST)
        assert reused.value.code == "pairing_nameplate_taken"

    _run(scenario)


def test_room_expiry_ends_both_sides() -> None:
    async def scenario(relay: RelayDouble, client: WebSocketPairingRelay) -> None:
        host = await client.open_room("EXP1", PairingRole.HOST)
        guest = await client.open_room("EXP1", PairingRole.GUEST)
        for channel in (host, guest):
            with pytest.raises(PairingError) as expired:
                await channel.receive(2)
            assert expired.value.code == "pairing_expired"
        lonely = await client.open_room("EXP2", PairingRole.HOST)
        with pytest.raises(PairingError) as waiting:
            await lonely.wait_for_peer(2)
        assert waiting.value.code == "pairing_expired"
        await host.close()
        await guest.close()
        await lonely.close()

    _run(scenario, ttl_seconds=0.3)


def test_frame_limits_are_enforced_before_sending() -> None:
    async def scenario(relay: RelayDouble, client: WebSocketPairingRelay) -> None:
        host = await client.open_room("MX01", PairingRole.HOST)
        with pytest.raises(PairingError) as early:
            await host.send(b"\x01too early")
        assert early.value.code == "pairing_protocol"
        guest = await client.open_room("MX01", PairingRole.GUEST)
        await host.wait_for_peer(1)
        with pytest.raises(ValidationFailedError):
            await host.send(b"x" * (MAX_FRAME_BYTES + 1))
        with pytest.raises(ValidationFailedError):
            await host.send(b"")
        await host.send(b"x" * MAX_FRAME_BYTES)
        assert len(await guest.receive(1)) == MAX_FRAME_BYTES
        for index in range(MAX_FRAMES_PER_SIDE - 1):
            await host.send(bytes([index % 256]))
        with pytest.raises(PairingError) as exhausted:
            await host.send(b"one too many")
        assert exhausted.value.code == "pairing_protocol"
        await host.close()
        await guest.close()

    _run(scenario)


def test_oversized_frame_from_the_peer_ends_the_room() -> None:
    async def scenario(relay: RelayDouble, client: WebSocketPairingRelay) -> None:
        host = await client.open_room("BG01", PairingRole.HOST)
        guest = await client.open_room("BG01", PairingRole.GUEST)
        await host.wait_for_peer(1)
        # Bypass the client-side guard: the relay answers with `message_too_large` and burns the room.
        await host._connection.send(b"x" * (MAX_FRAME_BYTES + 10))  # noqa: SLF001
        with pytest.raises(PairingError) as rejected:
            await host.receive(2)
        assert rejected.value.code == "pairing_protocol"
        with pytest.raises(PairingError) as left:
            await guest.receive(2)
        assert left.value.code == "pairing_peer_left"
        assert ("frame_rejected", "message_too_large") in relay.events
        await host.close()
        await guest.close()

    _run(scenario)


def test_rate_limit_and_unreachable_relay() -> None:
    async def scenario(relay: RelayDouble, client: WebSocketPairingRelay) -> None:
        first = await client.open_room("RT01", PairingRole.HOST)
        with pytest.raises(PairingError) as limited:
            await client.open_room("RT02", PairingRole.HOST)
        assert limited.value.code == "pairing_rate_limited"
        await first.close()

        unreachable = WebSocketPairingRelay("ws://127.0.0.1:9", open_timeout=1.0)
        with pytest.raises(PairingError) as down:
            await unreachable.open_room("RT03", PairingRole.HOST)
        assert down.value.code == "pairing_relay_unavailable"
        assert await unreachable.available() is False

    _run(scenario, rate_limit_per_minute=1)


def test_health_and_configuration() -> None:
    async def scenario(relay: RelayDouble, client: WebSocketPairingRelay) -> None:
        assert await client.available() is True
        disabled = WebSocketPairingRelay("")
        assert await disabled.available() is False
        with pytest.raises(PairingError) as off:
            await disabled.open_room("K7Q2", PairingRole.HOST)
        assert off.value.code == "pairing_relay_unavailable"
        assert off.value.details == {"reason": "relay_not_configured"}
        insecure = WebSocketPairingRelay("ws://relay.example.com")
        with pytest.raises(PairingError) as rejected:
            await insecure.open_room("K7Q2", PairingRole.HOST)
        assert rejected.value.details == {"reason": "relay_url_invalid"}
        with pytest.raises(ValidationFailedError):
            await client.open_room("k7q2", PairingRole.HOST)

    _run(scenario)
