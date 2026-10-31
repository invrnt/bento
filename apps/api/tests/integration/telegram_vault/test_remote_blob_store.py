from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from bento.adapters.storage.telegram_vault_blob_store import (
    MAX_PART_BYTES,
    PREMIUM_MAX_PART_BYTES,
    RemoteBlobUpload,
    SQLiteUploadSessionStore,
    UploadState,
    map_ciphertext_range,
    part_size_limit,
)
from bento.domain.assets import AssetMetadata
from bento.domain.errors import IntegrityError, ValidationFailedError, VaultLockedError
from bento.domain.security import EncryptionMode
from bento.domain.storage import BlobKind, BlobPart, StorageBackend
from bento.domain.telegram import RemotePart
from bento.domain.vault import VaultLayout
from tests.integration.telegram_vault.support import VaultDevice, make_vault_device

MIB = 1024 * 1024


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


async def _ready_device(tmp_path: Path) -> VaultDevice:
    device = make_vault_device(tmp_path, tmp_path / "cloud", "desk")
    await device.sign_in()
    await device.vault.create()
    return device


def _source(tmp_path: Path, size: int, name: str = "video.mp4") -> tuple[Path, AssetMetadata]:
    path = tmp_path / name
    data = os.urandom(size)
    path.write_bytes(data)
    metadata = AssetMetadata(
        original_filename=name, mime_type="video/mp4", size_bytes=size, sha256=hashlib.sha256(data).hexdigest()
    )
    return path, metadata


class CrashingParts:
    """Delegates to the fake part store but fails the n-th upload, like a crash mid-transfer."""

    def __init__(self, inner: object, *, fail_at: int | None = None) -> None:
        self.inner = inner
        self.fail_at = fail_at
        self.uploads = 0

    async def upload_part(self, layout: VaultLayout, source: Path, *, filename: str) -> RemotePart:
        self.uploads += 1
        if self.fail_at is not None and self.uploads == self.fail_at:
            raise ConnectionError("network vanished mid-part")
        return await self.inner.upload_part(layout, source, filename=filename)  # type: ignore[attr-defined]

    def __getattr__(self, name: str) -> object:
        return getattr(self.inner, name)


class AlbumParts(CrashingParts):
    def __init__(self, inner: object) -> None:
        super().__init__(inner)
        self.albums: list[list[str]] = []

    async def upload_parts(self, layout: VaultLayout, items: Sequence[tuple[Path, str]]) -> tuple[RemotePart, ...]:
        self.albums.append([name for _, name in items])
        return tuple([await self.inner.upload_part(layout, path, filename=name) for path, name in items])  # type: ignore[attr-defined]


