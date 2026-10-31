"""Vault keyring, envelopes, header MAC, recovery code, device identity and sealed boxes.

Formats follow `orchestration/architecture/telegram-first.md` § Cryptography:

```txt
keyring  = canonical JSON {"current_epoch": int, "keys": {"<epoch>": b64url(VMK)}, "vault_id": str}
subkey   = HKDF-SHA256(ikm=VMK_e, salt=vault_id_utf8, info="bento/v1/<purpose>", length=32)
envelope = "BENV" | 0x01 | purpose u8 | epoch u32 BE | nonce 12B | AES-256-GCM(ct || tag)
           AAD = the 22-byte prefix (magic..nonce) || caller aad
sealed   = "BBOX" | 0x01 | eph_pub 32B | nonce 12B | AES-256-GCM(ct || tag)
           key = HKDF(X25519(eph, recipient), salt=eph_pub || recipient_pub, info="bento/v1/sealed-box")
           AAD = the 49-byte prefix (magic..nonce) || caller aad
grant    = HMAC-SHA256(HKDF(X25519(sender, recipient), salt=min(pub_a, pub_b) || max(pub_a, pub_b),
           info="bento/v1/keys-grant-auth"), payload), base64url without padding
recovery = Crockford Base32 of (160-bit secret || first 20 bits of SHA-256(secret)), 9 groups of 4
```
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import uuid
import zlib
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.constant_time import bytes_eq

from bento.adapters.security.primitives import (
    KEY_BYTES,
    NONCE_BYTES,
    TAG_BYTES,
    U32_MAX,
    RandomBytes,
    b64url_decode,
    b64url_encode,
    hkdf_sha256,
    hmac_sha256,
    vault_subkey,
)
from bento.domain.errors import IntegrityError, RecoveryCodeInvalidError, ValidationFailedError
from bento.domain.pairing import CROCKFORD_ALPHABET
from bento.domain.security import DeviceIdentity, KeyPurpose, RecoveryWrap, SealPurpose, VaultKeyring
from bento.domain.vault import canonical_json

ENVELOPE_MAGIC = b"BENV"
ENVELOPE_VERSION = 1
SEALED_BOX_MAGIC = b"BBOX"
SEALED_BOX_VERSION = 1
RECOVERY_ALG = "hkdf-aesgcm-v1"
RECOVERY_SECRET_BYTES = 20
DEVICE_IDENTITY_VERSION = 1
DEFAULT_MAX_JSON_BYTES = 1024 * 1024 * 1024

SEAL_PURPOSE_LABELS: dict[SealPurpose, str] = {
    SealPurpose.SYNC: KeyPurpose.SYNC.value,
    SealPurpose.SNAPSHOT: KeyPurpose.SNAPSHOT.value,
    SealPurpose.DEVICE_RECORD: KeyPurpose.DEVICE_RECORD.value,
    SealPurpose.PAIRING: "pairing",
}
"""HKDF purpose label of each envelope purpose (pairing envelopes get their own `bento/v1/pairing` subkey)."""

_ENVELOPE_PREFIX = struct.Struct(">4sBBI12s")
_SEALED_PREFIX = struct.Struct(">4sB32s12s")
_SEALED_BOX_INFO = b"bento/v1/sealed-box"
_GRANT_AUTH_INFO = b"bento/v1/keys-grant-auth"
_RECOVERY_SALT = b"bento/v1/recovery"
_RECOVERY_CHARS = 36
_RECOVERY_CHECKSUM_BITS = 20
_CROCKFORD_INDEX = {char: index for index, char in enumerate(CROCKFORD_ALPHABET)}
_CROCKFORD_ALIASES = str.maketrans({"O": "0", "I": "1", "L": "1"})
_RECOVERY_SEPARATORS = re.compile(r"[\s\-‐-―−]")
_EPOCH_KEY = re.compile(r"[1-9][0-9]{0,9}")


class VaultCrypto:
    """`VaultCryptoPort` implementation. `random_bytes` is injectable only for known-answer tests."""

    def __init__(self, *, random_bytes: RandomBytes = os.urandom, max_json_bytes: int = DEFAULT_MAX_JSON_BYTES) -> None:
        self._random = random_bytes
        self._max_json_bytes = max_json_bytes

    def __repr__(self) -> str:
        return "VaultCrypto()"

    # Keyring

    def generate_keyring(self, vault_id: str) -> VaultKeyring:
        return VaultKeyring(vault_id=vault_id, current_epoch=1, keys={1: self._random(KEY_BYTES)})

    def rotate_keyring(self, keyring: VaultKeyring) -> VaultKeyring:
        epoch = max(keyring.keys) + 1
        if epoch > U32_MAX:
            raise ValidationFailedError("Vault key epochs are exhausted")
        return VaultKeyring(
            vault_id=keyring.vault_id, current_epoch=epoch, keys={**keyring.keys, epoch: self._random(KEY_BYTES)}
        )

    def keyring_to_bytes(self, keyring: VaultKeyring) -> bytes:
        return canonical_json(
            {
                "vault_id": keyring.vault_id,
                "current_epoch": keyring.current_epoch,
                "keys": {str(epoch): b64url_encode(key) for epoch, key in keyring.keys.items()},
            }
        )

    def keyring_from_bytes(self, payload: bytes) -> VaultKeyring:
        try:
            data = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, ValueError, TypeError):
            raise ValidationFailedError("Invalid vault keyring") from None
        if not isinstance(data, dict) or set(data) != {"vault_id", "current_epoch", "keys"}:
            raise ValidationFailedError("Invalid vault keyring")
        vault_id, current_epoch, encoded_keys = data["vault_id"], data["current_epoch"], data["keys"]
        if not isinstance(vault_id, str) or not _is_epoch(current_epoch) or not isinstance(encoded_keys, dict):
            raise ValidationFailedError("Invalid vault keyring")
        keys: dict[int, bytes] = {}
        for epoch_text, encoded in encoded_keys.items():
            if _EPOCH_KEY.fullmatch(epoch_text) is None or not _is_epoch(int(epoch_text)):
                raise ValidationFailedError("Invalid vault keyring")
            try:
                key = b64url_decode(encoded)
            except ValidationFailedError:
                raise ValidationFailedError("Invalid vault keyring") from None
            if len(key) != KEY_BYTES:
                raise ValidationFailedError("Invalid vault keyring")
            keys[int(epoch_text)] = key
        return VaultKeyring(vault_id=vault_id, current_epoch=current_epoch, keys=keys)

    # Envelopes

    def seal(self, keyring: VaultKeyring, purpose: SealPurpose, plaintext: bytes, *, aad: bytes = b"") -> bytes:
        purpose = SealPurpose(purpose)
        epoch = keyring.current_epoch
        nonce = self._random(NONCE_BYTES)
        prefix = _ENVELOPE_PREFIX.pack(ENVELOPE_MAGIC, ENVELOPE_VERSION, purpose.value, epoch, nonce)
        key = vault_subkey(keyring, SEAL_PURPOSE_LABELS[purpose], epoch)
        try:
            return prefix + AESGCM(key).encrypt(nonce, plaintext, prefix + aad)
        except OverflowError:
            raise ValidationFailedError("Payload is too large to seal") from None

    def open(self, keyring: VaultKeyring, purpose: SealPurpose, envelope: bytes, *, aad: bytes = b"") -> bytes:
        purpose = SealPurpose(purpose)
        envelope = bytes(envelope)
        if len(envelope) < _ENVELOPE_PREFIX.size + TAG_BYTES:
            raise IntegrityError("envelope")
        magic, version, code, epoch, nonce = _ENVELOPE_PREFIX.unpack_from(envelope)
        if magic != ENVELOPE_MAGIC or version != ENVELOPE_VERSION or code != purpose.value:
            raise IntegrityError("envelope")
        if epoch not in keyring.keys:
            raise IntegrityError("envelope_epoch")
        prefix = envelope[: _ENVELOPE_PREFIX.size]
        key = vault_subkey(keyring, SEAL_PURPOSE_LABELS[purpose], epoch)
        try:
            return AESGCM(key).decrypt(nonce, envelope[_ENVELOPE_PREFIX.size :], prefix + aad)
        except InvalidTag:
            raise IntegrityError("envelope") from None

    def seal_json(self, keyring: VaultKeyring, purpose: SealPurpose, payload: Any, *, aad: bytes = b"") -> bytes:
        try:
            encoded = canonical_json(payload)
        except (TypeError, ValueError):
            raise ValidationFailedError("Sealed payload must be JSON serializable") from None
        return self.seal(keyring, purpose, zlib.compress(encoded), aad=aad)

    def open_json(self, keyring: VaultKeyring, purpose: SealPurpose, envelope: bytes, *, aad: bytes = b"") -> Any:
        compressed = self.open(keyring, purpose, envelope, aad=aad)
        decompressor = zlib.decompressobj()
        try:
            encoded = decompressor.decompress(compressed, self._max_json_bytes)
            if decompressor.unconsumed_tail or not decompressor.eof or decompressor.unused_data:
                raise IntegrityError("envelope_payload")
            return json.loads(encoded.decode("utf-8"))
        except (zlib.error, UnicodeDecodeError, ValueError, RecursionError):
            raise IntegrityError("envelope_payload") from None

    # Header MAC

    def header_mac(self, keyring: VaultKeyring, canonical_unsigned: bytes) -> str:
        """HMAC-SHA256 under the current epoch's `header-mac` subkey, base64url without padding."""
        key = vault_subkey(keyring, KeyPurpose.HEADER_MAC.value, keyring.current_epoch)
        return b64url_encode(hmac_sha256(key, canonical_unsigned))

    def verify_header_mac(self, keyring: VaultKeyring, canonical_unsigned: bytes, mac: str | None) -> bool:
        if not isinstance(mac, str) or not mac or not mac.isascii():
            return False
        expected = self.header_mac(keyring, canonical_unsigned)
        return bytes_eq(expected.encode("ascii"), mac.encode("ascii"))

    # Recovery

    def generate_recovery_code(self) -> str:
        return _format_recovery_code(self._random(RECOVERY_SECRET_BYTES))

    def normalize_recovery_code(self, code: str) -> str:
        return _format_recovery_code(_parse_recovery_code(code))

    def wrap_for_recovery(self, keyring: VaultKeyring, recovery_code: str) -> RecoveryWrap:
        key = recovery_wrap_key(_parse_recovery_code(recovery_code), keyring.vault_id)
        nonce = self._random(NONCE_BYTES)
        wrapped = AESGCM(key).encrypt(nonce, self.keyring_to_bytes(keyring), keyring.vault_id.encode("utf-8"))
        return RecoveryWrap(alg=RECOVERY_ALG, nonce=b64url_encode(nonce), wrapped_keyring=b64url_encode(wrapped))

    def unwrap_with_recovery(self, wrap: RecoveryWrap, recovery_code: str, *, vault_id: str) -> VaultKeyring:
        secret = _parse_recovery_code(recovery_code)
        if wrap.alg != RECOVERY_ALG:
            raise ValidationFailedError("Unsupported recovery wrap algorithm")
        try:
            nonce = b64url_decode(wrap.nonce)
            wrapped = b64url_decode(wrap.wrapped_keyring)
        except ValidationFailedError:
            raise RecoveryCodeInvalidError() from None
        if len(nonce) != NONCE_BYTES or len(wrapped) < TAG_BYTES:
            raise RecoveryCodeInvalidError()
        try:
            payload = AESGCM(recovery_wrap_key(secret, vault_id)).decrypt(nonce, wrapped, vault_id.encode("utf-8"))
        except InvalidTag:
            raise RecoveryCodeInvalidError() from None
        try:
            keyring = self.keyring_from_bytes(payload)
        except ValidationFailedError:
            raise IntegrityError("recovery_wrap") from None
        if keyring.vault_id != vault_id:
            raise IntegrityError("recovery_wrap")
        return keyring

    # Device identity and sealed boxes

    def generate_device_identity(self) -> DeviceIdentity:
        private_key = self._random(KEY_BYTES)
        device_id = "dev_" + uuid.UUID(bytes=self._random(16), version=4).hex
        return _identity(device_id, private_key)

    def device_identity_to_bytes(self, identity: DeviceIdentity) -> bytes:
        return canonical_json(
            {
                "v": DEVICE_IDENTITY_VERSION,
                "device_id": identity.device_id,
                "private_key": b64url_encode(identity.private_key),
            }
        )

    def device_identity_from_bytes(self, payload: bytes) -> DeviceIdentity:
        try:
            data = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, ValueError, TypeError):
            raise ValidationFailedError("Invalid device identity") from None
        if (
            not isinstance(data, dict)
            or set(data) != {"v", "device_id", "private_key"}
            or data["v"] != DEVICE_IDENTITY_VERSION
            or not isinstance(data["device_id"], str)
        ):
            raise ValidationFailedError("Invalid device identity")
        try:
            private_key = b64url_decode(data["private_key"])
        except ValidationFailedError:
            raise ValidationFailedError("Invalid device identity") from None
        if len(private_key) != KEY_BYTES:
            raise ValidationFailedError("Invalid device identity")
        return _identity(data["device_id"], private_key)

    def seal_for_device(self, recipient_public_key: bytes, plaintext: bytes, *, aad: bytes = b"") -> bytes:
        recipient_public_key = bytes(recipient_public_key)
        if len(recipient_public_key) != KEY_BYTES:
            raise ValidationFailedError("Device public key must be 32 bytes")
        ephemeral = X25519PrivateKey.from_private_bytes(self._random(KEY_BYTES))
        ephemeral_public = ephemeral.public_key().public_bytes_raw()
        try:
            shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(recipient_public_key))
        except ValueError:
            raise ValidationFailedError("Invalid device public key") from None
        key = hkdf_sha256(shared, salt=ephemeral_public + recipient_public_key, info=_SEALED_BOX_INFO)
        nonce = self._random(NONCE_BYTES)
        prefix = _SEALED_PREFIX.pack(SEALED_BOX_MAGIC, SEALED_BOX_VERSION, ephemeral_public, nonce)
        return prefix + AESGCM(key).encrypt(nonce, plaintext, prefix + aad)

    def open_sealed(self, identity: DeviceIdentity, sealed: bytes, *, aad: bytes = b"") -> bytes:
        sealed = bytes(sealed)
        if len(sealed) < _SEALED_PREFIX.size + TAG_BYTES:
            raise IntegrityError("sealed_box")
        magic, version, ephemeral_public, nonce = _SEALED_PREFIX.unpack_from(sealed)
        if magic != SEALED_BOX_MAGIC or version != SEALED_BOX_VERSION:
            raise IntegrityError("sealed_box")
        private = X25519PrivateKey.from_private_bytes(identity.private_key)
        try:
            shared = private.exchange(X25519PublicKey.from_public_bytes(ephemeral_public))
        except ValueError:
            raise IntegrityError("sealed_box") from None
        recipient_public = private.public_key().public_bytes_raw()
        key = hkdf_sha256(shared, salt=ephemeral_public + recipient_public, info=_SEALED_BOX_INFO)
        prefix = sealed[: _SEALED_PREFIX.size]
        try:
            return AESGCM(key).decrypt(nonce, sealed[_SEALED_PREFIX.size :], prefix + aad)
        except InvalidTag:
            raise IntegrityError("sealed_box") from None

    def grant_auth(self, identity: DeviceIdentity, recipient_public_key: bytes, payload: bytes) -> str:
        return b64url_encode(hmac_sha256(grant_auth_key(identity, recipient_public_key), payload))

    def verify_grant_auth(self, identity: DeviceIdentity, sender_public_key: bytes, payload: bytes, tag: str) -> bool:
        if not isinstance(tag, str) or not tag or not tag.isascii():
            return False
        try:
            expected = self.grant_auth(identity, sender_public_key, payload)
        except ValidationFailedError:
            return False
        return bytes_eq(expected.encode("ascii"), tag.encode("ascii"))


