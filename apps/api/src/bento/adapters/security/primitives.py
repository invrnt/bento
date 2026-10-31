"""Shared building blocks for the Telegram-first crypto adapters.

Only compositions of `cryptography` primitives live here; formats are defined in
`orchestration/architecture/telegram-first.md` § Cryptography.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Callable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import hmac as crypto_hmac
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from bento.domain.errors import ValidationFailedError
from bento.domain.security import VaultKeyring

KEY_BYTES = 32
NONCE_BYTES = 12
TAG_BYTES = 16
U32_MAX = 0xFFFFFFFF

RandomBytes = Callable[[int], bytes]
"""Source of cryptographically secure random bytes (`os.urandom`); injectable only for known-answer tests."""

_B64URL = re.compile(r"[A-Za-z0-9_-]*")


def hkdf_sha256(ikm: bytes, *, salt: bytes | None, info: bytes, length: int = KEY_BYTES) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def hmac_sha256(key: bytes, message: bytes) -> bytes:
    mac = crypto_hmac.HMAC(key, hashes.SHA256())
    mac.update(message)
    return mac.finalize()


def vault_subkey(keyring: VaultKeyring, label: str, epoch: int | None = None) -> bytes:
    """`HKDF-SHA256(ikm=VMK_e, salt=vault_id_utf8, info="bento/v1/<label>", length=32)`."""
    return hkdf_sha256(
        keyring.key(epoch),
        salt=keyring.vault_id.encode("utf-8"),
        info=b"bento/v1/" + label.encode("ascii"),
    )


def b64url_encode(data: bytes) -> str:
    """URL-safe base64 without padding (RFC 4648 §5)."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(text: str) -> bytes:
    """Strict URL-safe base64 decoding; accepts optional `=` padding and nothing else."""
    if not isinstance(text, str):
        raise ValidationFailedError("Expected a base64url string")
    body = text.rstrip("=")
    if len(text) - len(body) > 2 or _B64URL.fullmatch(body) is None or len(body) % 4 == 1:
        raise ValidationFailedError("Invalid base64url value")
    try:
        return base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except (binascii.Error, ValueError):
        raise ValidationFailedError("Invalid base64url value") from None