def test_round_trip_in_parts_with_v2_metadata(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = await _ready_device(tmp_path)
        store = device.blob_store(part_size_bytes=96 * 1024)
        path, metadata = _source(tmp_path, 300_000)

        ref = await store.store(str(path), asset_id="asset_1", kind=BlobKind.ORIGINAL, metadata=metadata)

        assert ref.backend == StorageBackend.TELEGRAM and ref.size_bytes == 300_000 and ref.sha256 == metadata.sha256
        assert ref.encryption.mode == EncryptionMode.AES_GCM_STREAM
        assert ref.encryption.format_version == 2 and ref.encryption.key_epoch == 1
        assert [part.index for part in ref.parts] == [0, 1, 2, 3]
        assert [part.size_bytes for part in ref.parts][:3] == [96 * 1024] * 3
        layout = (await device.vault.require()).layout
        documents = [message for message in device.cloud.read_chat(layout.files_channel_id)[1] if message.media]
        assert len(documents) == 4
        assert all(message.media.filename.endswith(".bpart") for message in documents)
        assert all(metadata.original_filename not in message.media.filename for message in documents)
        # Telegram only ever holds ciphertext.
        stored = b"".join(device.cloud.document_path(layout.files_channel_id, message.id).read_bytes() for message in documents)
        assert path.read_bytes()[:64] not in stored and stored[:4] == b"BNT2"

        destination = tmp_path / "restored.mp4"
        assert await store.download(ref, destination) == destination
        assert destination.read_bytes() == path.read_bytes()
        assert await store.probe() is True

    run(scenario())


def test_upload_resumes_after_a_crash_mid_part_with_identical_ciphertext(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = await _ready_device(tmp_path)
        path, metadata = _source(tmp_path, 250_000)
        crashing = CrashingParts(device.runtime.parts, fail_at=3)
        store = device.blob_store(parts=crashing, part_size_bytes=64 * 1024)

        with pytest.raises(ConnectionError):
            await store.store(str(path), asset_id="asset_1", kind=BlobKind.ORIGINAL, metadata=metadata)
        sessions = SQLiteUploadSessionStore(device.sessions)
        [row] = _session_rows(device)
        interrupted = await sessions.get(row)
        assert interrupted is not None and interrupted.state == UploadState.UPLOADING
        assert len(interrupted.completed_parts) == 2 and interrupted.asset_id == "asset_1"
        assert interrupted.blob_kind == BlobKind.ORIGINAL

        resumed = device.blob_store(parts=CrashingParts(device.runtime.parts), part_size_bytes=64 * 1024)
        ref = await resumed.store(str(path), asset_id="asset_1", kind=BlobKind.ORIGINAL, metadata=metadata)

        assert ref.id == interrupted.blob_ref_id
        assert [part.remote() for part in ref.parts[:2]] == list(interrupted.completed_parts)
        layout = (await device.vault.require()).layout
        documents = [message for message in device.cloud.read_chat(layout.files_channel_id)[1] if message.media]
        assert len(documents) == len(ref.parts) == 4  # completed parts were not uploaded again
        restored = tmp_path / "restored.bin"
        await resumed.download(ref, restored)
        assert restored.read_bytes() == path.read_bytes()
        assert (await sessions.get(row)).state == UploadState.COMPLETED  # type: ignore[union-attr]
        # A retry after the upload finished returns the same ref without uploading anything.
        again = await resumed.store(str(path), asset_id="asset_1", kind=BlobKind.ORIGINAL, metadata=metadata)
        assert again == ref
        assert len([message for message in device.cloud.read_chat(layout.files_channel_id)[1] if message.media]) == 4

    run(scenario())


def test_changed_source_or_epoch_never_reuses_saved_nonces(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = await _ready_device(tmp_path)
        path, metadata = _source(tmp_path, 200_000)
        store = device.blob_store(parts=CrashingParts(device.runtime.parts, fail_at=2), part_size_bytes=64 * 1024)
        with pytest.raises(ConnectionError):
            await store.store(str(path), asset_id="asset_1", kind=BlobKind.ORIGINAL, metadata=metadata)

        # The bytes on disk no longer match what the blob ref describes.
        path.write_bytes(os.urandom(200_000))
        with pytest.raises(ValidationFailedError):
            await device.blob_store().store(str(path), asset_id="asset_1", kind=BlobKind.ORIGINAL, metadata=metadata)

        # After a key rotation the half-done upload restarts under the new epoch and its old parts are deleted.
        path, metadata = _source(tmp_path, 200_000, "other.mp4")
        with pytest.raises(ConnectionError):
            await device.blob_store(parts=CrashingParts(device.runtime.parts, fail_at=2), part_size_bytes=64 * 1024).store(
                str(path), asset_id="asset_2", kind=BlobKind.ORIGINAL, metadata=metadata
            )
        context = await device.vault.require()
        layout = context.layout
        before = {message.id for message in device.cloud.read_chat(layout.files_channel_id)[1] if message.media}
        await device.vault.update_keyring(device.crypto.rotate_keyring(context.keyring))

        ref = await device.blob_store(part_size_bytes=64 * 1024).store(
            str(path), asset_id="asset_2", kind=BlobKind.ORIGINAL, metadata=metadata
        )

        assert ref.encryption.key_epoch == 2
        after = {message.id for message in device.cloud.read_chat(layout.files_channel_id)[1] if message.media}
        assert {int(part.message_id) for part in ref.parts} <= after
        assert len(before - after) == 1  # the stale epoch-1 part of asset_2 is gone

    run(scenario())


def test_range_reads_decrypt_only_the_needed_segments(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = await _ready_device(tmp_path)
        store = device.blob_store(part_size_bytes=700 * 1024)
        path, metadata = _source(tmp_path, int(2.5 * MIB))
        ref = await store.store(str(path), asset_id="asset_1", kind=BlobKind.ORIGINAL, metadata=metadata)
        plaintext = path.read_bytes()
        assert len(ref.parts) == 4

        for start, length in [(0, 10), (MIB - 5, 10), (700 * 1024 - 3, 9), (2 * MIB, 4096), (len(plaintext) - 7, 7)]:
            assert await store.read_range(ref, start, length) == plaintext[start : start + length]
        assert await store.read_range(ref, len(plaintext) - 3, 100) == plaintext[-3:]
        assert await store.read_range(ref, len(plaintext) + 10, 5) == b""
        assert await store.read_range(ref, 5, 0) == b""
        with pytest.raises(ValidationFailedError):
            await store.read_range(ref, -1, 4)

    run(scenario())


def test_delete_ref_removes_every_part_and_the_session(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = await _ready_device(tmp_path)
        store = device.blob_store(part_size_bytes=64 * 1024)
        path, metadata = _source(tmp_path, 150_000)
        ref = await store.store(str(path), asset_id="asset_1", kind=BlobKind.ORIGINAL, metadata=metadata)
        layout = (await device.vault.require()).layout

        await store.delete_ref(ref)

        assert not [message for message in device.cloud.read_chat(layout.files_channel_id)[1] if message.media]
        assert _session_rows(device) == []
        await store.delete_ref(ref)  # already gone: still fine

    run(scenario())


def test_tampered_or_truncated_parts_fail_authentication(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = await _ready_device(tmp_path)
        store = device.blob_store(part_size_bytes=64 * 1024)
        path, metadata = _source(tmp_path, 100_000)
        ref = await store.store(str(path), asset_id="asset_1", kind=BlobKind.ORIGINAL, metadata=metadata)
        layout = (await device.vault.require()).layout
        document = device.cloud.document_path(layout.files_channel_id, int(ref.parts[1].message_id))
        data = bytearray(document.read_bytes())
        data[100] ^= 0x01
        document.write_bytes(bytes(data))

        with pytest.raises(IntegrityError):
            await store.download(ref, tmp_path / "out.bin")
        assert not (tmp_path / "out.bin").exists()
        with pytest.raises(IntegrityError):
            await store.read_range(ref, 64 * 1024, 10)
        truncated = replace(ref, parts=ref.parts[:1])
        with pytest.raises(IntegrityError):
            await store.download(truncated, tmp_path / "out.bin")

    run(scenario())


def test_small_blobs_upload_in_albums_of_ten(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = await _ready_device(tmp_path)
        albums = AlbumParts(device.runtime.parts)
        store = device.blob_store(parts=albums, part_size_bytes=MIB)
        uploads = []
        for index in range(12):
            path, metadata = _source(tmp_path, 2_000 + index, f"thumb-{index}.jpg")
            uploads.append(RemoteBlobUpload(str(path), f"asset_{index}", BlobKind.THUMBNAIL, metadata))
        large_path, large_metadata = _source(tmp_path, 3 * MIB, "big.mp4")
        uploads.append(RemoteBlobUpload(str(large_path), "asset_big", BlobKind.ORIGINAL, large_metadata))

        refs = await store.store_many(uploads)

        assert [len(album) for album in albums.albums] == [10, 2]
        assert all(name.endswith(".bpart") for album in albums.albums for name in album)
        assert [ref.asset_id for ref in refs] == [upload.asset_id for upload in uploads]
        assert all(len(ref.parts) == 1 for ref in refs[:12]) and len(refs[12].parts) == 4  # 3 MiB + v2 overhead
        for upload, ref in zip(uploads, refs, strict=True):
            restored = tmp_path / f"restored-{ref.id}"
            await store.download(ref, restored)
            assert restored.read_bytes() == Path(upload.source_ref).read_bytes()
        assert await store.store_many(uploads[:3]) == refs[:3]  # completed sessions are reused

    run(scenario())


def test_the_store_needs_an_unlocked_vault(tmp_path: Path) -> None:
    async def scenario() -> None:
        first = await _ready_device(tmp_path)
        other = make_vault_device(tmp_path, tmp_path / "cloud", "other")
        await other.sign_in()
        path, metadata = _source(tmp_path, 1000)

        assert await other.blob_store().probe() is False
        with pytest.raises(VaultLockedError):
            await other.blob_store().store(str(path), asset_id=None, kind=BlobKind.ORIGINAL, metadata=metadata)
        ref = await first.blob_store().store(str(path), asset_id=None, kind=BlobKind.ORIGINAL, metadata=metadata)
        with pytest.raises(VaultLockedError):
            await other.blob_store().download(ref, tmp_path / "x")

    run(scenario())


def test_premium_accounts_allow_larger_parts() -> None:
    assert part_size_limit(premium=False) == MAX_PART_BYTES == 1950 * MIB
    assert part_size_limit(premium=True) == PREMIUM_MAX_PART_BYTES == 3900 * MIB


def test_ciphertext_ranges_map_to_part_offsets() -> None:
    parts = (
        BlobPart(index=0, channel_id="-1", message_id="1", size_bytes=100),
        BlobPart(index=1, channel_id="-1", message_id="2", size_bytes=100),
        BlobPart(index=2, channel_id="-1", message_id="3", size_bytes=40),
    )

    assert map_ciphertext_range(parts, 0, 36) == ((parts[0], 0, 36),)
    assert map_ciphertext_range(parts, 90, 20) == ((parts[0], 90, 10), (parts[1], 0, 10))
    assert map_ciphertext_range(parts, 100, 100) == ((parts[1], 0, 100),)
    assert map_ciphertext_range(parts, 150, 500) == ((parts[1], 50, 50), (parts[2], 0, 40))
    assert map_ciphertext_range(parts, 240, 10) == ()


def _session_rows(device: VaultDevice) -> list[str]:
    from sqlalchemy import select

    from bento.infrastructure.db.engine import session_scope
    from bento.infrastructure.db.models import UploadSessionModel

    with session_scope(device.sessions) as session:
        return list(session.scalars(select(UploadSessionModel.id)))
