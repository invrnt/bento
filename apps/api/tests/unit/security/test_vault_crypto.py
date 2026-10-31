from __future__ import annotations

import base64
import json
import re
import struct
import zlib

import pytest

from bento.adapters.security import VaultCrypto
from bento.adapters.security.primitives import b64url_encode, vault_subkey
from bento.adapters.security.vault_crypto import SEAL_PURPOSE_LABELS
from bento.domain.errors import IntegrityError, RecoveryCodeInvalidError, ValidationFailedError
from bento.domain.security import KeyPurpose, RecoveryWrap, SealPurpose, VaultKeyring
from bento.domain.vault import canonical_json
from tests.unit.security.crypto_support import DeterministicRandom, flip_bit

RECOVERY_FORMAT = re.compile(r"(?:[0-9A-HJKMNP-TV-Z]{4}-){8}[0-9A-HJKMNP-TV-Z]{4}")
crypto = VaultCrypto()


def _keyring() -> VaultKeyring:
    return VaultKeyring(vault_id="vlt_alpha", current_epoch=2, keys={1: b"\x01" * 32, 2: b"\x02" * 32})


# Keyring


def test_generate_and_rotate_keyring() -> None:
    keyring = crypto.generate_keyring("vlt_new")
    assert keyring.vault_id == "vlt_new"
    assert keyring.current_epoch == 1
    assert len(keyring.key()) == 32
    rotated = crypto.rotate_keyring(keyring)
    assert rotated.current_epoch == 2
    assert rotated.keys[1] == keyring.keys[1]
    assert rotated.keys[2] != keyring.keys[1]
    assert crypto.rotate_keyring(rotated).current_epoch == 3
    assert crypto.generate_keyring("vlt_new").key() != keyring.key()


def test_keyring_serialization_is_canonical_json() -> None:
    keyring = _keyring()
    payload = crypto.keyring_to_bytes(keyring)
    key1 = base64.urlsafe_b64encode(b"\x01" * 32).decode().rstrip("=")
    key2 = base64.urlsafe_b64encode(b"\x02" * 32).decode().rstrip("=")
    assert (
        payload
        == ('{"current_epoch":2,"keys":{"1":"' + key1 + '","2":"' + key2 + '"},"vault_id":"vlt_alpha"}').encode()
    )
    assert crypto.keyring_from_bytes(payload) == keyring


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not json",
        b"\xff\xfe",
        b"[]",
        b'{"vault_id":"v","current_epoch":1}',
        b'{"vault_id":"v","current_epoch":1,"keys":{"1":"AAAA"}}',
        b'{"vault_id":"v","current_epoch":true,"keys":{"1":"' + b64url_encode(bytes(32)).encode() + b'"}}',
        b'{"vault_id":"v","current_epoch":2,"keys":{"1":"' + b64url_encode(bytes(32)).encode() + b'"}}',
        b'{"vault_id":"v","current_epoch":1,"keys":{"01":"' + b64url_encode(bytes(32)).encode() + b'"}}',
        b'{"vault_id":"v","current_epoch":1,"keys":{"1":"' + b64url_encode(bytes(32)).encode() + b'*"}}',
        b'{"vault_id":"","current_epoch":1,"keys":{"1":"' + b64url_encode(bytes(32)).encode() + b'"}}',
        b'{"vault_id":"v","current_epoch":1,"keys":{"1":"' + b64url_encode(bytes(32)).encode() + b'"},"x":1}',
    ],
)
def test_keyring_parsing_rejects_malformed_input(payload: bytes) -> None:
    with pytest.raises(ValidationFailedError):
        crypto.keyring_from_bytes(payload)


def test_subkeys_are_separated_by_purpose_epoch_and_vault() -> None:
    keyring = _keyring()
    labels = [purpose.value for purpose in KeyPurpose] + ["pairing"]
    derived = {(label, epoch): vault_subkey(keyring, label, epoch) for label in labels for epoch in (1, 2)}
    assert len(set(derived.values())) == len(derived)
    other_vault = VaultKeyring(vault_id="vlt_beta", current_epoch=2, keys=keyring.keys)
    assert vault_subkey(other_vault, "sync", 2) != derived[("sync", 2)]
    assert set(SEAL_PURPOSE_LABELS) == set(SealPurpose)


# Envelopes


