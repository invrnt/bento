from __future__ import annotations

import unicodedata

import pytest

from bento.adapters.security import SAS_EMOJIS, PairingCryptoFactory, PairingCryptoSession, verify_commitment
from bento.adapters.security.pairing_crypto import MAX_FRAME_BYTES, sas_from_bits
from bento.domain.errors import IntegrityError, ValidationFailedError
from bento.domain.pairing import PairingCode
from tests.unit.security.crypto_support import DeterministicRandom, flip_bit

factory = PairingCryptoFactory()
PASSWORD = PairingCode.parse("K7Q2-MXR9-T4WA").password


def _handshake(
    host_password: bytes = PASSWORD, guest_password: bytes = PASSWORD
) -> tuple[PairingCryptoSession, PairingCryptoSession]:
    host = factory.host_session(host_password)
    guest = factory.guest_session(guest_password)
    host_hello, guest_hello = host.start(), guest.start()
    host.finish(guest_hello)
    guest.finish(host_hello)
    return host, guest


def _confirmed() -> tuple[PairingCryptoSession, PairingCryptoSession]:
    host, guest = _handshake()
    guest.verify_peer_confirmation(host.confirmation())
    host.verify_peer_confirmation(guest.confirmation())
    return host, guest


def test_same_code_yields_same_sas_and_confirmations() -> None:
    host, guest = _handshake()
    assert host.sas() == guest.sas()
    assert len(host.sas()) == 4 and all(emoji in SAS_EMOJIS for emoji in host.sas())
    host_confirmation, guest_confirmation = host.confirmation(), guest.confirmation()
    assert host_confirmation[0] == 0x02 and len(host_confirmation) == 33
    assert host_confirmation != guest_confirmation
    guest.verify_peer_confirmation(host_confirmation)
    host.verify_peer_confirmation(guest_confirmation)


def test_frames_carry_type_bytes() -> None:
    host = factory.host_session(PASSWORD)
    guest = factory.guest_session(PASSWORD)
    host_hello, guest_hello = host.start(), guest.start()
    assert host_hello[0] == guest_hello[0] == 0x01
    assert len(host_hello) == 1 + 33
    host.finish(guest_hello)
    guest.finish(host_hello)
    guest.verify_peer_confirmation(host.confirmation())
    host.verify_peer_confirmation(guest.confirmation())
    frame = guest.encrypt_message({"type": "join_request"})
    assert frame[0] == 0x03
    assert host.decrypt_message(frame) == {"type": "join_request"}


def test_different_code_fails_confirmation_on_both_sides() -> None:
    other = PairingCode.parse("K7Q2-MXR9-T4WB").password
    host, guest = _handshake(PASSWORD, other)
    host_confirmation, guest_confirmation = host.confirmation(), guest.confirmation()
    with pytest.raises(IntegrityError):
        guest.verify_peer_confirmation(host_confirmation)
    with pytest.raises(IntegrityError):
        host.verify_peer_confirmation(guest_confirmation)
    with pytest.raises(IntegrityError):
        host.sas()
    with pytest.raises(IntegrityError):
        guest.encrypt_message({"type": "join_request"})


def test_reflected_confirmation_is_rejected() -> None:
    host, _guest = _handshake()
    with pytest.raises(IntegrityError):
        host.verify_peer_confirmation(host.confirmation())


def test_confirmation_tampering_is_rejected() -> None:
    host, guest = _handshake()
    confirmation = host.confirmation()
    for bit in (0, 9, 100, 263):
        _host, fresh_guest = _handshake()
        with pytest.raises(IntegrityError):
            fresh_guest.verify_peer_confirmation(flip_bit(confirmation, bit))
    with pytest.raises(IntegrityError):
        guest.verify_peer_confirmation(confirmation[:-1])


def test_messages_round_trip_in_both_directions_with_counters() -> None:
    host, guest = _confirmed()
    messages = [{"type": "join_request", "device_name": "Portátil · Linux", "n": index} for index in range(5)]
    frames = [guest.encrypt_message(message) for message in messages]
    assert len(set(frames)) == len(frames)
    assert [host.decrypt_message(frame) for frame in frames] == messages
    reply = host.encrypt_message({"type": "vault_grant", "vault_id": "vlt_1"})
    assert guest.decrypt_message(reply) == {"type": "vault_grant", "vault_id": "vlt_1"}


