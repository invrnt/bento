"""Validation of relay application messages, fallback messages, codes, and encodings."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from bento.application.pairing import (
    MAX_LOGIN_TOKEN_BYTES,
    FallbackKind,
    MessageType,
    b64url_decode,
    b64url_encode,
    decode_public_key,
    generate_pairing_code,
    normalize_device_name,
    parse_fallback_message,
    parse_peer_message,
)
from bento.domain.devices import DevicePlatform
from bento.domain.errors import ValidationFailedError
from bento.domain.pairing import CROCKFORD_ALPHABET, PairingCode, PairingError, PairingRole

KEY = b64url_encode(bytes(range(32)))
NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)


def _join(**changes: Any) -> dict[str, Any]:
    message: dict[str, Any] = {
        "type": "join_request",
        "device_id": "dev_" + "a" * 32,
        "device_name": "Portátil · Linux",
        "platform": "linux",
        "public_key": KEY,
        "app_version": "0.1.0",
        "telegram": {"authorized": False, "login_token_b64": b64url_encode(b"token")},
    }
    message.update(changes)
    return message


def _protocol_error(payload: Any, sender: PairingRole = PairingRole.GUEST) -> None:
    with pytest.raises(PairingError) as error:
        parse_peer_message(payload, sender=sender)
    assert error.value.code == "pairing_protocol"


def test_join_request_is_parsed() -> None:
    message = parse_peer_message(_join(extra="ignored"), sender=PairingRole.GUEST)
    assert message.type is MessageType.JOIN_REQUEST and message.join is not None
    assert message.join.device_name == "Portátil · Linux"
    assert message.join.platform is DevicePlatform.LINUX
    assert message.join.public_key == bytes(range(32))
    assert message.join.login_token == b"token" and not message.join.telegram_authorized
    signed_in = parse_peer_message(_join(telegram={"authorized": True}, platform="beos"), sender=PairingRole.GUEST)
    assert signed_in.join is not None and signed_in.join.login_token is None
    assert signed_in.join.platform is DevicePlatform.OTHER


@pytest.mark.parametrize(
    "payload",
    [
        _join(device_id="device_1"),
        _join(device_id="dev_" + "a" * 70),
        _join(device_id=5),
        _join(device_name=""),
        _join(device_name="   "),
        _join(device_name="x" * 65),
        _join(device_name="evil‮name"),
        _join(device_name="bell\x07"),
        _join(device_name=["list"]),
        _join(public_key=b64url_encode(bytes(31))),
        _join(public_key="not base64!"),
        _join(public_key=KEY + "==="),
        _join(app_version="x" * 33),
        _join(telegram={"authorized": "yes"}),
        _join(telegram="authorized"),
        _join(telegram={"authorized": False}),
        _join(telegram={"authorized": False, "login_token_b64": ""}),
        _join(telegram={"authorized": False, "login_token_b64": b64url_encode(bytes(MAX_LOGIN_TOKEN_BYTES + 1))}),
    ],
)
def test_hostile_join_requests_are_protocol_errors(payload: dict[str, Any]) -> None:
    _protocol_error(payload)


@pytest.mark.parametrize(
    ("payload", "sender"),
    [
        ({}, PairingRole.GUEST),
        ({"type": None}, PairingRole.GUEST),
        ({"type": "launch_missiles"}, PairingRole.GUEST),
        ({"type": "vault_grant"}, PairingRole.GUEST),
        ({"type": "join_request"}, PairingRole.HOST),
        ({"type": "rejected"}, PairingRole.GUEST),
        ({"type": "done"}, PairingRole.HOST),
        ({"type": ["login_token"]}, PairingRole.GUEST),
    ],
)
def test_unknown_or_misdirected_types_are_rejected(payload: dict[str, Any], sender: PairingRole) -> None:
    _protocol_error(payload, sender)


def _grant(**changes: Any) -> dict[str, Any]:
    message: dict[str, Any] = {
        "type": "vault_grant",
        "vault_id": "vlt_abc",
        "layout": {"files": -1001, "sync": -1002, "inbox": -1003},
        "sealed_keyring": b64url_encode(b"sealed"),
    }
    message.update(changes)
    return message


def test_vault_grant_is_parsed_and_validated() -> None:
    grant = parse_peer_message(_grant(), sender=PairingRole.HOST).grant
    assert grant is not None and grant.layout.sync_channel_id == -1002 and grant.sealed_keyring == b"sealed"
    for hostile in (
        _grant(vault_id="vault"),
        _grant(vault_id="vlt_../../x"),
        _grant(layout={"files": True, "sync": -1002, "inbox": -1003}),
        _grant(layout={"files": "1", "sync": -1002, "inbox": -1003}),
        _grant(layout={"files": 0, "sync": -1002, "inbox": -1003}),
        _grant(layout={"files": 1 << 70, "sync": -1002, "inbox": -1003}),
        _grant(layout=[1, 2, 3]),
        _grant(sealed_keyring=b64url_encode(bytes(48 * 1024 + 1))),
        _grant(sealed_keyring=None),
    ):
        _protocol_error(hostile, PairingRole.HOST)


def test_other_messages() -> None:
    token = parse_peer_message({"type": "login_token", "login_token_b64": b64url_encode(b"t2")}, sender=PairingRole.GUEST)
    assert token.login_token == b"t2"
    _protocol_error({"type": "login_token"})
    failed = parse_peer_message({"type": "telegram_login_failed", "reason": "telegram_network"}, sender=PairingRole.HOST)
    assert failed.reason == "telegram_network"
    odd = parse_peer_message({"type": "telegram_login_failed", "reason": "<script>"}, sender=PairingRole.HOST)
    assert odd.reason == "unknown"
    assert parse_peer_message({"type": "done"}, sender=PairingRole.GUEST).type is MessageType.DONE


def test_fallback_messages_are_parsed_or_ignored() -> None:
    request_id = "r" * 32
    request = parse_fallback_message(
        '{"bento":"pair_request","v":1,"request_id":"%s","device_id":"dev_%s","device_name":"Nuevo","platform":"macos",'
        '"public_key":"%s","commitment":"%s"}' % (request_id, "b" * 32, KEY, b64url_encode(bytes(32))),
        message_id=7,
        created_at=NOW,
    )
    assert request is not None and request.kind is FallbackKind.REQUEST and request.request is not None
    assert request.request.platform is DevicePlatform.MACOS and request.request.message_id == 7
    reveal = parse_fallback_message(
        '{"bento":"pair_reveal","v":1,"request_id":"%s","eph_pub":"%s","offer":"%s"}' % (request_id, KEY, KEY),
        message_id=9,
        created_at=NOW,
    )
    assert reveal is not None and reveal.eph_pub == bytes(range(32)) and reveal.offer_eph_pub == bytes(range(32))
    grant = parse_fallback_message(
        '{"bento":"pair_grant","v":1,"request_id":"%s","grant":"%s"}' % (request_id, b64url_encode(bytes(60))),
        message_id=11,
        created_at=NOW,
    )
    assert grant is not None and grant.kind is FallbackKind.GRANT and grant.grant == bytes(60)
    for junk in (
        '{"bento":"pair_grant","v":1,"request_id":"%s","sealed_keyring":"%s"}' % (request_id, KEY),
        '{"bento":"pair_grant","v":1,"request_id":"%s","grant":""}' % request_id,
        '{"bento":"pair_grant","v":1,"request_id":"%s","grant":"%s"}' % (request_id, b64url_encode(bytes(48 * 1024 + 29))),
        "",
        "plain text",
        "[1]",
        '{"bento":"pair_request","v":2,"request_id":"%s"}' % request_id,
        '{"bento":"pair_offer","v":1,"request_id":"short","eph_pub":"%s"}' % KEY,
        '{"bento":"pair_offer","v":1,"request_id":"%s","eph_pub":"AAAA"}' % request_id,
        '{"bento":"pair_grant","v":1,"request_id":"%s"}' % request_id,
        '{"bento":"vault-header","v":1,"request_id":"%s"}' % request_id,
        '{"bento":"pair_request","v":1,"request_id":"%s","device_id":"dev_x","device_name":"","platform":"linux",'
        '"public_key":"%s","commitment":"%s"}' % (request_id, KEY, KEY),
        "x" * (64 * 1024 + 1),
    ):
        assert parse_fallback_message(junk, message_id=1, created_at=NOW) is None


def test_generated_codes_use_the_unambiguous_alphabet() -> None:
    codes = {generate_pairing_code().format() for _ in range(500)}
    assert len(codes) == 500
    for text in codes:
        nameplate, first, second = text.split("-")
        assert len(nameplate) == len(first) == len(second) == 4
        assert set(nameplate + first + second) <= set(CROCKFORD_ALPHABET)
        assert not set(text) & set("ILOU")
        assert PairingCode.parse(text).format() == text
        assert PairingCode.parse(PairingCode.parse(text).link()).format() == text
    assert PairingCode.parse("https://bento.example/join/#v=1&c=K7Q2-MXR9-T4WA").format() == "K7Q2-MXR9-T4WA"


def test_base64url_and_names() -> None:
    assert b64url_decode(b64url_encode(b"\xff\x00"), max_bytes=2) == b"\xff\x00"
    for bad in ("a", "a+b/", "abc$", 3, None, "A" * 100):
        with pytest.raises(ValidationFailedError):
            b64url_decode(bad, max_bytes=8)
    with pytest.raises(ValidationFailedError):
        decode_public_key(b64url_encode(bytes(33)))
    assert normalize_device_name("  Mi\tPortátil  ") == "Mi Portátil"
    with pytest.raises(ValidationFailedError):
        normalize_device_name("​zero-width")
