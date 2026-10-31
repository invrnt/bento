from __future__ import annotations

import asyncio
import hashlib
import os
import struct
import tracemalloc
from pathlib import Path

import pytest

from bento.adapters.security import LocalAesGcmEncryptionAdapter, StreamingBlobCipher, VaultCrypto
from bento.adapters.security.stream_aead import HEADER_SIZE
from bento.domain.errors import IntegrityError, ValidationFailedError
from bento.domain.security import BlobCipherParams, VaultKeyring
from tests.unit.security.crypto_support import flip_bit

SEGMENT = 4096


def _keyring() -> VaultKeyring:
    return VaultKeyring(vault_id="vlt_test", current_epoch=1, keys={1: b"\x11" * 32, 2: b"\x22" * 32})


def _params(segment_size: int = SEGMENT, epoch: int = 1) -> BlobCipherParams:
    return BlobCipherParams(
        epoch=epoch, file_salt=bytes(range(16)), nonce_prefix=b"\xa0" * 7, segment_size=segment_size
    )


def _encrypt_bytes(tmp_path: Path, plaintext: bytes, params: BlobCipherParams, name: str = "blob") -> bytes:
    source = tmp_path / f"{name}.plain"
    source.write_bytes(plaintext)
    destination = tmp_path / f"{name}.bnt2"
    cipher = StreamingBlobCipher()
    result = asyncio.run(cipher.encrypt_file(source, destination, keyring=_keyring(), params=params))
    ciphertext = destination.read_bytes()
    assert result.ciphertext_size == len(ciphertext)
    return ciphertext


def _range(ciphertext: bytes, start: int, length: int, keyring: VaultKeyring | None = None) -> bytes:
    async def read(offset: int, size: int) -> bytes:
        return ciphertext[offset : offset + size]

    return asyncio.run(
        StreamingBlobCipher().decrypt_range(
            read, ciphertext_size=len(ciphertext), start=start, length=length, keyring=keyring or _keyring()
        )
    )


