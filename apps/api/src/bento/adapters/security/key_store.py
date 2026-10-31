"""Device key store (architecture/telegram-first.md § Key Store).

Each secret is `<directory>/<name>.bin`:

```txt
"BKEY" | version u8 = 1 | nonce 12B | AES-256-GCM(device_wrapping_key, value, aad = name_ascii) -> ct || tag
```

Files are written `0600` through a temporary sibling, fsync and `os.replace`, so readers in other
processes see either the old or the new value.
"""

from __future__ import annotations

import asyncio
import os
import re
import stat
import struct
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from bento.adapters.security.primitives import (
    KEY_BYTES,
    NONCE_BYTES,
    TAG_BYTES,
    RandomBytes,
    b64url_decode,
    b64url_encode,
)
from bento.domain.errors import IntegrityError, ValidationFailedError
from bento.infrastructure import process_secrets

KEY_NAME_PATTERN = re.compile(r"[a-z0-9._-]{1,64}")
WRAPPING_KEY_ENV = "BENTO_DEVICE_WRAPPING_KEY"
WRAPPING_KEY_FILE = Path("secure") / "wrapping.key"
KEY_FILE_MAGIC = b"BKEY"
KEY_FILE_VERSION = 1

_KEY_FILE_PREFIX = struct.Struct(">4sB12s")
_POSIX = os.name == "posix"


@dataclass(frozen=True, slots=True)
class WrappingKey:
    """Device wrapping key plus where it came from; `file_based` should raise a doctor warning."""

    key: bytes = field(repr=False)
    file_based: bool
    path: Path | None = None


class WrappedFileKeyStore:
    """`KeyStorePort` persisting AES-256-GCM wrapped secrets in a private directory."""

    def __init__(self, directory: Path | str, wrapping_key: bytes, *, random_bytes: RandomBytes = os.urandom) -> None:
        if not isinstance(wrapping_key, bytes) or len(wrapping_key) != KEY_BYTES:
            raise ValidationFailedError("Device wrapping key must be 32 bytes")
        self._directory = Path(directory)
        self._wrapping_key = wrapping_key
        self._random = random_bytes

    def __repr__(self) -> str:
        return f"WrappedFileKeyStore(directory={str(self._directory)!r})"

    @property
    def directory(self) -> Path:
        return self._directory

    async def get(self, name: str) -> bytes | None:
        path = self._path(name)
        return await asyncio.to_thread(self._get_sync, name, path)

    async def put(self, name: str, value: bytes) -> None:
        path = self._path(name)
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise ValidationFailedError("Key store values must be bytes")
        await asyncio.to_thread(self._put_sync, name, path, bytes(value))

    async def delete(self, name: str) -> None:
        path = self._path(name)
        await asyncio.to_thread(self._delete_sync, path)

    def _path(self, name: str) -> Path:
        return self._directory / f"{validate_key_name(name)}.bin"

    def _get_sync(self, name: str, path: Path) -> bytes | None:
        try:
            payload = path.read_bytes()
        except FileNotFoundError:
            return None
        if len(payload) < _KEY_FILE_PREFIX.size + TAG_BYTES:
            raise IntegrityError("key_store")
        magic, version, nonce = _KEY_FILE_PREFIX.unpack_from(payload)
        if magic != KEY_FILE_MAGIC or version != KEY_FILE_VERSION:
            raise IntegrityError("key_store")
        try:
            return AESGCM(self._wrapping_key).decrypt(nonce, payload[_KEY_FILE_PREFIX.size :], name.encode("ascii"))
        except InvalidTag:
            raise IntegrityError("key_store") from None

    def _put_sync(self, name: str, path: Path, value: bytes) -> None:
        nonce = self._random(NONCE_BYTES)
        sealed = AESGCM(self._wrapping_key).encrypt(nonce, value, name.encode("ascii"))
        payload = _KEY_FILE_PREFIX.pack(KEY_FILE_MAGIC, KEY_FILE_VERSION, nonce) + sealed
        _ensure_private_directory(self._directory)
        _atomic_write(path, payload)

    def _delete_sync(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            return
        _fsync_directory(path.parent)


class InMemoryKeyStore:
    """`KeyStorePort` for tests and ephemeral runs; same name rules as the file store."""

    def __init__(self, initial: Mapping[str, bytes] | None = None) -> None:
        self._values: dict[str, bytes] = {}
        for name, value in (initial or {}).items():
            self._values[validate_key_name(name)] = bytes(value)

    def __repr__(self) -> str:
        return f"InMemoryKeyStore(names={sorted(self._values)})"

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._values))

    async def get(self, name: str) -> bytes | None:
        return self._values.get(validate_key_name(name))

    async def put(self, name: str, value: bytes) -> None:
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise ValidationFailedError("Key store values must be bytes")
        self._values[validate_key_name(name)] = bytes(value)

    async def delete(self, name: str) -> None:
        self._values.pop(validate_key_name(name), None)