def test_replayed_frame_is_rejected_and_session_fails_closed() -> None:
    host, guest = _confirmed()
    frame = guest.encrypt_message({"type": "join_request"})
    assert host.decrypt_message(frame) == {"type": "join_request"}
    with pytest.raises(IntegrityError):
        host.decrypt_message(frame)
    with pytest.raises(IntegrityError):
        host.decrypt_message(guest.encrypt_message({"type": "done"}))
    with pytest.raises(IntegrityError):
        host.encrypt_message({"type": "anything"})
    assert "failed" in repr(host)


def test_reordered_frames_are_rejected() -> None:
    host, guest = _confirmed()
    first = guest.encrypt_message({"n": 1})
    second = guest.encrypt_message({"n": 2})
    with pytest.raises(IntegrityError):
        host.decrypt_message(second)
    with pytest.raises(IntegrityError):
        host.decrypt_message(first)


def test_reflected_and_tampered_frames_are_rejected() -> None:
    host, guest = _confirmed()
    own = host.encrypt_message({"type": "vault_grant"})
    with pytest.raises(IntegrityError):
        host.decrypt_message(own)
    for bit in range(0, len(own) * 8, 7):
        fresh_host, fresh_guest = _confirmed()
        frame = fresh_host.encrypt_message({"type": "vault_grant"})
        with pytest.raises(IntegrityError):
            fresh_guest.decrypt_message(flip_bit(frame, bit))
    _host, fresh_guest = _confirmed()
    with pytest.raises(IntegrityError):
        fresh_guest.decrypt_message(b"\x03" + bytes(10))


def test_non_object_payloads_are_rejected() -> None:
    host, _guest = _confirmed()
    with pytest.raises(ValidationFailedError):
        host.encrypt_message(["not", "an", "object"])  # type: ignore[arg-type]
    with pytest.raises(ValidationFailedError):
        host.encrypt_message({"x": object()})


def test_oversized_message_is_rejected_before_counter_advances() -> None:
    host, guest = _confirmed()
    with pytest.raises(ValidationFailedError):
        host.encrypt_message({"blob": "x" * MAX_FRAME_BYTES})
    largest = {"blob": "x" * (MAX_FRAME_BYTES - 17 - len('{"blob":""}'))}
    frame = host.encrypt_message(largest)
    assert len(frame) == MAX_FRAME_BYTES
    assert guest.decrypt_message(frame) == largest


def test_state_machine_misuse_is_rejected() -> None:
    session = factory.host_session(PASSWORD)
    with pytest.raises(ValidationFailedError):
        session.finish(b"\x01" + bytes(33))
    with pytest.raises(ValidationFailedError):
        session.confirmation()
    with pytest.raises(ValidationFailedError):
        session.sas()
    session.start()
    with pytest.raises(ValidationFailedError):
        session.start()
    with pytest.raises(ValidationFailedError):
        session.encrypt_message({})
    guest = factory.guest_session(PASSWORD)
    session.finish(guest.start())
    with pytest.raises(ValidationFailedError):
        session.encrypt_message({"type": "x"})
    with pytest.raises(ValidationFailedError):
        session.decrypt_message(b"\x03" + bytes(17))
    with pytest.raises(ValidationFailedError):
        session.finish(guest.start())
    with pytest.raises(ValidationFailedError):
        factory.host_session(b"")


@pytest.mark.parametrize(
    "frame",
    [b"", b"\x01", b"\x02" + bytes(33), b"\x01" + bytes(33), b"\x01garbage", b"\x01A" + b"\xff" * 32, b"\x01A"],
)
def test_bad_spake2_frames_fail_closed(frame: bytes) -> None:
    session = factory.guest_session(PASSWORD)
    session.start()
    with pytest.raises(IntegrityError):
        session.finish(frame)
    with pytest.raises(IntegrityError):
        session.confirmation()


def test_same_side_message_is_rejected() -> None:
    first = factory.host_session(PASSWORD)
    second = factory.host_session(PASSWORD)
    first.start()
    with pytest.raises(IntegrityError):
        first.finish(second.start())