@pytest.mark.parametrize(
    ("size", "segment_size"),
    [
        (0, SEGMENT),
        (1, SEGMENT),
        (SEGMENT - 1, SEGMENT),
        (SEGMENT, SEGMENT),
        (SEGMENT + 1, SEGMENT),
        (3 * SEGMENT, SEGMENT),
        (5 * SEGMENT + 123, SEGMENT),
        (0, 1024 * 1024),
        (1024 * 1024, 1024 * 1024),
        (3 * 1024 * 1024 + 4321, 1024 * 1024),
    ],
)
def test_round_trip_for_many_sizes(tmp_path: Path, size: int, segment_size: int) -> None:
    plaintext = os.urandom(size)
    source = tmp_path / "plain"
    source.write_bytes(plaintext)
    cipher = StreamingBlobCipher(segment_size=segment_size)
    keyring = _keyring()
    params = cipher.new_params(keyring)

    result = asyncio.run(cipher.encrypt_file(source, tmp_path / "enc", keyring=keyring, params=params))
    ciphertext = (tmp_path / "enc").read_bytes()
    digest = asyncio.run(cipher.decrypt_file(tmp_path / "enc", tmp_path / "out", keyring=keyring))

    expected_sha = hashlib.sha256(plaintext).hexdigest()
    assert (tmp_path / "out").read_bytes() == plaintext
    assert digest == expected_sha == result.plaintext_sha256
    assert result.plaintext_size == size
    assert result.params == params
    assert len(ciphertext) == result.ciphertext_size == cipher.ciphertext_size(size, segment_size)
    segments = max(1, -(-size // segment_size))
    assert len(ciphertext) == HEADER_SIZE + size + 16 * segments
    if size >= 16:
        assert plaintext[:64] not in ciphertext
    assert not list(tmp_path.glob("*.partial"))


def test_header_layout_matches_spec(tmp_path: Path) -> None:
    params = BlobCipherParams(epoch=2, file_salt=b"S" * 16, nonce_prefix=b"N" * 7, segment_size=8192)
    ciphertext = _encrypt_bytes(tmp_path, b"hello", params)
    magic, version, epoch, salt, segment_size, prefix = struct.unpack(">4sBI16sI7s", ciphertext[:36])
    assert (magic, version, epoch, salt, segment_size, prefix) == (b"BNT2", 2, 2, b"S" * 16, 8192, b"N" * 7)
    assert len(ciphertext) == 36 + 5 + 16


def test_encryption_is_deterministic_for_identical_params(tmp_path: Path) -> None:
    plaintext = os.urandom(3 * SEGMENT + 77)
    first = _encrypt_bytes(tmp_path, plaintext, _params(), "a")
    second = _encrypt_bytes(tmp_path, plaintext, _params(), "b")
    other_salt = BlobCipherParams(epoch=1, file_salt=b"\x01" * 16, nonce_prefix=b"\xa0" * 7, segment_size=SEGMENT)
    third = _encrypt_bytes(tmp_path, plaintext, other_salt, "c")
    assert first == second
    assert third != first


def test_new_params_are_random_and_use_current_epoch() -> None:
    keyring = VaultCrypto().rotate_keyring(_keyring())
    cipher = StreamingBlobCipher()
    first, second = cipher.new_params(keyring), cipher.new_params(keyring)
    assert first.epoch == second.epoch == keyring.current_epoch == 3
    assert first.file_salt != second.file_salt
    assert first.nonce_prefix != second.nonce_prefix
    assert first.segment_size == 1024 * 1024


def test_old_epoch_blobs_decrypt_after_rotation(tmp_path: Path) -> None:
    ciphertext = _encrypt_bytes(tmp_path, b"epoch one", _params(epoch=1))
    (tmp_path / "old.bnt2").write_bytes(ciphertext)
    rotated = VaultCrypto().rotate_keyring(_keyring())
    asyncio.run(StreamingBlobCipher().decrypt_file(tmp_path / "old.bnt2", tmp_path / "out", keyring=rotated))
    assert (tmp_path / "out").read_bytes() == b"epoch one"


def test_every_single_bit_flip_fails(tmp_path: Path) -> None:
    plaintext = os.urandom(SEGMENT + 10)
    ciphertext = _encrypt_bytes(tmp_path, plaintext, _params())
    keyring = _keyring()
    cipher = StreamingBlobCipher()

    async def scenario() -> int:
        failures = 0
        for bit in range(len(ciphertext) * 8):
            mutated = flip_bit(ciphertext, bit)

            async def read(offset: int, size: int, data: bytes = mutated) -> bytes:
                return data[offset : offset + size]

            with pytest.raises(IntegrityError):
                await cipher.decrypt_range(
                    read, ciphertext_size=len(mutated), start=0, length=len(plaintext), keyring=keyring
                )
            failures += 1
        return failures

    assert asyncio.run(scenario()) == len(ciphertext) * 8


def test_bit_flips_fail_full_file_decryption_and_leave_no_output(tmp_path: Path) -> None:
    ciphertext = _encrypt_bytes(tmp_path, os.urandom(SEGMENT + 3), _params())
    tampered = tmp_path / "tampered.bnt2"
    output = tmp_path / "out"
    cipher = StreamingBlobCipher()

    async def scenario() -> None:
        for position in range(len(ciphertext)):
            tampered.write_bytes(flip_bit(ciphertext, position * 8 + position % 8))
            with pytest.raises(IntegrityError):
                await cipher.decrypt_file(tampered, output, keyring=_keyring())
            assert not output.exists()

    asyncio.run(scenario())
    assert not list(tmp_path.glob("*.partial"))


def test_truncation_extension_and_segment_swaps_fail(tmp_path: Path) -> None:
    plaintext = os.urandom(3 * SEGMENT)
    ciphertext = _encrypt_bytes(tmp_path, plaintext, _params())
    stride = SEGMENT + 16
    segments = [ciphertext[36 + index * stride : 36 + (index + 1) * stride] for index in range(3)]
    header = ciphertext[:36]
    other = _encrypt_bytes(tmp_path, plaintext, BlobCipherParams(1, b"\x09" * 16, b"\xa0" * 7, SEGMENT), "other")

    candidates = {
        "truncate_last_segment": ciphertext[:-stride],
        "truncate_one_byte": ciphertext[:-1],
        "truncate_tag": ciphertext[:-16],
        "header_only": header,
        "partial_header": ciphertext[:20],
        "empty": b"",
        "extend_one_byte": ciphertext + b"\x00",
        "extend_tag_sized": ciphertext + bytes(16),
        "extend_duplicate_segment": ciphertext + segments[2],
        "swap_first_two": header + segments[1] + segments[0] + segments[2],
        "swap_last_two": header + segments[0] + segments[2] + segments[1],
        "duplicate_first": header + segments[0] + segments[0] + segments[2],
        "foreign_header": other[:36] + b"".join(segments),
        "foreign_segment": header + other[36 : 36 + stride] + segments[1] + segments[2],
    }
    for truncated_length in (*range(0, 40), *range(40, len(ciphertext), 97)):
        candidates[f"truncate_{truncated_length}"] = ciphertext[:truncated_length]

    path = tmp_path / "candidate"
    cipher = StreamingBlobCipher()

    async def scenario() -> None:
        for name, candidate in candidates.items():
            path.write_bytes(candidate)
            with pytest.raises(IntegrityError):
                await cipher.decrypt_file(path, tmp_path / "out", keyring=_keyring())
            assert not (tmp_path / "out").exists(), name

    asyncio.run(scenario())


def test_empty_blob_truncated_to_header_or_extended_fails(tmp_path: Path) -> None:
    ciphertext = _encrypt_bytes(tmp_path, b"", _params())
    assert len(ciphertext) == 52
    for candidate in (ciphertext[:36], ciphertext[:-1], ciphertext + ciphertext[36:]):
        (tmp_path / "c").write_bytes(candidate)
        with pytest.raises(IntegrityError):
            asyncio.run(StreamingBlobCipher().decrypt_file(tmp_path / "c", tmp_path / "out", keyring=_keyring()))


def test_unknown_epoch_and_wrong_vault_fail_closed(tmp_path: Path) -> None:
    ciphertext = _encrypt_bytes(tmp_path, b"secret", _params(epoch=2))
    (tmp_path / "c").write_bytes(ciphertext)
    cipher = StreamingBlobCipher()
    only_epoch_one = VaultKeyring(vault_id="vlt_test", current_epoch=1, keys={1: b"\x11" * 32})
    other_vault = VaultKeyring(vault_id="vlt_other", current_epoch=1, keys={1: b"\x11" * 32, 2: b"\x22" * 32})
    with pytest.raises(IntegrityError) as unknown:
        asyncio.run(cipher.decrypt_file(tmp_path / "c", tmp_path / "out", keyring=only_epoch_one))
    assert unknown.value.details == {"what": "blob_epoch"}
    with pytest.raises(IntegrityError):
        asyncio.run(cipher.decrypt_file(tmp_path / "c", tmp_path / "out", keyring=other_vault))


@pytest.mark.parametrize(
    ("start", "length"),
    [
        (0, 0),
        (0, 1),
        (SEGMENT - 5, 10),
        (SEGMENT - 1, 2),
        (SEGMENT, SEGMENT),
        (SEGMENT - 1, SEGMENT + 2),
        (2 * SEGMENT + 7, 3 * SEGMENT),
        (5 * SEGMENT, 123),
        (5 * SEGMENT + 122, 1),
        (0, 5 * SEGMENT + 123),
    ],
)
def test_range_decryption_equals_plaintext_slice(tmp_path: Path, start: int, length: int) -> None:
    plaintext = os.urandom(5 * SEGMENT + 123)
    ciphertext = _encrypt_bytes(tmp_path, plaintext, _params())
    assert _range(ciphertext, start, length) == plaintext[start : start + length]


def test_range_decryption_reads_only_needed_segments(tmp_path: Path) -> None:
    plaintext = os.urandom(6 * SEGMENT + 50)
    ciphertext = _encrypt_bytes(tmp_path, plaintext, _params())
    reads: list[tuple[int, int]] = []

    async def read(offset: int, size: int) -> bytes:
        reads.append((offset, size))
        return ciphertext[offset : offset + size]

    start, length = 2 * SEGMENT + 10, SEGMENT
    result = asyncio.run(
        StreamingBlobCipher().decrypt_range(
            read, ciphertext_size=len(ciphertext), start=start, length=length, keyring=_keyring()
        )
    )
    stride = SEGMENT + 16
    assert result == plaintext[start : start + length]
    assert reads == [(0, 36), (36 + 2 * stride, stride), (36 + 3 * stride, stride)]

    reads.clear()
    tail = asyncio.run(
        StreamingBlobCipher().decrypt_range(
            read, ciphertext_size=len(ciphertext), start=6 * SEGMENT + 40, length=10, keyring=_keyring()
        )
    )
    assert tail == plaintext[-10:]
    assert reads == [(0, 36), (36 + 6 * stride, 50 + 16)]


def test_range_validation(tmp_path: Path) -> None:
    plaintext = os.urandom(SEGMENT + 1)
    ciphertext = _encrypt_bytes(tmp_path, plaintext, _params())
    for start, length in ((-1, 1), (0, -1), (SEGMENT, 2), (SEGMENT + 2, 0)):
        with pytest.raises(ValidationFailedError):
            _range(ciphertext, start, length)
    with pytest.raises(IntegrityError):
        asyncio.run(
            StreamingBlobCipher().decrypt_range(
                _reader(ciphertext), ciphertext_size=len(ciphertext) + 16, start=SEGMENT, length=1, keyring=_keyring()
            )
        )


def test_range_rejects_short_reads(tmp_path: Path) -> None:
    ciphertext = _encrypt_bytes(tmp_path, os.urandom(2 * SEGMENT), _params())

    async def short_read(offset: int, size: int) -> bytes:
        return ciphertext[offset : offset + max(0, size - 1)] if offset else ciphertext[:size]

    with pytest.raises(IntegrityError):
        asyncio.run(
            StreamingBlobCipher().decrypt_range(
                short_read, ciphertext_size=len(ciphertext), start=0, length=10, keyring=_keyring()
            )
        )


def test_legacy_v1_files_stay_decryptable(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = tmp_path / "legacy.txt"
        content = os.urandom(2 * 1024 * 1024 + 9)
        source.write_bytes(content)
        legacy = LocalAesGcmEncryptionAdapter(key=b"k" * 32, key_id="primary", temp_dir=tmp_path / "legacy")
        encrypted, _metadata = await legacy.encrypt(str(source))
        cipher = StreamingBlobCipher(legacy_keys={"primary": b"k" * 32})

        digest = await cipher.decrypt_file(Path(encrypted), tmp_path / "out", keyring=_keyring())
        assert digest == hashlib.sha256(content).hexdigest()
        assert (tmp_path / "out").read_bytes() == content

        with pytest.raises(ValidationFailedError, match="key is not available"):
            await StreamingBlobCipher().decrypt_file(Path(encrypted), tmp_path / "out2", keyring=_keyring())

        payload = bytearray(Path(encrypted).read_bytes())
        payload[len(payload) // 2] ^= 1
        tampered = tmp_path / "tampered.bento"
        tampered.write_bytes(payload)
        with pytest.raises(IntegrityError):
            await cipher.decrypt_file(tampered, tmp_path / "out3", keyring=_keyring())
        assert not (tmp_path / "out3").exists()

        tampered.write_bytes(Path(encrypted).read_bytes()[:15])
        with pytest.raises(IntegrityError):
            await cipher.decrypt_file(tampered, tmp_path / "out4", keyring=_keyring())

        with pytest.raises(ValidationFailedError, match="format v2"):
            await cipher.decrypt_range(
                _reader(Path(encrypted).read_bytes()),
                ciphertext_size=Path(encrypted).stat().st_size,
                start=0,
                length=1,
                keyring=_keyring(),
            )

    asyncio.run(scenario())


def test_existing_destination_is_untouched_on_failure(tmp_path: Path) -> None:
    ciphertext = _encrypt_bytes(tmp_path, b"payload", _params())
    (tmp_path / "bad").write_bytes(flip_bit(ciphertext, 400))
    destination = tmp_path / "dest"
    destination.write_bytes(b"previous")
    with pytest.raises(IntegrityError):
        asyncio.run(StreamingBlobCipher().decrypt_file(tmp_path / "bad", destination, keyring=_keyring()))
    assert destination.read_bytes() == b"previous"


def test_parameter_validation() -> None:
    cipher = StreamingBlobCipher()
    with pytest.raises(ValidationFailedError):
        cipher.ciphertext_size(-1)
    with pytest.raises(ValidationFailedError):
        cipher.ciphertext_size(10, 1024)
    with pytest.raises(ValidationFailedError):
        StreamingBlobCipher(segment_size=1024)
    with pytest.raises(ValidationFailedError):
        StreamingBlobCipher(legacy_keys={"primary": b"short"})
    assert cipher.ciphertext_size(0) == 52
    assert cipher.ciphertext_size(1024 * 1024) == 36 + 1024 * 1024 + 16
    assert cipher.ciphertext_size(1024 * 1024 + 1) == 36 + 1024 * 1024 + 1 + 32


def test_unknown_params_epoch_is_rejected_on_encrypt(tmp_path: Path) -> None:
    (tmp_path / "p").write_bytes(b"x")
    with pytest.raises(ValidationFailedError):
        asyncio.run(
            StreamingBlobCipher().encrypt_file(
                tmp_path / "p", tmp_path / "c", keyring=_keyring(), params=_params(epoch=9)
            )
        )
    assert not (tmp_path / "c").exists()


def test_streams_large_sparse_file_in_constant_memory(tmp_path: Path) -> None:
    size = 64 * 1024 * 1024 + 17
    source = tmp_path / "sparse.bin"
    with source.open("wb") as handle:
        handle.truncate(size)
    cipher = StreamingBlobCipher()
    keyring = _keyring()

    tracemalloc.start()
    try:
        result = asyncio.run(
            cipher.encrypt_file(source, tmp_path / "sparse.bnt2", keyring=keyring, params=cipher.new_params(keyring))
        )
        _current, encrypt_peak = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        digest = asyncio.run(cipher.decrypt_file(tmp_path / "sparse.bnt2", tmp_path / "sparse.out", keyring=keyring))
        _current, decrypt_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    expected = hashlib.sha256()
    chunk = bytes(1024 * 1024)
    for _ in range(64):
        expected.update(chunk)
    expected.update(bytes(17))
    assert result.plaintext_sha256 == digest == expected.hexdigest()
    assert (tmp_path / "sparse.out").stat().st_size == size
    assert encrypt_peak < 8 * 1024 * 1024
    assert decrypt_peak < 8 * 1024 * 1024


def test_repr_hides_legacy_keys() -> None:
    cipher = StreamingBlobCipher(legacy_keys={"primary": b"K" * 32})
    assert "KKKK" not in repr(cipher)
    assert "primary" in repr(cipher)


def _reader(data: bytes):
    async def read(offset: int, size: int) -> bytes:
        return data[offset : offset + size]

    return read


def test_expected_header_digest_is_checked_before_any_segment(tmp_path: Path) -> None:
    from bento.adapters.security.primitives import b64url_encode

    cipher = StreamingBlobCipher(segment_size=4096)
    keyring = VaultCrypto().generate_keyring("vlt_digest")
    source = tmp_path / "plain.bin"
    source.write_bytes(b"x" * 10_000)
    params = cipher.new_params(keyring)
    ciphertext = tmp_path / "cipher.bin"
    asyncio.run(cipher.encrypt_file(source, ciphertext, keyring=keyring, params=params))
    data = ciphertext.read_bytes()
    digest = cipher.header_digest(params)
    assert digest == b64url_encode(hashlib.sha256(data[:HEADER_SIZE]).digest())

    async def read(offset: int, length: int) -> bytes:
        return data[offset : offset + length]

    assert asyncio.run(cipher.decrypt_range(read, ciphertext_size=len(data), start=5, length=5, keyring=keyring, expected_header_sha256=digest)) == b"xxxxx"
    for wrong in ("A" * 43, "ñ"):
        with pytest.raises(IntegrityError):
            asyncio.run(cipher.decrypt_range(read, ciphertext_size=len(data), start=5, length=5, keyring=keyring, expected_header_sha256=wrong))
        with pytest.raises(IntegrityError):
            asyncio.run(cipher.decrypt_file(ciphertext, tmp_path / "out.bin", keyring=keyring, expected_header_sha256=wrong))
    assert asyncio.run(cipher.decrypt_file(ciphertext, tmp_path / "out.bin", keyring=keyring, expected_header_sha256=digest))