def validate_key_name(name: str) -> str:
    if not isinstance(name, str) or KEY_NAME_PATTERN.fullmatch(name) is None:
        raise ValidationFailedError("Invalid key store name")
    return name


def load_wrapping_key(settings_env: Mapping[str, str], data_dir: Path | str) -> WrappingKey:
    """Return `BENTO_DEVICE_WRAPPING_KEY` (base64url, 32 bytes), or read/create
    `<data_dir>/secure/wrapping.key` (`0600`, base64url text). A present but invalid key fails closed.

    The key the desktop host provided (moved out of the environment by the sidecar launcher) wins
    over `settings_env`; once provided, the key file is never consulted or created."""
    provided = process_secrets.get(WRAPPING_KEY_ENV)
    if provided is not None:
        return WrappingKey(key=_decode_wrapping_key(provided, WRAPPING_KEY_ENV), file_based=False)
    raw = settings_env.get(WRAPPING_KEY_ENV)
    if raw is not None and raw.strip():
        return WrappingKey(key=_decode_wrapping_key(raw, WRAPPING_KEY_ENV), file_based=False)
    path = Path(data_dir) / WRAPPING_KEY_FILE
    return WrappingKey(key=_read_or_create_wrapping_key(path), file_based=True, path=path)


def _decode_wrapping_key(text: str, source: str) -> bytes:
    try:
        key = b64url_decode(text.strip())
    except ValidationFailedError:
        raise ValidationFailedError(f"{source} must be a base64url-encoded 32-byte key") from None
    if len(key) != KEY_BYTES:
        raise ValidationFailedError(f"{source} must be a base64url-encoded 32-byte key")
    return key


def _read_or_create_wrapping_key(path: Path) -> bytes:
    try:
        return _read_wrapping_key_file(path)
    except FileNotFoundError:
        pass
    _ensure_private_directory(path.parent)
    key = os.urandom(KEY_BYTES)
    content = (b64url_encode(key) + "\n").encode("ascii")
    descriptor, temporary = tempfile.mkstemp(prefix=".tmp-", suffix=".partial", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # Create-if-absent with complete content, so concurrent first starts agree on one key.
            os.link(temporary, path)
        except FileExistsError:
            return _read_wrapping_key_file(path)
        except OSError:
            if not _create_exclusive(path, content):
                return _read_wrapping_key_file(path)
        _fsync_directory(path.parent)
        return key
    finally:
        Path(temporary).unlink(missing_ok=True)


def _read_wrapping_key_file(path: Path) -> bytes:
    content = path.read_bytes()
    if _POSIX:
        try:
            if stat.S_IMODE(path.stat().st_mode) & 0o077:
                os.chmod(path, 0o600)
        except OSError:
            pass
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError:
        raise ValidationFailedError("The device wrapping key file is corrupt") from None
    try:
        return _decode_wrapping_key(text, "The device wrapping key file")
    except ValidationFailedError:
        raise ValidationFailedError("The device wrapping key file is corrupt") from None


def _create_exclusive(path: Path, content: bytes) -> bool:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def _ensure_private_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if _POSIX:
        try:
            if stat.S_IMODE(directory.stat().st_mode) != 0o700:
                os.chmod(directory, 0o700)
        except OSError:
            pass


def _atomic_write(path: Path, payload: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".tmp-", suffix=".partial", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            if _POSIX:
                os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)


def _fsync_directory(directory: Path) -> None:
    if not _POSIX:
        return
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
