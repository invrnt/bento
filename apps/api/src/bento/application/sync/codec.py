"""Wire encodings used inside sync payloads (unpadded base64url, little-endian float32 vectors)."""

from __future__ import annotations

import base64
import binascii
import math
import re
import struct
from collections.abc import Sequence

from bento.domain.errors import ValidationFailedError

_B64URL = re.compile(r"[A-Za-z0-9_-]*")


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(text: str) -> bytes:
    """Strict unpadded base64url (the format of every sync/keys payload field)."""
    if not isinstance(text, str) or _B64URL.fullmatch(text) is None or len(text) % 4 == 1:
        raise ValidationFailedError("Expected an unpadded base64url string")
    try:
        decoded = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        raise ValidationFailedError("Expected an unpadded base64url string") from None
    if b64url_encode(decoded) != text:
        raise ValidationFailedError("Non-canonical base64url string")
    return decoded


def encode_vector(vector: Sequence[float]) -> str:
    return b64url_encode(struct.pack(f"<{len(vector)}f", *vector))


def decode_vector(text: str, dimensions: int) -> tuple[float, ...]:
    raw = b64url_decode(text)
    if dimensions < 1 or len(raw) != dimensions * 4:
        raise ValidationFailedError("Embedding vector does not match its dimensions")
    vector = struct.unpack(f"<{dimensions}f", raw)
    if not all(math.isfinite(value) for value in vector):
        raise ValidationFailedError("Embedding vector contains non-finite values")
    return vector