def test_envelope_round_trip_layout_and_aad() -> None:
    keyring = _keyring()
    envelope = crypto.seal(keyring, SealPurpose.SNAPSHOT, b"snapshot bytes", aad=b"context")
    magic, version, purpose, epoch, _nonce = struct.unpack(">4sBBI12s", envelope[:22])
    assert (magic, version, purpose, epoch) == (b"BENV", 1, 2, 2)
    assert len(envelope) == 22 + len(b"snapshot bytes") + 16
    assert crypto.open(keyring, SealPurpose.SNAPSHOT, envelope, aad=b"context") == b"snapshot bytes"
    assert crypto.seal(keyring, SealPurpose.SNAPSHOT, b"x") != crypto.seal(keyring, SealPurpose.SNAPSHOT, b"x")
    with pytest.raises(IntegrityError):
        crypto.open(keyring, SealPurpose.SNAPSHOT, envelope)
    with pytest.raises(IntegrityError):
        crypto.open(keyring, SealPurpose.SNAPSHOT, envelope, aad=b"other")


def test_envelope_purpose_mismatch_fails() -> None:
    keyring = _keyring()
    envelope = crypto.seal(keyring, SealPurpose.SYNC, b"ops")
    for purpose in (SealPurpose.SNAPSHOT, SealPurpose.DEVICE_RECORD, SealPurpose.PAIRING):
        with pytest.raises(IntegrityError):
            crypto.open(keyring, purpose, envelope)
    relabelled = envelope[:5] + bytes((SealPurpose.SNAPSHOT.value,)) + envelope[6:]
    with pytest.raises(IntegrityError):
        crypto.open(keyring, SealPurpose.SNAPSHOT, relabelled)


def test_envelope_epoch_mismatch_fails_and_old_epochs_open() -> None:
    keyring = _keyring()
    envelope = crypto.seal(keyring, SealPurpose.SYNC, b"ops")
    relabelled = envelope[:6] + struct.pack(">I", 1) + envelope[10:]
    with pytest.raises(IntegrityError):
        crypto.open(keyring, SealPurpose.SYNC, relabelled)
    only_epoch_one = VaultKeyring(vault_id="vlt_alpha", current_epoch=1, keys={1: b"\x01" * 32})
    with pytest.raises(IntegrityError) as missing:
        crypto.open(only_epoch_one, SealPurpose.SYNC, envelope)
    assert missing.value.details == {"what": "envelope_epoch"}
    old = crypto.seal(only_epoch_one, SealPurpose.SYNC, b"old ops")
    assert crypto.open(crypto.rotate_keyring(_keyring()), SealPurpose.SYNC, old) == b"old ops"
    other_vault = VaultKeyring(vault_id="vlt_beta", current_epoch=2, keys=_keyring().keys)
    with pytest.raises(IntegrityError):
        crypto.open(other_vault, SealPurpose.SYNC, envelope)


def test_every_envelope_bit_flip_and_truncation_fails() -> None:
    keyring = _keyring()
    envelope = crypto.seal(keyring, SealPurpose.DEVICE_RECORD, b"device record payload", aad=b"dev_1")
    for bit in range(len(envelope) * 8):
        with pytest.raises(IntegrityError):
            crypto.open(keyring, SealPurpose.DEVICE_RECORD, flip_bit(envelope, bit), aad=b"dev_1")
    for length in range(len(envelope)):
        with pytest.raises(IntegrityError):
            crypto.open(keyring, SealPurpose.DEVICE_RECORD, envelope[:length], aad=b"dev_1")
    with pytest.raises(IntegrityError):
        crypto.open(keyring, SealPurpose.DEVICE_RECORD, envelope + b"\x00", aad=b"dev_1")


def test_seal_json_round_trip_uses_zlib_canonical_json() -> None:
    keyring = _keyring()
    payload = {"bento": "sync-batch", "v": 1, "ops": [{"filename": "café ✓.jpg", "favorite": True}]}
    envelope = crypto.seal_json(keyring, SealPurpose.SYNC, payload, aad=b"batch")
    assert crypto.open_json(keyring, SealPurpose.SYNC, envelope, aad=b"batch") == payload
    inner = crypto.open(keyring, SealPurpose.SYNC, envelope, aad=b"batch")
    assert zlib.decompress(inner) == canonical_json(payload)
    with pytest.raises(ValidationFailedError):
        crypto.seal_json(keyring, SealPurpose.SYNC, {"bad": object()})


