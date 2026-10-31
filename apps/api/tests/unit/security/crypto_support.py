from __future__ import annotations

import hashlib


class DeterministicRandom:
    """Reproducible byte stream (SHA-256 in counter mode) for known-answer tests only."""

    def __init__(self, seed: bytes) -> None:
        self._seed = seed
        self._counter = 0
        self._buffer = b""

    def __call__(self, size: int) -> bytes:
        while len(self._buffer) < size:
            self._buffer += hashlib.sha256(self._seed + self._counter.to_bytes(8, "big")).digest()
            self._counter += 1
        chunk, self._buffer = self._buffer[:size], self._buffer[size:]
        return chunk


def flip_bit(data: bytes, bit: int) -> bytes:
    mutated = bytearray(data)
    mutated[bit // 8] ^= 1 << (bit % 8)
    return bytes(mutated)