def test_sas_emoji_list_is_fixed_distinct_and_safe() -> None:
    assert len(SAS_EMOJIS) == 64
    assert len(set(SAS_EMOJIS)) == 64
    for emoji in SAS_EMOJIS:
        assert len(emoji) == 1, emoji
        code_point = ord(emoji)
        assert code_point != 0xFE0F
        assert not 0x1F1E6 <= code_point <= 0x1F1FF, "regional indicator / flag"
        assert not 0x1F3FB <= code_point <= 0x1F3FF, "skin tone modifier"
        assert unicodedata.category(emoji) == "So"
        assert unicodedata.name(emoji)
    assert sas_from_bits(b"\x00\x00\x00") == (SAS_EMOJIS[0],) * 4
    assert sas_from_bits(b"\xff\xff\xff") == (SAS_EMOJIS[63],) * 4
    assert sas_from_bits(bytes((0b00000100, 0b00100000, 0b11000100))) == (
        SAS_EMOJIS[1],
        SAS_EMOJIS[2],
        SAS_EMOJIS[3],
        SAS_EMOJIS[4],
    )
    with pytest.raises(ValidationFailedError):
        sas_from_bits(b"\x00")


GUEST_DEVICE_KEY = bytes(range(1, 33))
REQUEST_ID = "req_7f3a"


def _transcript(guest_eph: bytes, host_eph: bytes, **overrides: object) -> dict[str, object]:
    transcript: dict[str, object] = {
        "request_id": REQUEST_ID,
        "guest_device_public_key": GUEST_DEVICE_KEY,
        "guest_ephemeral_public_key": guest_eph,
        "host_ephemeral_public_key": host_eph,
    }
    transcript.update(overrides)
    return transcript


def test_fallback_commit_then_reveal_flow_agrees_on_sas() -> None:
    guest, host = factory.fallback_keys(), factory.fallback_keys()
    commitment = guest.commitment(device_public_key=GUEST_DEVICE_KEY, request_id=REQUEST_ID)
    assert len(commitment) == 43 and "=" not in commitment
    # Host offers its ephemeral key, then the guest reveals and the host checks the commitment.
    assert verify_commitment(
        commitment, eph_pub=guest.public_key(), device_public_key=GUEST_DEVICE_KEY, request_id=REQUEST_ID
    )
    transcript = _transcript(guest.public_key(), host.public_key())
    guest_sas = guest.sas_with(host.public_key(), **transcript)  # type: ignore[arg-type]
    host_sas = host.sas_with(guest.public_key(), **transcript)  # type: ignore[arg-type]
    assert guest_sas == host_sas
    assert len(guest_sas) == 4 and all(emoji in SAS_EMOJIS for emoji in guest_sas)


def test_commitment_binds_every_input() -> None:
    guest, other = factory.fallback_keys(), factory.fallback_keys()
    commitment = guest.commitment(device_public_key=GUEST_DEVICE_KEY, request_id=REQUEST_ID)
    good = {"eph_pub": guest.public_key(), "device_public_key": GUEST_DEVICE_KEY, "request_id": REQUEST_ID}
    assert verify_commitment(commitment, **good)  # type: ignore[arg-type]
    for field, value in (
        ("eph_pub", other.public_key()),
        ("device_public_key", bytes(range(2, 34))),
        ("request_id", "req_7f3b"),
        ("eph_pub", b"short"),
        ("request_id", ""),
    ):
        assert not verify_commitment(commitment, **{**good, field: value})  # type: ignore[arg-type]
    for bad in ("", commitment + "A", commitment[:-1], commitment[:-1] + ("A" if commitment[-1] != "A" else "B")):
        assert not verify_commitment(bad, **good)  # type: ignore[arg-type]
    assert not verify_commitment("ñ" * 43, **good)  # type: ignore[arg-type]
    assert not verify_commitment(None, **good)  # type: ignore[arg-type]
    with pytest.raises(ValidationFailedError):
        guest.commitment(device_public_key=b"short", request_id=REQUEST_ID)
    with pytest.raises(ValidationFailedError):
        guest.commitment(device_public_key=GUEST_DEVICE_KEY, request_id="")


def test_fallback_sas_binds_the_transcript() -> None:
    deterministic = PairingCryptoFactory(random_bytes=DeterministicRandom(b"fallback-transcript"))
    guest, host = deterministic.fallback_keys(), deterministic.fallback_keys()
    base = _transcript(guest.public_key(), host.public_key())
    reference = host.sas_with(guest.public_key(), **base)  # type: ignore[arg-type]
    for override in ({"request_id": "req_other"}, {"guest_device_public_key": bytes(range(2, 34))}):
        assert host.sas_with(guest.public_key(), **{**base, **override}) != reference  # type: ignore[arg-type]
    intruder = deterministic.fallback_keys()
    swapped = _transcript(intruder.public_key(), host.public_key())
    assert host.sas_with(intruder.public_key(), **swapped) != reference  # type: ignore[arg-type]
    roles_swapped = _transcript(host.public_key(), guest.public_key())
    assert host.sas_with(guest.public_key(), **roles_swapped) != reference  # type: ignore[arg-type]


