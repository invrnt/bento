from __future__ import annotations

import asyncio
import base64
import os
import stat
import threading
from pathlib import Path

import pytest

from bento.adapters.security import InMemoryKeyStore, WrappedFileKeyStore, load_wrapping_key
from bento.adapters.security import key_store as key_store_module
from bento.adapters.security.primitives import b64url_encode
from bento.domain.errors import IntegrityError, ValidationFailedError
from bento.ports.key_store import DEVICE_IDENTITY, TELEGRAM_SESSION, VAULT_KEYRING

POSIX = os.name == "posix"
WRAPPING_KEY = b"\x42" * 32


def _store(tmp_path: Path, key: bytes = WRAPPING_KEY) -> WrappedFileKeyStore:
    return WrappedFileKeyStore(tmp_path / "secure", key)


def test_put_get_delete_round_trip(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = _store(tmp_path)
        assert await store.get(VAULT_KEYRING) is None
        await store.put(VAULT_KEYRING, b"keyring secret")
        await store.put(TELEGRAM_SESSION, b"session string")
        await store.put(DEVICE_IDENTITY, b"")
        assert await store.get(VAULT_KEYRING) == b"keyring secret"
        assert await store.get(TELEGRAM_SESSION) == b"session string"
        assert await store.get(DEVICE_IDENTITY) == b""
        await store.delete(VAULT_KEYRING)
        await store.delete(VAULT_KEYRING)
        assert await store.get(VAULT_KEYRING) is None
        assert sorted(path.name for path in (tmp_path / "secure").iterdir()) == [
            "device.identity.bin",
            "telegram.session.bin",
        ]

    asyncio.run(scenario())


def test_files_are_encrypted_and_layout_is_stable(tmp_path: Path) -> None:
    asyncio.run(_store(tmp_path).put("vault.keyring", b"plaintext secret value"))
    payload = (tmp_path / "secure" / "vault.keyring.bin").read_bytes()
    assert payload[:4] == b"BKEY" and payload[4] == 1
    assert len(payload) == 4 + 1 + 12 + len(b"plaintext secret value") + 16
    assert b"plaintext secret value" not in payload


@pytest.mark.skipif(not POSIX, reason="POSIX permissions")
def test_file_and_directory_permissions(tmp_path: Path) -> None:
    asyncio.run(_store(tmp_path).put("vault.keyring", b"secret"))
    assert stat.S_IMODE((tmp_path / "secure").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "secure" / "vault.keyring.bin").stat().st_mode) == 0o600
    os.chmod(tmp_path / "secure", 0o755)
    asyncio.run(_store(tmp_path).put("vault.keyring", b"secret 2"))
    assert stat.S_IMODE((tmp_path / "secure").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "secure" / "vault.keyring.bin").stat().st_mode) == 0o600


def test_wrong_wrapping_key_fails_closed(tmp_path: Path) -> None:
    asyncio.run(_store(tmp_path).put("vault.keyring", b"secret"))
    with pytest.raises(IntegrityError):
        asyncio.run(_store(tmp_path, b"\x43" * 32).get("vault.keyring"))


def test_tampered_or_swapped_files_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    asyncio.run(store.put("vault.keyring", b"keyring"))
    asyncio.run(store.put("telegram.session", b"session"))
    directory = tmp_path / "secure"
    original = (directory / "vault.keyring.bin").read_bytes()

    for index in range(len(original)):
        mutated = bytearray(original)
        mutated[index] ^= 0x01
        (directory / "vault.keyring.bin").write_bytes(bytes(mutated))
        with pytest.raises(IntegrityError):
            asyncio.run(store.get("vault.keyring"))
    for candidate in (b"", original[:20], original + b"\x00"):
        (directory / "vault.keyring.bin").write_bytes(candidate)
        with pytest.raises(IntegrityError):
            asyncio.run(store.get("vault.keyring"))

    (directory / "vault.keyring.bin").write_bytes((directory / "telegram.session.bin").read_bytes())
    with pytest.raises(IntegrityError):
        asyncio.run(store.get("vault.keyring"))


