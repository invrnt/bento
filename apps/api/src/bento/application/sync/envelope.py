"""Reads the public prefix of a sealed envelope (architecture § Envelope)."""

from __future__ import annotations

import struct

_PREFIX = struct.Struct(">4sBBI")
_MAGIC = b"BENV"


def envelope_epoch(envelope: bytes) -> int | None:
    """Key epoch carried by `"BENV" | version u8 | purpose u8 | epoch u32 BE | …`, or None if malformed."""
    if len(envelope) < _PREFIX.size:
        return None
    magic, _version, _purpose, epoch = _PREFIX.unpack_from(envelope)
    return epoch if magic == _MAGIC else None