def grant_auth_key(identity: DeviceIdentity, peer_public_key: bytes) -> bytes:
    """Static-static key of two devices (the same in both directions)."""
    peer_public_key = bytes(peer_public_key)
    if len(peer_public_key) != KEY_BYTES:
        raise ValidationFailedError("Device public key must be 32 bytes")
    private = X25519PrivateKey.from_private_bytes(identity.private_key)
    try:
        shared = private.exchange(X25519PublicKey.from_public_bytes(peer_public_key))
    except ValueError:
        raise ValidationFailedError("Invalid device public key") from None
    own_public = private.public_key().public_bytes_raw()
    return hkdf_sha256(shared, salt=b"".join(sorted((own_public, peer_public_key))), info=_GRANT_AUTH_INFO)


def recovery_wrap_key(secret: bytes, vault_id: str) -> bytes:
    """`HKDF-SHA256(ikm=secret, salt="bento/v1/recovery", info=vault_id, length=32)`."""
    return hkdf_sha256(secret, salt=_RECOVERY_SALT, info=vault_id.encode("utf-8"))


def _identity(device_id: str, private_key: bytes) -> DeviceIdentity:
    public_key = X25519PrivateKey.from_private_bytes(private_key).public_key().public_bytes_raw()
    return DeviceIdentity(device_id=device_id, private_key=private_key, public_key=public_key)


