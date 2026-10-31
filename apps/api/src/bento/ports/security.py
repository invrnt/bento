from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from bento.domain.security import (
    BlobCipherParams,
    BlobCipherResult,
    DeviceIdentity,
    EncryptionMetadata,
    RecoveryWrap,
    SealPurpose,
    VaultKeyring,
)


class EncryptionPort(Protocol):
    async def encrypt(self, source_ref: str) -> tuple[str, EncryptionMetadata]: ...

    async def decrypt(self, source_ref: str, metadata: EncryptionMetadata) -> str: ...


ReadCiphertext = Callable[[int, int], Awaitable[bytes]]
"""Async reader of `(offset, length)` from a remote ciphertext stream."""


class BlobCipherPort(Protocol):
    """v2 streaming AEAD (see architecture/telegram-first.md § Blob format v2)."""

    def new_params(self, keyring: VaultKeyring) -> BlobCipherParams: ...

    def ciphertext_size(self, plaintext_size: int, segment_size: int = 1024 * 1024) -> int: ...

    async def encrypt_file(
        self, source: Path, destination: Path, *, keyring: VaultKeyring, params: BlobCipherParams
    ) -> BlobCipherResult:
        """Deterministic for identical inputs so resumed uploads produce identical ciphertext."""
        ...

    def header_digest(self, params: BlobCipherParams) -> str:
        """b64url SHA-256 of the v2 header these params produce (`cipher_header_sha256` of the blob ref)."""
        ...

    async def decrypt_file(
        self, source: Path, destination: Path, *, keyring: VaultKeyring, expected_header_sha256: str | None = None
    ) -> str:
        """Decrypt a full v2 (or legacy v1) file; returns the plaintext sha256.

        With `expected_header_sha256`, a v2 header with another digest raises `IntegrityError` before decrypting.
        """
        ...

    async def decrypt_range(
        self,
        read: ReadCiphertext,
        *,
        ciphertext_size: int,
        start: int,
        length: int,
        keyring: VaultKeyring,
        expected_header_sha256: str | None = None,
    ) -> bytes:
        """Decrypt plaintext bytes [start, start+length) fetching only the needed segments (header digest as above)."""
        ...


class VaultCryptoPort(Protocol):
    def generate_keyring(self, vault_id: str) -> VaultKeyring: ...

    def rotate_keyring(self, keyring: VaultKeyring) -> VaultKeyring: ...

    def keyring_to_bytes(self, keyring: VaultKeyring) -> bytes: ...

    def keyring_from_bytes(self, payload: bytes) -> VaultKeyring: ...

    def seal(self, keyring: VaultKeyring, purpose: SealPurpose, plaintext: bytes, *, aad: bytes = b"") -> bytes: ...

    def open(self, keyring: VaultKeyring, purpose: SealPurpose, envelope: bytes, *, aad: bytes = b"") -> bytes:
        """Raises `IntegrityError` on tampering or wrong purpose."""
        ...

    def seal_json(self, keyring: VaultKeyring, purpose: SealPurpose, payload: Any, *, aad: bytes = b"") -> bytes:
        """zlib-compressed canonical JSON, then `seal`."""
        ...

    def open_json(
        self,
        keyring: VaultKeyring,
        purpose: SealPurpose,
        envelope: bytes,
        *,
        aad: bytes = b"",
        max_json_bytes: int | None = None,
    ) -> Any:
        """`open`, then inflate at most `max_json_bytes` (default: the adapter's limit); larger payloads fail closed."""
        ...

    def header_mac(self, keyring: VaultKeyring, canonical_unsigned: bytes) -> str: ...

    def verify_header_mac(self, keyring: VaultKeyring, canonical_unsigned: bytes, mac: str | None) -> bool: ...

    def generate_recovery_code(self) -> str: ...

    def normalize_recovery_code(self, code: str) -> str:
        """Raises `RecoveryCodeInvalidError` on bad characters or checksum."""
        ...

    def wrap_for_recovery(self, keyring: VaultKeyring, recovery_code: str) -> RecoveryWrap: ...

    def unwrap_with_recovery(self, wrap: RecoveryWrap, recovery_code: str, *, vault_id: str) -> VaultKeyring:
        """Raises `RecoveryCodeInvalidError` when the code does not open the wrap."""
        ...

    def generate_device_identity(self) -> DeviceIdentity: ...

    def device_identity_to_bytes(self, identity: DeviceIdentity) -> bytes: ...

    def device_identity_from_bytes(self, payload: bytes) -> DeviceIdentity: ...

    def seal_for_device(self, recipient_public_key: bytes, plaintext: bytes, *, aad: bytes = b"") -> bytes: ...

    def open_sealed(self, identity: DeviceIdentity, sealed: bytes, *, aad: bytes = b"") -> bytes: ...

    def grant_auth(self, identity: DeviceIdentity, recipient_public_key: bytes, payload: bytes) -> str:
        """b64url `HMAC-SHA256(HKDF(X25519(identity, recipient), salt = sorted public keys,
        info="bento/v1/keys-grant-auth"), payload)`: proves the grant comes from `identity`'s device.

        Raises `ValidationFailedError` for an unusable recipient key.
        """
        ...

    def verify_grant_auth(self, identity: DeviceIdentity, sender_public_key: bytes, payload: bytes, tag: str) -> bool:
        """Constant-time check of a `grant_auth` tag the sender computed for `identity`'s device."""
        ...