def test_atomic_overwrite_and_failed_write_keeps_previous_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    asyncio.run(store.put("vault.keyring", b"first"))
    asyncio.run(store.put("vault.keyring", b"second"))
    assert asyncio.run(store.get("vault.keyring")) == b"second"

    def broken_replace(source: str, destination: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(key_store_module.os, "replace", broken_replace)
    with pytest.raises(OSError):
        asyncio.run(store.put("vault.keyring", b"third"))
    monkeypatch.undo()
    assert asyncio.run(store.get("vault.keyring")) == b"second"
    assert sorted(path.name for path in (tmp_path / "secure").iterdir()) == ["vault.keyring.bin"]


def test_concurrent_writers_leave_one_complete_value(tmp_path: Path) -> None:
    store = _store(tmp_path)

    async def scenario() -> None:
        values = [bytes([index]) * 4096 for index in range(16)]
        await asyncio.gather(*(store.put("telegram.session", value) for value in values))
        assert await store.get("telegram.session") in values

    asyncio.run(scenario())
    assert sorted(path.name for path in (tmp_path / "secure").iterdir()) == ["telegram.session.bin"]


@pytest.mark.parametrize(
    "name",
    ["", "Vault", "a/b", "../escape", "a\\b", "abc\n", "a" * 65, "name with space", "ñ", "a:b", None],
)
def test_invalid_names_are_rejected(tmp_path: Path, name: str) -> None:
    store = _store(tmp_path)
    memory = InMemoryKeyStore()
    for operation in (
        lambda target: target.get(name),
        lambda target: target.put(name, b"x"),
        lambda target: target.delete(name),
    ):
        for target in (store, memory):
            with pytest.raises(ValidationFailedError):
                asyncio.run(operation(target))
    assert not (tmp_path / "secure").exists()


def test_valid_name_edge_cases(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for name in ("a", "a" * 64, "pairing.pending", "x-y_z.9"):
        asyncio.run(store.put(name, name.encode()))
        assert asyncio.run(store.get(name)) == name.encode()


def test_values_must_be_bytes_and_wrapping_key_must_be_32_bytes(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailedError):
        asyncio.run(_store(tmp_path).put("vault.keyring", "text"))  # type: ignore[arg-type]
    with pytest.raises(ValidationFailedError):
        WrappedFileKeyStore(tmp_path, b"short")


def test_in_memory_key_store() -> None:
    async def scenario() -> None:
        store = InMemoryKeyStore({"vault.keyring": b"initial"})
        assert await store.get("vault.keyring") == b"initial"
        await store.put("telegram.session", bytearray(b"session"))
        assert await store.get("telegram.session") == b"session"
        await store.delete("vault.keyring")
        await store.delete("missing")
        assert store.names() == ("telegram.session",)
        assert "session" not in repr(store).replace("telegram.session", "")

    asyncio.run(scenario())


def test_reprs_hide_wrapping_key(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert "BBBB" not in repr(store) and repr(WRAPPING_KEY) not in repr(store)
    loaded = load_wrapping_key({"BENTO_DEVICE_WRAPPING_KEY": b64url_encode(WRAPPING_KEY)}, tmp_path)
    assert b64url_encode(WRAPPING_KEY) not in repr(loaded)
    assert repr(WRAPPING_KEY) not in repr(loaded)


# load_wrapping_key


def test_wrapping_key_from_environment(tmp_path: Path) -> None:
    unpadded = b64url_encode(WRAPPING_KEY)
    padded = base64.urlsafe_b64encode(WRAPPING_KEY).decode()
    for value in (unpadded, padded, f"  {unpadded}\n"):
        loaded = load_wrapping_key({"BENTO_DEVICE_WRAPPING_KEY": value}, tmp_path)
        assert loaded.key == WRAPPING_KEY
        assert loaded.file_based is False
        assert loaded.path is None
    assert not (tmp_path / "secure").exists()


@pytest.mark.parametrize("value", ["not-base64!", b64url_encode(b"x" * 31), b64url_encode(b"x" * 33), "Zq9"])
def test_invalid_environment_wrapping_key_fails_closed(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValidationFailedError) as caught:
        load_wrapping_key({"BENTO_DEVICE_WRAPPING_KEY": value}, tmp_path)
    assert value not in str(caught.value)
    assert value not in str(caught.value.details)
    assert not (tmp_path / "secure").exists()


def test_wrapping_key_file_is_created_once_and_reused(tmp_path: Path) -> None:
    first = load_wrapping_key({}, tmp_path)
    second = load_wrapping_key({"BENTO_DEVICE_WRAPPING_KEY": "   "}, tmp_path)
    path = tmp_path / "secure" / "wrapping.key"
    assert first.file_based is True and first.path == path
    assert len(first.key) == 32
    assert second.key == first.key
    assert path.read_text().strip() == b64url_encode(first.key)
    if POSIX:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        os.chmod(path, 0o644)
        load_wrapping_key({}, tmp_path)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert sorted(entry.name for entry in path.parent.iterdir()) == ["wrapping.key"]


def test_corrupt_wrapping_key_file_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "secure" / "wrapping.key"
    path.parent.mkdir(parents=True)
    for content in (b"", b"short", b"\xff\xfe", b64url_encode(b"x" * 16).encode()):
        path.write_bytes(content)
        with pytest.raises(ValidationFailedError):
            load_wrapping_key({}, tmp_path)
        assert path.read_bytes() == content


def test_concurrent_first_start_agrees_on_one_key(tmp_path: Path) -> None:
    barrier = threading.Barrier(8)
    results: list[bytes] = []
    errors: list[BaseException] = []

    def worker() -> None:
        barrier.wait()
        try:
            results.append(load_wrapping_key({}, tmp_path).key)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(set(results)) == 1
    assert sorted(entry.name for entry in (tmp_path / "secure").iterdir()) == ["wrapping.key"]


def test_wrapped_store_works_with_file_based_key(tmp_path: Path) -> None:
    loaded = load_wrapping_key({}, tmp_path)
    store = WrappedFileKeyStore(tmp_path / "secure", loaded.key)
    asyncio.run(store.put("device.identity", b"identity"))
    reopened = WrappedFileKeyStore(tmp_path / "secure", load_wrapping_key({}, tmp_path).key)
    assert asyncio.run(reopened.get("device.identity")) == b"identity"