def test_open_json_rejects_bad_payloads_and_decompression_bombs() -> None:
    keyring = _keyring()
    small = VaultCrypto(max_json_bytes=1024)
    bomb = crypto.seal(keyring, SealPurpose.SNAPSHOT, zlib.compress(b"[" + b"0," * 10_000 + b"0]"))
    with pytest.raises(IntegrityError):
        small.open_json(keyring, SealPurpose.SNAPSHOT, bomb)
    assert len(crypto.open_json(keyring, SealPurpose.SNAPSHOT, bomb)) == 10_001
    for raw in (b"not zlib", zlib.compress(b"{not json"), zlib.compress(b"{}") + b"trailing"):
        with pytest.raises(IntegrityError):
            crypto.open_json(keyring, SealPurpose.SNAPSHOT, crypto.seal(keyring, SealPurpose.SNAPSHOT, raw))


# Header MAC


def test_header_mac_verifies_and_rejects_edits() -> None:
    keyring = _keyring()
    unsigned = canonical_json({"bento": "vault-header", "v": 1, "vault_id": "vlt_alpha", "current_epoch": 2})
    mac = crypto.header_mac(keyring, unsigned)
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", mac)
    assert crypto.verify_header_mac(keyring, unsigned, mac)
    edited = unsigned.replace(b'"current_epoch":2', b'"current_epoch":3')
    assert not crypto.verify_header_mac(keyring, edited, mac)
    assert not crypto.verify_header_mac(keyring, unsigned, None)
    assert not crypto.verify_header_mac(keyring, unsigned, "")
    assert not crypto.verify_header_mac(keyring, unsigned, mac + "=")
    assert not crypto.verify_header_mac(keyring, unsigned, mac[:-1] + ("A" if mac[-1] != "A" else "B"))
    assert not crypto.verify_header_mac(keyring, unsigned, "ñ" * 43)
    assert not crypto.verify_header_mac(crypto.rotate_keyring(keyring), unsigned, mac)
    other_vault = VaultKeyring(vault_id="vlt_beta", current_epoch=2, keys=keyring.keys)
    assert not crypto.verify_header_mac(other_vault, unsigned, mac)


# Recovery code


def test_recovery_code_format() -> None:
    codes = {crypto.generate_recovery_code() for _ in range(50)}
    assert len(codes) == 50
    for code in codes:
        assert RECOVERY_FORMAT.fullmatch(code), code
        assert len(code.split("-")) == 9
        assert crypto.normalize_recovery_code(code) == code


def test_recovery_code_normalization_aliases() -> None:
    code = _code_with_aliasable_chars()
    canonical = crypto.normalize_recovery_code(code)
    assert canonical == code
    variants = [
        code.lower(),
        code.replace("-", ""),
        code.replace("-", " "),
        "  " + code.replace("-", "  -  ") + "\n",
        code.replace("0", "O"),
        code.replace("0", "o"),
        code.replace("1", "I"),
        code.replace("1", "l"),
        code.replace("1", "L"),
        code.replace("-", "‑"),
    ]
    for variant in variants:
        assert crypto.normalize_recovery_code(variant) == canonical, variant


@pytest.mark.parametrize("mutation", ["checksum", "length", "chars", "type"])
def test_recovery_code_rejects_invalid_input(mutation: str) -> None:
    code = VaultCrypto(random_bytes=DeterministicRandom(b"recovery")).generate_recovery_code()
    if mutation == "checksum":
        last = code[-1]
        candidates = [
            code[:-1] + replacement for replacement in "0123456789ABCDEFGHJKMNPQRSTVWXYZ" if replacement != last
        ]
        for candidate in candidates:
            with pytest.raises(RecoveryCodeInvalidError):
                crypto.normalize_recovery_code(candidate)
        first = "1" if code[0] != "1" else "2"
        with pytest.raises(RecoveryCodeInvalidError):
            crypto.normalize_recovery_code(first + code[1:])
    elif mutation == "length":
        for candidate in (code[:-1], code + "0", "", code.replace("-", "")[:35]):
            with pytest.raises(RecoveryCodeInvalidError):
                crypto.normalize_recovery_code(candidate)
    elif mutation == "chars":
        for bad in ("U", "*", "é", "З", "ß"):
            with pytest.raises(RecoveryCodeInvalidError):
                crypto.normalize_recovery_code(bad + code[1:])
    else:
        with pytest.raises(RecoveryCodeInvalidError):
            crypto.normalize_recovery_code(None)  # type: ignore[arg-type]