def test_fallback_sas_rejects_inconsistent_or_invalid_transcripts() -> None:
    guest, host, intruder = factory.fallback_keys(), factory.fallback_keys(), factory.fallback_keys()
    transcript = _transcript(guest.public_key(), host.public_key())
    bad_calls = [
        (host, intruder.public_key(), transcript),
        (intruder, guest.public_key(), transcript),
        (host, guest.public_key(), _transcript(guest.public_key(), guest.public_key())),
        (host, guest.public_key(), {**transcript, "request_id": ""}),
        (host, guest.public_key(), {**transcript, "guest_device_public_key": b"short"}),
        (host, b"short", transcript),
        (host, bytes(32), _transcript(bytes(32), host.public_key())),
        (host, host.public_key(), transcript),
    ]
    for keys, peer, call_transcript in bad_calls:
        with pytest.raises(IntegrityError):
            keys.sas_with(peer, **call_transcript)  # type: ignore[arg-type]


def test_fallback_grant_key_agrees_and_is_separate_from_the_sas() -> None:
    guest, host = factory.fallback_keys(), factory.fallback_keys()
    transcript = _transcript(guest.public_key(), host.public_key())
    guest_key = guest.grant_key_with(host.public_key(), **transcript)  # type: ignore[arg-type]
    host_key = host.grant_key_with(guest.public_key(), **transcript)  # type: ignore[arg-type]
    assert guest_key == host_key and len(guest_key) == 32
    assert host.grant_key_with(guest.public_key(), **{**transcript, "request_id": "req_other"}) != host_key  # type: ignore[arg-type]
    intruder = factory.fallback_keys()
    assert intruder.grant_key_with(guest.public_key(), **_transcript(guest.public_key(), intruder.public_key())) != host_key  # type: ignore[arg-type]
    for keys, peer, call_transcript in (
        (host, intruder.public_key(), transcript),
        (intruder, guest.public_key(), transcript),
        (host, guest.public_key(), {**transcript, "request_id": ""}),
        (host, host.public_key(), transcript),
    ):
        with pytest.raises(IntegrityError):
            keys.grant_key_with(peer, **call_transcript)  # type: ignore[arg-type]


def test_fallback_grant_only_opens_for_the_sas_verified_host() -> None:
    guest, host, intruder = factory.fallback_keys(), factory.fallback_keys(), factory.fallback_keys()
    transcript = _transcript(guest.public_key(), host.public_key())
    grant = host.seal_grant(guest.public_key(), b"sealed keyring", **transcript)  # type: ignore[arg-type]
    assert guest.open_grant(host.public_key(), grant, **transcript) == b"sealed keyring"  # type: ignore[arg-type]
    assert host.seal_grant(guest.public_key(), b"sealed keyring", **transcript)[:12] != grant[:12]  # type: ignore[arg-type]

    # A channel writer knows every public value but neither ephemeral private key.
    forged = intruder.seal_grant(
        guest.public_key(), b"attacker keyring", **_transcript(guest.public_key(), intruder.public_key())  # type: ignore[arg-type]
    )
    tampered = (flip_bit(grant, 0), flip_bit(grant, 12 * 8), flip_bit(grant, len(grant) * 8 - 1))  # nonce, body, tag
    for bad in (forged, *tampered, grant[:20], b"", grant + b"x"):
        with pytest.raises(IntegrityError):
            guest.open_grant(host.public_key(), bad, **transcript)  # type: ignore[arg-type]
    with pytest.raises(IntegrityError):
        guest.open_grant(host.public_key(), grant, **{**transcript, "request_id": "req_other"})  # type: ignore[arg-type]
    with pytest.raises(ValidationFailedError):
        host.seal_grant(guest.public_key(), b"", **transcript)  # type: ignore[arg-type]


def test_reprs_hide_secrets() -> None:
    host, _guest = _confirmed()
    text = repr(host)
    assert text == "PairingCryptoSession(role=host, state=confirmed)"
    assert PASSWORD.decode() not in text
    assert repr(factory.fallback_keys()) == "FallbackPairingKeys()"