def _is_epoch(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= U32_MAX


def _recovery_checksum(secret: bytes) -> int:
    return int.from_bytes(hashlib.sha256(secret).digest()[:3], "big") >> (24 - _RECOVERY_CHECKSUM_BITS)


def _format_recovery_code(secret: bytes) -> str:
    value = (int.from_bytes(secret, "big") << _RECOVERY_CHECKSUM_BITS) | _recovery_checksum(secret)
    chars = "".join(
        CROCKFORD_ALPHABET[(value >> (5 * (_RECOVERY_CHARS - 1 - position))) & 31]
        for position in range(_RECOVERY_CHARS)
    )
    return "-".join(chars[offset : offset + 4] for offset in range(0, _RECOVERY_CHARS, 4))


def _parse_recovery_code(code: str) -> bytes:
    if not isinstance(code, str):
        raise RecoveryCodeInvalidError()
    stripped = _RECOVERY_SEPARATORS.sub("", code)
    if not stripped.isascii():
        raise RecoveryCodeInvalidError()
    cleaned = stripped.upper().translate(_CROCKFORD_ALIASES)
    if len(cleaned) != _RECOVERY_CHARS or any(char not in _CROCKFORD_INDEX for char in cleaned):
        raise RecoveryCodeInvalidError()
    value = 0
    for char in cleaned:
        value = (value << 5) | _CROCKFORD_INDEX[char]
    secret = (value >> _RECOVERY_CHECKSUM_BITS).to_bytes(RECOVERY_SECRET_BYTES, "big")
    checksum = value & ((1 << _RECOVERY_CHECKSUM_BITS) - 1)
    if not bytes_eq(checksum.to_bytes(3, "big"), _recovery_checksum(secret).to_bytes(3, "big")):
        raise RecoveryCodeInvalidError()
    return secret