def test_recovery_wrap_round_trip_and_wrong_code() -> None:
    keyring = _keyring()
    code = crypto.generate_recovery_code()
    wrap = crypto.wrap_for_recovery(keyring, code)
    assert wrap.alg == "hkdf-aesgcm-v1"
    assert len(base64.urlsafe_b64decode(wrap.nonce + "==")) == 12
    assert crypto.unwrap_with_recovery(wrap, code.lower().replace("-", " "), vault_id="vlt_alpha") == keyring

    with pytest.raises(RecoveryCodeInvalidError):
        crypto.unwrap_with_recovery(wrap, crypto.generate_recovery_code(), vault_id="vlt_alpha")
    with pytest.raises(RecoveryCodeInvalidError):
        crypto.unwrap_with_recovery(wrap, code, vault_id="vlt_other")
    with pytest.raises(RecoveryCodeInvalidError):
        crypto.unwrap_with_recovery(wrap, code[:-1] + ("0" if code[-1] != "0" else "1"), vault_id="vlt_alpha")
    tampered = RecoveryWrap(alg=wrap.alg, nonce=wrap.nonce, wrapped_keyring=_flip_b64(wrap.wrapped_keyring))
    with pytest.raises(RecoveryCodeInvalidError):
        crypto.unwrap_with_recovery(tampered, code, vault_id="vlt_alpha")
    for broken in (
        RecoveryWrap(alg=wrap.alg, nonce="***", wrapped_keyring=wrap.wrapped_keyring),
        RecoveryWrap(alg=wrap.alg, nonce=b64url_encode(b"short"), wrapped_keyring=wrap.wrapped_keyring),
        RecoveryWrap(alg=wrap.alg, nonce=wrap.nonce, wrapped_keyring=""),
    ):
        with pytest.raises(RecoveryCodeInvalidError):
            crypto.unwrap_with_recovery(broken, code, vault_id="vlt_alpha")
    with pytest.raises(ValidationFailedError):
        crypto.unwrap_with_recovery(
            RecoveryWrap(alg="other", nonce=wrap.nonce, wrapped_keyring=wrap.wrapped_keyring),
            code,
            vault_id="vlt_alpha",
        )
    with pytest.raises(RecoveryCodeInvalidError):
        crypto.wrap_for_recovery(keyring, "not a code")


# Device identity and sealed boxes


def test_device_identity_generation_and_serialization() -> None:
    identity = crypto.generate_device_identity()
    assert re.fullmatch(r"dev_[0-9a-f]{32}", identity.device_id)
    assert len(identity.private_key) == len(identity.public_key) == 32
    assert crypto.generate_device_identity().device_id != identity.device_id
    payload = crypto.device_identity_to_bytes(identity)
    assert json.loads(payload)["device_id"] == identity.device_id
    assert crypto.device_identity_from_bytes(payload) == identity


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"{}",
        b'{"v":2,"device_id":"dev_1","private_key":"' + b64url_encode(bytes(range(32))).encode() + b'"}',
        b'{"v":1,"device_id":"bad","private_key":"' + b64url_encode(bytes(range(32))).encode() + b'"}',
        b'{"v":1,"device_id":"dev_1","private_key":"' + b64url_encode(bytes(31)).encode() + b'"}',
        b'{"v":1,"device_id":"dev_1","private_key":"!!"}',
        b'{"v":1,"device_id":7,"private_key":"' + b64url_encode(bytes(range(32))).encode() + b'"}',
    ],
)
def test_device_identity_parsing_rejects_malformed_input(payload: bytes) -> None:
    with pytest.raises(ValidationFailedError):
        crypto.device_identity_from_bytes(payload)


def test_sealed_box_only_opens_with_right_identity_and_aad() -> None:
    recipient = crypto.generate_device_identity()
    stranger = crypto.generate_device_identity()
    sealed = crypto.seal_for_device(recipient.public_key, b"keyring json", aad=b"vlt_alpha")
    magic, version = sealed[:4], sealed[4]
    assert (magic, version) == (b"BBOX", 1)
    assert len(sealed) == 4 + 1 + 32 + 12 + len(b"keyring json") + 16
    assert crypto.open_sealed(recipient, sealed, aad=b"vlt_alpha") == b"keyring json"
    with pytest.raises(IntegrityError):
        crypto.open_sealed(stranger, sealed, aad=b"vlt_alpha")
    with pytest.raises(IntegrityError):
        crypto.open_sealed(recipient, sealed, aad=b"vlt_beta")
    with pytest.raises(IntegrityError):
        crypto.open_sealed(recipient, sealed)
    for bit in range(len(sealed) * 8):
        with pytest.raises(IntegrityError):
            crypto.open_sealed(recipient, flip_bit(sealed, bit), aad=b"vlt_alpha")
    for length in range(len(sealed)):
        with pytest.raises(IntegrityError):
            crypto.open_sealed(recipient, sealed[:length], aad=b"vlt_alpha")
    assert crypto.seal_for_device(recipient.public_key, b"x") != crypto.seal_for_device(recipient.public_key, b"x")


