from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum

from bento.domain.errors import ValidationFailedError


class EncryptionMode(StrEnum):
    NONE = "none"
    AES_GCM = "aes_gcm"
    AES_GCM_STREAM = "aes_gcm_stream"


@dataclass(frozen=True, slots=True)
class EncryptionMetadata:
    mode: EncryptionMode
    key_id: str | None = None
    nonce: str | None = None
    tag: str | None = None
    key_epoch: int | None = None
    format_version: int = 1


class SealPurpose(IntEnum):
    SYNC = 1
    SNAPSHOT = 2
    DEVICE_RECORD = 3
    PAIRING = 4


class KeyPurpose(StrEnum):
    BLOB = "blob"
    SYNC = "sync"
    SNAPSHOT = "snapshot"
    HEADER_MAC = "header-mac"
    DEVICE_RECORD = "device-record"


@dataclass(frozen=True, slots=True)
class VaultKeyring:
    """All master keys of a vault, one per key epoch. Never serialized outside the key store or a sealed box."""

    vault_id: str
    current_epoch: int
    keys: dict[int, bytes] = field(repr=False)

    def __post_init__(self) -> None:
        if not self.vault_id.strip():
            raise ValidationFailedError("Vault id is required")
        if self.current_epoch not in self.keys:
            raise ValidationFailedError("Keyring must contain its current epoch")
        if any(len(key) != 32 for key in self.keys.values()):
            raise ValidationFailedError("Vault master keys must be 32 bytes")

    def key(self, epoch: int | None = None) -> bytes:
        selected = self.current_epoch if epoch is None else epoch
        try:
            return self.keys[selected]
        except KeyError as exc:
            raise ValidationFailedError("Unknown key epoch", {"epoch": selected}) from exc


@dataclass(frozen=True, slots=True)
class RecoveryWrap:
    """Keyring wrapped with a recovery code, as stored in the vault header (base64url strings)."""

    alg: str
    nonce: str
    wrapped_keyring: str


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    device_id: str
    private_key: bytes = field(repr=False)
    public_key: bytes = b""

    def __post_init__(self) -> None:
        if not self.device_id.startswith("dev_"):
            raise ValidationFailedError("Device id must start with dev_")
        if len(self.private_key) != 32 or len(self.public_key) != 32:
            raise ValidationFailedError("Device keys must be 32-byte X25519 keys")


@dataclass(frozen=True, slots=True)
class BlobCipherParams:
    """Deterministic inputs of a v2 streaming encryption so an interrupted upload can be resumed."""

    epoch: int
    file_salt: bytes
    nonce_prefix: bytes
    segment_size: int = 1024 * 1024

    def __post_init__(self) -> None:
        if len(self.file_salt) != 16:
            raise ValidationFailedError("Blob file salt must be 16 bytes")
        if len(self.nonce_prefix) != 7:
            raise ValidationFailedError("Blob nonce prefix must be 7 bytes")
        if self.segment_size < 4096:
            raise ValidationFailedError("Blob segment size is too small")


@dataclass(frozen=True, slots=True)
class BlobCipherResult:
    params: BlobCipherParams
    plaintext_size: int
    ciphertext_size: int
    plaintext_sha256: str
