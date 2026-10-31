from __future__ import annotations

import pytest

from bento.adapters.pairing.frames import (
    RelayFrameError,
    RelayFrameType,
    health_url,
    normalize_relay_url,
    pairing_error_code,
    parse_control_frame,
    room_url,
)
from bento.domain.pairing import PairingRole


def test_parse_control_frames() -> None:
    welcome = parse_control_frame('{"type":"welcome","role":"guest","expires_at":"2026-10-31T12:10:00.000Z"}')
    assert welcome.type is RelayFrameType.WELCOME and welcome.role is PairingRole.GUEST
    assert welcome.expires_at is not None and welcome.expires_at.utcoffset() is not None
    assert parse_control_frame('{"type":"peer_joined"}').type is RelayFrameType.PEER_JOINED
    assert parse_control_frame('{"type":"peer_left"}').type is RelayFrameType.PEER_LEFT
    assert parse_control_frame('{"type":"error","code":"room_full"}').code == "room_full"
    assert parse_control_frame('{"type":"closed","reason":"burned"}').reason == "burned"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        '{"type":"surprise"}',
        '{"type":"welcome","role":"admin","expires_at":"2026-10-31T12:10:00Z"}',
        '{"type":"welcome","role":"host","expires_at":"2026-10-31T12:10:00"}',
        '{"type":"error"}',
        '{"type":"closed","reason":4}',
        '{"type":"peer_left","pad":"' + "x" * 2048 + '"}',
    ],
)
def test_parse_control_frame_rejects_malformed_frames(text: str) -> None:
    with pytest.raises(RelayFrameError):
        parse_control_frame(text)


def test_relay_error_codes_map_to_pairing_codes() -> None:
    assert pairing_error_code("nameplate_taken") == "pairing_nameplate_taken"
    assert pairing_error_code("room_not_found") == "pairing_room_not_found"
    assert pairing_error_code("room_full") == "pairing_room_full"
    assert pairing_error_code("expired") == "pairing_expired"
    assert pairing_error_code("rate_limited") == "pairing_rate_limited"
    assert pairing_error_code("message_too_large") == "pairing_protocol"
    assert pairing_error_code("anything else") == "pairing_protocol"
    assert pairing_error_code(None) == "pairing_protocol"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ""),
        ("  ", ""),
        ("wss://bento-relay.example.workers.dev", "wss://bento-relay.example.workers.dev"),
        ("wss://bento-relay.example.workers.dev/", "wss://bento-relay.example.workers.dev"),
        ("wss://relay.example:8443/base/", "wss://relay.example:8443/base"),
        ("ws://127.0.0.1:8787", "ws://127.0.0.1:8787"),
        ("ws://localhost:8787/", "ws://localhost:8787"),
        ("ws://[::1]:8787", "ws://[::1]:8787"),
    ],
)
def test_normalize_relay_url_accepts_wss_and_loopback_ws(value: str, expected: str) -> None:
    assert normalize_relay_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "ws://relay.example.com",
        "ws://192.168.1.20:8787",
        "ws://127.0.0.1.example.com",
        "https://relay.example.com",
        "http://127.0.0.1:8787",
        "relay.example.com",
        "wss://",
        "wss://user:secret@relay.example.com",
        "wss://relay.example.com?x=1",
        "wss://relay.example.com#frag",
        "wss://relay.example.com:99999",
    ],
)
def test_normalize_relay_url_rejects_everything_else(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_relay_url(value)


def test_room_and_health_urls() -> None:
    assert room_url("wss://relay.example", "K7Q2", PairingRole.HOST) == "wss://relay.example/v1/rooms/K7Q2?role=host"
    assert room_url("ws://127.0.0.1:8787", "0Z9A", PairingRole.GUEST) == "ws://127.0.0.1:8787/v1/rooms/0Z9A?role=guest"
    for invalid in ("k7q2", "K7Q", "K7QU", "K7QI", "K7Q2X", "../a"):
        with pytest.raises(ValueError):
            room_url("wss://relay.example", invalid, PairingRole.HOST)
    assert health_url("wss://relay.example") == "https://relay.example/v1/health"
    assert health_url("ws://127.0.0.1:8787") == "http://127.0.0.1:8787/v1/health"