def test_sealed_box_rejects_invalid_keys() -> None:
    recipient = crypto.generate_device_identity()
    with pytest.raises(ValidationFailedError):
        crypto.seal_for_device(b"short", b"x")
    with pytest.raises(ValidationFailedError):
        crypto.seal_for_device(bytes(32), b"x")
    sealed = crypto.seal_for_device(recipient.public_key, b"x")
    low_order = sealed[:5] + bytes(32) + sealed[37:]
    with pytest.raises(IntegrityError):
        crypto.open_sealed(recipient, low_order)


# Keys grant authentication


def test_grant_auth_binds_sender_recipient_and_payload() -> None:
    sender, recipient, stranger = (crypto.generate_device_identity() for _ in range(3))
    tag = crypto.grant_auth(sender, recipient.public_key, b"grant payload")
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", tag)
    assert crypto.grant_auth(sender, recipient.public_key, b"grant payload") == tag, "deterministic"
    assert crypto.verify_grant_auth(recipient, sender.public_key, b"grant payload", tag)
    # The static-static key is symmetric, so the sender can check its own tag too.
    assert crypto.verify_grant_auth(sender, recipient.public_key, b"grant payload", tag)

    assert not crypto.verify_grant_auth(recipient, sender.public_key, b"grant payloaD", tag)
    assert not crypto.verify_grant_auth(recipient, stranger.public_key, b"grant payload", tag)
    assert not crypto.verify_grant_auth(stranger, sender.public_key, b"grant payload", tag)
    forged = crypto.grant_auth(stranger, recipient.public_key, b"grant payload")
    assert not crypto.verify_grant_auth(recipient, sender.public_key, b"grant payload", forged)
    raw = base64.urlsafe_b64decode(tag + "=")
    for bit in range(len(raw) * 8):
        flipped = b64url_encode(flip_bit(raw, bit))
        assert not crypto.verify_grant_auth(recipient, sender.public_key, b"grant payload", flipped)
    for bad in ("", tag + "=", tag[:-1], "ñ" * 43, None, 7):
        assert not crypto.verify_grant_auth(recipient, sender.public_key, b"grant payload", bad)  # type: ignore[arg-type]


def test_grant_auth_rejects_invalid_keys() -> None:
    sender, recipient = crypto.generate_device_identity(), crypto.generate_device_identity()
    with pytest.raises(ValidationFailedError):
        crypto.grant_auth(sender, b"short", b"x")
    with pytest.raises(ValidationFailedError):
        crypto.grant_auth(sender, bytes(32), b"x")
    tag = crypto.grant_auth(sender, recipient.public_key, b"x")
    assert not crypto.verify_grant_auth(recipient, bytes(32), b"x", tag)
    assert not crypto.verify_grant_auth(recipient, b"short", b"x", tag)


def test_reprs_and_errors_hide_secrets() -> None:
    keyring = _keyring()
    identity = crypto.generate_device_identity()
    assert "keys" not in repr(keyring)
    assert repr(identity.private_key) not in repr(identity)
    assert repr(crypto) == "VaultCrypto()"
    secret_json = crypto.keyring_to_bytes(keyring)
    with pytest.raises(ValidationFailedError) as caught:
        crypto.keyring_from_bytes(secret_json[:-1])
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert b64url_encode(b"\x01" * 32) not in str(caught.value)
    assert caught.value.details == {}


def test_deterministic_random_makes_outputs_reproducible() -> None:
    first = VaultCrypto(random_bytes=DeterministicRandom(b"seed"))
    second = VaultCrypto(random_bytes=DeterministicRandom(b"seed"))
    assert first.generate_keyring("v") == second.generate_keyring("v")
    assert first.generate_recovery_code() == second.generate_recovery_code()
    assert first.generate_device_identity() == second.generate_device_identity()


def _code_with_aliasable_chars() -> str:
    for _ in range(10_000):
        code = crypto.generate_recovery_code()
        if "0" in code and "1" in code:
            return code
    raise AssertionError("could not generate a code with 0 and 1")


def _flip_b64(value: str) -> str:
    raw = bytearray(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    raw[0] ^= 1
    return b64url_encode(bytes(raw))