class PairingCryptoSessionPort(Protocol):
    """SPAKE2 session for one side of a relay pairing."""

    def start(self) -> bytes: ...

    def finish(self, peer_message: bytes) -> None: ...

    def confirmation(self) -> bytes: ...

    def verify_peer_confirmation(self, confirmation: bytes) -> None:
        """Raises `IntegrityError` when the peer used a different code."""
        ...

    def sas(self) -> tuple[str, str, str, str]: ...

    def encrypt_message(self, payload: dict[str, Any]) -> bytes: ...

    def decrypt_message(self, frame: bytes) -> dict[str, Any]: ...


class FallbackPairingKeysPort(Protocol):
    """Ephemeral X25519 exchange used by Sync-channel pairing (commit-then-reveal, see architecture doc)."""

    def public_key(self) -> bytes: ...

    def commitment(self, *, device_public_key: bytes, request_id: str) -> str:
        """Guest side: b64url SHA-256 commitment to this ephemeral key."""
        ...

    def sas_with(
        self,
        peer_public_key: bytes,
        *,
        request_id: str,
        guest_device_public_key: bytes,
        guest_ephemeral_public_key: bytes,
        host_ephemeral_public_key: bytes,
    ) -> tuple[str, str, str, str]: ...

    def grant_key_with(
        self,
        peer_public_key: bytes,
        *,
        request_id: str,
        guest_device_public_key: bytes,
        guest_ephemeral_public_key: bytes,
        host_ephemeral_public_key: bytes,
    ) -> bytes:
        """32-byte `HKDF(X25519, salt = SAS transcript hash, info="bento/v1/pairing/fallback-grant")`."""
        ...

    def seal_grant(
        self,
        peer_public_key: bytes,
        sealed_keyring: bytes,
        *,
        request_id: str,
        guest_device_public_key: bytes,
        guest_ephemeral_public_key: bytes,
        host_ephemeral_public_key: bytes,
    ) -> bytes:
        """Host: `nonce 12B || AES-256-GCM(grant_key, nonce, sealed_keyring, aad=request_id)`."""
        ...

    def open_grant(
        self,
        peer_public_key: bytes,
        grant: bytes,
        *,
        request_id: str,
        guest_device_public_key: bytes,
        guest_ephemeral_public_key: bytes,
        host_ephemeral_public_key: bytes,
    ) -> bytes:
        """Guest: the sealed keyring inside `grant`. Raises `IntegrityError` unless the SAS-verified host made it."""
        ...


class PairingCryptoFactoryPort(Protocol):
    def host_session(self, password: bytes) -> PairingCryptoSessionPort: ...

    def guest_session(self, password: bytes) -> PairingCryptoSessionPort: ...

    def fallback_keys(self) -> FallbackPairingKeysPort: ...
