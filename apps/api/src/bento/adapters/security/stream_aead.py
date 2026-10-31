"""Blob format v2: segmented streaming AES-256-GCM (architecture/telegram-first.md § Blob format v2).

```txt
header = "BNT2" | version u8 = 2 | epoch u32 BE | file_salt 16B | segment_size u32 BE | nonce_prefix 7B   (36 bytes)
file_key = HKDF-SHA256(ikm=blob_subkey(epoch), salt=file_salt, info="bento/v1/blob-file", length=32)
segment i = AES-256-GCM(file_key, nonce = nonce_prefix || u32 BE(i) || u8(last), aad = header) -> ciphertext || tag
```

A plaintext of `P` bytes has `max(1, ceil(P / segment_size))` segments: a plaintext that is an exact
multiple of the segment size ends with a full final segment (no trailing empty segment); only the
empty plaintext produces a single empty segment.

The header carries a random `file_salt`, so its SHA-256 (`cipher_header_sha256` of the synced blob ref) names
one encryption of one file: reads that expect a digest reject any other ciphertext, even one sealed with the
same vault keys, before decrypting a segment.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import struct
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from bento.adapters.security.aes_gcm import LEGACY_V1_MAGIC, decrypt_legacy_body, read_legacy_envelope
from bento.adapters.security.primitives import (
    KEY_BYTES,
    TAG_BYTES,
    U32_MAX,
    RandomBytes,
    b64url_encode,
    hkdf_sha256,
    vault_subkey,
)
from bento.domain.errors import IntegrityError, ValidationFailedError
from bento.domain.security import BlobCipherParams, BlobCipherResult, KeyPurpose, VaultKeyring
from bento.ports.security import ReadCiphertext

BLOB_V2_MAGIC = b"BNT2"
BLOB_V2_VERSION = 2
HEADER_SIZE = 36
DEFAULT_SEGMENT_SIZE = 1024 * 1024
MIN_SEGMENT_SIZE = 4096
MAX_SEGMENT_SIZE = 64 * 1024 * 1024
"""Upper bound enforced by this adapter so a forged header cannot force huge reads before authentication."""

_HEADER = struct.Struct(">4sBI16sI7s")
_SEGMENT_NONCE_SUFFIX = struct.Struct(">IB")
_FILE_KEY_INFO = b"bento/v1/blob-file"
_SALT_BYTES = 16
_NONCE_PREFIX_BYTES = 7

assert _HEADER.size == HEADER_SIZE


@dataclass(frozen=True, slots=True)
class _Header:
    raw: bytes
    epoch: int
    file_salt: bytes
    segment_size: int
    nonce_prefix: bytes


@dataclass(frozen=True, slots=True)
class _Layout:
    segment_count: int
    last_segment_bytes: int
    plaintext_size: int


def encode_blob_header(params: BlobCipherParams) -> bytes:
    if not 0 <= params.epoch <= U32_MAX:
        raise ValidationFailedError("Blob key epoch is out of range")
    if params.segment_size > MAX_SEGMENT_SIZE:
        raise ValidationFailedError("Blob segment size is too large")
    return _HEADER.pack(
        BLOB_V2_MAGIC, BLOB_V2_VERSION, params.epoch, params.file_salt, params.segment_size, params.nonce_prefix
    )


def blob_header_digest(header: bytes) -> str:
    """b64url SHA-256 of a raw v2 header."""
    return b64url_encode(hashlib.sha256(header).digest())


def blob_file_key(keyring: VaultKeyring, epoch: int, file_salt: bytes) -> bytes:
    blob_key = vault_subkey(keyring, KeyPurpose.BLOB.value, epoch)
    return hkdf_sha256(blob_key, salt=file_salt, info=_FILE_KEY_INFO, length=KEY_BYTES)


def blob_segment_count(plaintext_size: int, segment_size: int) -> int:
    return max(1, -(-plaintext_size // segment_size))


class StreamingBlobCipher:
    """`BlobCipherPort` for blob format v2; full-file decryption also accepts legacy v1 files.

    `legacy_keys` maps a v1 key id to its 32-byte key (the former `BENTO_ENCRYPTION_KEY`).
    """

    def __init__(
        self,
        *,
        legacy_keys: Mapping[str, bytes] | None = None,
        segment_size: int = DEFAULT_SEGMENT_SIZE,
        random_bytes: RandomBytes = os.urandom,
    ) -> None:
        if not MIN_SEGMENT_SIZE <= segment_size <= MAX_SEGMENT_SIZE:
            raise ValidationFailedError("Blob segment size is out of range")
        keys = dict(legacy_keys or {})
        if any(len(key) != KEY_BYTES for key in keys.values()):
            raise ValidationFailedError("Legacy encryption keys must be 32 bytes")
        self._legacy_keys = keys
        self._segment_size = segment_size
        self._random = random_bytes

    def __repr__(self) -> str:
        return f"StreamingBlobCipher(segment_size={self._segment_size}, legacy_key_ids={sorted(self._legacy_keys)})"

    def new_params(self, keyring: VaultKeyring) -> BlobCipherParams:
        return BlobCipherParams(
            epoch=keyring.current_epoch,
            file_salt=self._random(_SALT_BYTES),
            nonce_prefix=self._random(_NONCE_PREFIX_BYTES),
            segment_size=self._segment_size,
        )

    def header_digest(self, params: BlobCipherParams) -> str:
        return blob_header_digest(encode_blob_header(params))

    def ciphertext_size(self, plaintext_size: int, segment_size: int = DEFAULT_SEGMENT_SIZE) -> int:
        if plaintext_size < 0:
            raise ValidationFailedError("Plaintext size cannot be negative")
        if not MIN_SEGMENT_SIZE <= segment_size <= MAX_SEGMENT_SIZE:
            raise ValidationFailedError("Blob segment size is out of range")
        return HEADER_SIZE + plaintext_size + TAG_BYTES * blob_segment_count(plaintext_size, segment_size)

    async def encrypt_file(
        self, source: Path, destination: Path, *, keyring: VaultKeyring, params: BlobCipherParams
    ) -> BlobCipherResult:
        return await asyncio.to_thread(self._encrypt_file, Path(source), Path(destination), keyring, params)

    async def decrypt_file(
        self, source: Path, destination: Path, *, keyring: VaultKeyring, expected_header_sha256: str | None = None
    ) -> str:
        return await asyncio.to_thread(
            self._decrypt_file, Path(source), Path(destination), keyring, expected_header_sha256
        )

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
        if start < 0 or length < 0:
            raise ValidationFailedError("Invalid blob range")
        raw = await read(0, HEADER_SIZE)
        if raw[: len(LEGACY_V1_MAGIC)] == LEGACY_V1_MAGIC:
            raise ValidationFailedError("Range decryption requires blob format v2")
        header = _parse_header(raw)
        _check_header_digest(header, expected_header_sha256)
        layout = _layout(ciphertext_size, header.segment_size)
        if start + length > layout.plaintext_size:
            raise ValidationFailedError("Blob range is outside the plaintext")
        if length == 0:
            return b""
        aead = _decrypt_aead(keyring, header)
        size = header.segment_size
        stride = size + TAG_BYTES
        end = start + length
        output = bytearray()
        for index in range(start // size, (end - 1) // size + 1):
            last = index == layout.segment_count - 1
            expected = layout.last_segment_bytes if last else stride
            ciphertext = await read(HEADER_SIZE + index * stride, expected)
            if len(ciphertext) != expected:
                raise IntegrityError("blob")
            plaintext = _open_segment(aead, header, index, last, ciphertext)
            segment_start = index * size
            view = memoryview(plaintext)[max(start - segment_start, 0) : min(end - segment_start, len(plaintext))]
            output += view
        if len(output) != length:
            raise IntegrityError("blob")
        return bytes(output)

    def _encrypt_file(
        self, source: Path, destination: Path, keyring: VaultKeyring, params: BlobCipherParams
    ) -> BlobCipherResult:
        header = encode_blob_header(params)
        aead = AESGCM(blob_file_key(keyring, params.epoch, params.file_salt))
        size = params.segment_size
        digest = hashlib.sha256()
        plaintext_size = 0
        written = 0
        with source.open("rb") as reader, _atomic_output(destination) as writer:
            writer.write(header)
            written += len(header)
            index = 0
            chunk = _read_up_to(reader, size)
            while True:
                following = _read_up_to(reader, size) if len(chunk) == size else b""
                last = not following
                if index > U32_MAX:
                    raise ValidationFailedError("Blob is too large for format v2")
                digest.update(chunk)
                plaintext_size += len(chunk)
                sealed = aead.encrypt(_segment_nonce(params.nonce_prefix, index, last), chunk, header)
                writer.write(sealed)
                written += len(sealed)
                if last:
                    break
                chunk = following
                index += 1
        return BlobCipherResult(
            params=params,
            plaintext_size=plaintext_size,
            ciphertext_size=written,
            plaintext_sha256=digest.hexdigest(),
        )

    def _decrypt_file(
        self, source: Path, destination: Path, keyring: VaultKeyring, expected_header_sha256: str | None
    ) -> str:
        with source.open("rb") as reader:
            magic = reader.read(len(LEGACY_V1_MAGIC))
            reader.seek(0)
            if magic[: len(BLOB_V2_MAGIC)] == BLOB_V2_MAGIC:
                return self._decrypt_v2(reader, destination, keyring, expected_header_sha256)
            if magic == LEGACY_V1_MAGIC and expected_header_sha256 is None:
                return self._decrypt_v1(reader, destination)
        raise IntegrityError("blob")

    def _decrypt_v2(
        self, reader: BinaryIO, destination: Path, keyring: VaultKeyring, expected_header_sha256: str | None
    ) -> str:
        ciphertext_size = os.fstat(reader.fileno()).st_size
        header = _parse_header(_read_up_to(reader, HEADER_SIZE))
        _check_header_digest(header, expected_header_sha256)
        layout = _layout(ciphertext_size, header.segment_size)
        aead = _decrypt_aead(keyring, header)
        stride = header.segment_size + TAG_BYTES
        digest = hashlib.sha256()
        with _atomic_output(destination) as writer:
            for index in range(layout.segment_count):
                last = index == layout.segment_count - 1
                expected = layout.last_segment_bytes if last else stride
                ciphertext = _read_up_to(reader, expected)
                if len(ciphertext) != expected:
                    raise IntegrityError("blob")
                plaintext = _open_segment(aead, header, index, last, ciphertext)
                digest.update(plaintext)
                writer.write(plaintext)
            if reader.read(1):
                raise IntegrityError("blob")
        return digest.hexdigest()

    def _decrypt_v1(self, reader: BinaryIO, destination: Path) -> str:
        try:
            envelope = read_legacy_envelope(reader)
        except ValidationFailedError:
            raise IntegrityError("blob") from None
        key = self._legacy_keys.get(envelope.key_id)
        if key is None:
            raise ValidationFailedError("Required Bento encryption key is not available")
        digest = hashlib.sha256()
        with _atomic_output(destination) as writer:

            def write(chunk: bytes) -> None:
                digest.update(chunk)
                writer.write(chunk)

            try:
                decrypt_legacy_body(reader, envelope, key, write)
            except (InvalidTag, ValidationFailedError):
                raise IntegrityError("blob") from None
        return digest.hexdigest()


def _parse_header(raw: bytes) -> _Header:
    if len(raw) != HEADER_SIZE:
        raise IntegrityError("blob")
    magic, version, epoch, file_salt, segment_size, nonce_prefix = _HEADER.unpack(raw)
    if magic != BLOB_V2_MAGIC or version != BLOB_V2_VERSION:
        raise IntegrityError("blob")
    if not MIN_SEGMENT_SIZE <= segment_size <= MAX_SEGMENT_SIZE:
        raise IntegrityError("blob")
    return _Header(
        raw=bytes(raw), epoch=epoch, file_salt=file_salt, segment_size=segment_size, nonce_prefix=nonce_prefix
    )


def _check_header_digest(header: _Header, expected: str | None) -> None:
    if expected is not None and not hmac.compare_digest(
        blob_header_digest(header.raw).encode("ascii"), str(expected).encode("utf-8")
    ):
        raise IntegrityError("blob_header")


def _layout(ciphertext_size: int, segment_size: int) -> _Layout:
    body = ciphertext_size - HEADER_SIZE
    if body < TAG_BYTES:
        raise IntegrityError("blob")
    stride = segment_size + TAG_BYTES
    count = -(-body // stride)
    last = body - (count - 1) * stride
    if last < TAG_BYTES or (count > 1 and last == TAG_BYTES) or count - 1 > U32_MAX:
        raise IntegrityError("blob")
    return _Layout(segment_count=count, last_segment_bytes=last, plaintext_size=body - count * TAG_BYTES)


def _decrypt_aead(keyring: VaultKeyring, header: _Header) -> AESGCM:
    # The header is only authenticated by the segment tags, so an unknown epoch fails closed.
    if header.epoch not in keyring.keys:
        raise IntegrityError("blob_epoch")
    return AESGCM(blob_file_key(keyring, header.epoch, header.file_salt))


def _segment_nonce(prefix: bytes, index: int, last: bool) -> bytes:
    return prefix + _SEGMENT_NONCE_SUFFIX.pack(index, 1 if last else 0)


def _open_segment(aead: AESGCM, header: _Header, index: int, last: bool, ciphertext: bytes) -> bytes:
    try:
        return aead.decrypt(_segment_nonce(header.nonce_prefix, index, last), ciphertext, header.raw)
    except InvalidTag:
        raise IntegrityError("blob") from None


def _read_up_to(reader: BinaryIO, size: int) -> bytes:
    data = reader.read(size)
    if len(data) == size or not data:
        return data
    parts = [data]
    remaining = size - len(data)
    while remaining:
        more = reader.read(remaining)
        if not more:
            break
        parts.append(more)
        remaining -= len(more)
    return b"".join(parts)


@contextmanager
def _atomic_output(destination: Path) -> Iterator[BinaryIO]:
    """Write to a private temporary sibling and move it into place only on success."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            yield handle
        os.replace(temporary_path, destination)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
