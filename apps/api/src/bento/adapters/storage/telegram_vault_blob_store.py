"""Encrypted blobs in the vault Files channel (architecture/telegram-first.md § Blob format v2, § Rate and size).

A blob is one continuous v2 ciphertext stream split into `<random>.bpart` documents of `part_size` bytes, so a
plaintext range maps to ciphertext segments and then to `(part, offset_in_part)`. Uploads are resumable at part
granularity through `upload_sessions`: the session id is derived from the source content, and its saved
`file_salt`/`nonce_prefix` are reused only for the very same bytes, which makes the re-encryption identical.

Works with any `RemotePartStorePort` (MTProto or the fake cloud).
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import shutil
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.mappers import aware, require_aware
from bento.domain.assets import AssetMetadata
from bento.domain.errors import IntegrityError, StorageUnavailableError, ValidationFailedError
from bento.domain.security import BlobCipherParams, EncryptionMetadata, EncryptionMode, VaultKeyring
from bento.domain.storage import BlobKind, BlobPart, BlobRef, StorageBackend
from bento.domain.telegram import RemotePart
from bento.domain.vault import VaultLayout
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import UploadSessionModel
from bento.ports.repositories import ClockPort
from bento.ports.security import BlobCipherPort
from bento.ports.telegram import RemotePartStorePort
from bento.ports.vault import VaultContext, VaultSessionPort

MIB = 1024 * 1024
MAX_PART_BYTES = 1950 * MIB
PREMIUM_MAX_PART_BYTES = 3900 * MIB
ALBUM_SIZE = 10
DEFAULT_SMALL_BLOB_BYTES = 8 * MIB
BLOB_FORMAT_VERSION = 2
PART_SUFFIX = ".bpart"
COMPLETED_SESSION_TTL = timedelta(days=7)
_COPY_CHUNK = 4 * MIB


class UploadState:
    UPLOADING = "uploading"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class UploadSession:
    id: str
    blob_ref_id: str
    asset_id: str | None
    source_path: str
    blob_kind: BlobKind
    params: BlobCipherParams
    plaintext_size: int
    ciphertext_size: int
    completed_parts: tuple[RemotePart, ...]
    state: str
    created_at: datetime
    updated_at: datetime

    @property
    def bytes_done(self) -> int:
        return sum(part.size_bytes for part in self.completed_parts)


class UploadSessionStorePort(Protocol):
    async def get(self, session_id: str) -> UploadSession | None: ...

    async def save(self, session: UploadSession) -> None: ...

    async def delete(self, session_id: str) -> None: ...

    async def delete_for_blob(self, blob_ref_id: str) -> None: ...

    async def purge_completed(self, *, before: datetime) -> int: ...


class BlobRefLookupPort(Protocol):
    async def get(self, blob_id: str) -> BlobRef | None: ...


@runtime_checkable
class PartBatchUploader(Protocol):
    """Optional capability of a part store: one album request for up to 10 documents."""

    async def upload_parts(self, layout: VaultLayout, items: Sequence[tuple[Path, str]]) -> tuple[RemotePart, ...]: ...


@dataclass(frozen=True, slots=True)
class RemoteBlobUpload:
    source_ref: str
    asset_id: str | None
    kind: BlobKind
    metadata: AssetMetadata


async def upload_part_batch(
    parts: RemotePartStorePort, layout: VaultLayout, items: Sequence[tuple[Path, str]]
) -> tuple[RemotePart, ...]:
    """Upload `(path, filename)` pairs, in albums of up to 10 when the part store supports it."""
    uploaded: list[RemotePart] = []
    for offset in range(0, len(items), ALBUM_SIZE):
        chunk = items[offset : offset + ALBUM_SIZE]
        if isinstance(parts, PartBatchUploader) and len(chunk) > 1:
            result = await parts.upload_parts(layout, chunk)
            if len(result) != len(chunk):
                raise StorageUnavailableError(StorageBackend.TELEGRAM.value)
            uploaded.extend(result)
        else:
            for path, filename in chunk:
                uploaded.append(await parts.upload_part(layout, path, filename=filename))
    return tuple(uploaded)


def part_size_limit(*, premium: bool) -> int:
    return PREMIUM_MAX_PART_BYTES if premium else MAX_PART_BYTES


def part_offsets(parts: Sequence[BlobPart]) -> tuple[tuple[int, BlobPart], ...]:
    """Ciphertext offset at which each part starts."""
    offsets: list[tuple[int, BlobPart]] = []
    position = 0
    for part in parts:
        offsets.append((position, part))
        position += part.size_bytes
    return tuple(offsets)


def map_ciphertext_range(parts: Sequence[BlobPart], offset: int, length: int) -> tuple[tuple[BlobPart, int, int], ...]:
    """`(part, offset_in_part, length)` slices covering ciphertext bytes `[offset, offset + length)`."""
    end = offset + length
    slices: list[tuple[BlobPart, int, int]] = []
    for start, part in part_offsets(parts):
        stop = start + part.size_bytes
        if stop <= offset or start >= end or part.size_bytes == 0:
            continue
        local_start = max(offset, start) - start
        local_stop = min(end, stop) - start
        slices.append((part, local_start, local_stop - local_start))
    return tuple(slices)


class TelegramVaultBlobStore:
    """`RemoteBlobStorePort` over a part store, the v2 cipher, and the unlocked vault."""

    def __init__(
        self,
        *,
        vault: VaultSessionPort,
        parts: RemotePartStorePort,
        cipher: BlobCipherPort,
        sessions: UploadSessionStorePort,
        catalog: BlobRefLookupPort,
        clock: ClockPort,
        temp_dir: Path | str,
        part_size_bytes: int = 512 * MIB,
        small_blob_bytes: int = DEFAULT_SMALL_BLOB_BYTES,
    ) -> None:
        if part_size_bytes <= 0:
            raise ValidationFailedError("Part size must be positive")
        self._vault = vault
        self._parts = parts
        self._cipher = cipher
        self._sessions = sessions
        self._catalog = catalog
        self._clock = clock
        self._temp_dir = Path(temp_dir)
        self._part_size = part_size_bytes
        self._small_blob_bytes = small_blob_bytes

    async def probe(self) -> bool:
        return await self._vault.current() is not None

    async def store(
        self,
        source_ref: str,
        *,
        asset_id: str | None,
        kind: BlobKind,
        metadata: AssetMetadata,
        encryption: EncryptionMetadata | None = None,
    ) -> BlobRef:
        """Encrypt with the current epoch and upload every missing part; resumes an interrupted upload."""
        del encryption  # Remote blobs are always v2 streaming AEAD.
        context = await self._vault.require()
        await self._sessions.purge_completed(before=self._clock.now() - COMPLETED_SESSION_TTL)
        session = await self._session_for(context, Path(source_ref), asset_id, kind, metadata)
        if session.state != UploadState.COMPLETED:
            with self._temp_file(".bcipher") as ciphertext:
                await self._encrypt(context.keyring, Path(source_ref), ciphertext, session, metadata)
                session = await self._upload_missing_parts(context, session, ciphertext)
        return _blob_ref(session, metadata.sha256)

    async def store_many(self, uploads: Sequence[RemoteBlobUpload]) -> tuple[BlobRef, ...]:
        """Like `store` for each item, but small single-part blobs (thumbnails, previews) go up in albums of 10."""
        context = await self._vault.require()
        results: dict[int, BlobRef] = {}
        small: list[tuple[int, UploadSession, Path, RemoteBlobUpload]] = []
        limit = min(self._small_blob_bytes, self._effective_part_size(context))
        batch_dir = self._new_temp_dir()
        try:
            for index, upload in enumerate(uploads):
                session = await self._session_for(
                    context, Path(upload.source_ref), upload.asset_id, upload.kind, upload.metadata
                )
                if session.state == UploadState.COMPLETED:
                    results[index] = _blob_ref(session, upload.metadata.sha256)
                elif session.ciphertext_size <= limit and not session.completed_parts:
                    ciphertext = batch_dir / f"{secrets.token_hex(12)}{PART_SUFFIX}"
                    await self._encrypt(context.keyring, Path(upload.source_ref), ciphertext, session, upload.metadata)
                    small.append((index, session, ciphertext, upload))
                else:
                    results[index] = await self.store(
                        upload.source_ref, asset_id=upload.asset_id, kind=upload.kind, metadata=upload.metadata
                    )
            for offset in range(0, len(small), ALBUM_SIZE):
                chunk = small[offset : offset + ALBUM_SIZE]
                remotes = await upload_part_batch(
                    self._parts, context.layout, [(path, path.name) for _, _, path, _ in chunk]
                )
                for (index, session, _, upload), remote in zip(chunk, remotes, strict=True):
                    _check_part_size(remote, session.ciphertext_size)
                    completed = self._complete(replace(session, completed_parts=(remote,)))
                    await self._sessions.save(completed)
                    results[index] = _blob_ref(completed, upload.metadata.sha256)
        finally:
            await asyncio.to_thread(shutil.rmtree, batch_dir, True)
        return tuple(results[index] for index in range(len(uploads)))

    async def get(self, blob_id: str) -> BlobRef | None:
        blob_ref = await self._catalog.get(blob_id)
        return blob_ref if blob_ref is not None and blob_ref.backend == StorageBackend.TELEGRAM else None

    async def download(self, blob_ref: BlobRef, destination_path: Path | str) -> Path:
        """Fetch every part, decrypt (each segment authenticated), and verify the plaintext sha256."""
        _require_remote(blob_ref)
        context = await self._vault.require()
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._temp_file(".bcipher") as ciphertext:
            if len(blob_ref.parts) == 1:
                await self._parts.download_part(blob_ref.parts[0].remote(), ciphertext)
            else:
                for part in blob_ref.parts:
                    with self._temp_file(PART_SUFFIX) as part_file:
                        await self._parts.download_part(part.remote(), part_file)
                        await asyncio.to_thread(_append, part_file, ciphertext)
            expected = sum(part.size_bytes for part in blob_ref.parts)
            if await asyncio.to_thread(lambda: ciphertext.stat().st_size) != expected:
                raise IntegrityError("blob")
            digest = await self._cipher.decrypt_file(ciphertext, destination, keyring=context.keyring)
        if blob_ref.sha256 is not None and digest != blob_ref.sha256:
            destination.unlink(missing_ok=True)
            raise IntegrityError("blob")
        return destination

    async def read_range(self, blob_ref: BlobRef, start: int, length: int) -> bytes:
        """Plaintext `[start, start + length)`, clamped to the blob; downloads only the needed segments."""
        if start < 0 or length < 0:
            raise ValidationFailedError("Invalid blob range")
        _require_remote(blob_ref)
        if length == 0 or start >= blob_ref.size_bytes:
            return b""
        length = min(length, blob_ref.size_bytes - start)
        context = await self._vault.require()
        parts = blob_ref.parts

        async def read(offset: int, size: int) -> bytes:
            chunks = [
                await self._parts.read_part_range(part.remote(), local_offset, local_length)
                for part, local_offset, local_length in map_ciphertext_range(parts, offset, size)
            ]
            return b"".join(chunks)

        return await self._cipher.decrypt_range(
            read,
            ciphertext_size=sum(part.size_bytes for part in parts),
            start=start,
            length=length,
            keyring=context.keyring,
        )

    async def delete(self, blob_id: str) -> None:
        blob_ref = await self.get(blob_id)
        if blob_ref is not None:
            await self.delete_ref(blob_ref)

    async def delete_ref(self, blob_ref: BlobRef) -> None:
        """Delete every part message of the blob (missing messages are ignored) and its upload session."""
        if blob_ref.parts:
            await self._parts.delete_parts(tuple(part.remote() for part in blob_ref.parts))
        await self._sessions.delete_for_blob(blob_ref.id)

    # Internals

    async def _session_for(
        self, context: VaultContext, source: Path, asset_id: str | None, kind: BlobKind, metadata: AssetMetadata
    ) -> UploadSession:
        size, digest = await asyncio.to_thread(_size_and_sha256, source)
        # Resume safety (GCM nonce reuse): saved salts are only reused for the very same content.
        if digest != metadata.sha256 or size != metadata.size_bytes:
            raise ValidationFailedError("Blob sha256 does not match metadata")
        session_id = _session_id(asset_id, kind, digest, size)
        session = await self._sessions.get(session_id)
        keyring = context.keyring
        if session is not None:
            if session.state == UploadState.COMPLETED and session.params.epoch in keyring.keys:
                return session
            if session.plaintext_size == size and session.params.epoch == keyring.current_epoch:
                return replace(session, source_path=str(source))
            # Restart with the current epoch: never leave parts sealed with a superseded key behind.
            if session.completed_parts:
                await self._parts.delete_parts(session.completed_parts)
            await self._sessions.delete(session.id)
        params = self._cipher.new_params(keyring)
        now = self._clock.now()
        session = UploadSession(
            id=session_id,
            blob_ref_id=f"tgb_{secrets.token_hex(16)}",
            asset_id=asset_id,
            source_path=str(source),
            blob_kind=kind,
            params=params,
            plaintext_size=size,
            ciphertext_size=self._cipher.ciphertext_size(size, params.segment_size),
            completed_parts=(),
            state=UploadState.UPLOADING,
            created_at=now,
            updated_at=now,
        )
        await self._sessions.save(session)
        return session

    async def _encrypt(
        self, keyring: VaultKeyring, source: Path, ciphertext: Path, session: UploadSession, metadata: AssetMetadata
    ) -> None:
        result = await self._cipher.encrypt_file(source, ciphertext, keyring=keyring, params=session.params)
        if result.plaintext_sha256 != metadata.sha256 or result.ciphertext_size != session.ciphertext_size:
            raise ValidationFailedError("Blob changed while it was being encrypted")

    async def _upload_missing_parts(self, context: VaultContext, session: UploadSession, ciphertext: Path) -> UploadSession:
        total = session.ciphertext_size
        completed = list(session.completed_parts)
        # Parts are uploaded in order, so a resumed session keeps the split it started with.
        part_size = completed[0].size_bytes if completed else self._effective_part_size(context)
        count = max(1, -(-total // part_size))
        for index in range(len(completed), count):
            start = index * part_size
            length = min(part_size, total - start)
            filename = f"{secrets.token_hex(12)}{PART_SUFFIX}"
            if count == 1:
                remote = await self._parts.upload_part(context.layout, ciphertext, filename=filename)
            else:
                with self._temp_file(PART_SUFFIX) as part_file:
                    await asyncio.to_thread(_copy_range, ciphertext, part_file, start, length)
                    remote = await self._parts.upload_part(context.layout, part_file, filename=filename)
            _check_part_size(remote, length)
            completed.append(remote)
            session = replace(session, completed_parts=tuple(completed), updated_at=self._clock.now())
            await self._sessions.save(session)
        session = self._complete(session)
        await self._sessions.save(session)
        return session

    def _complete(self, session: UploadSession) -> UploadSession:
        return replace(session, state=UploadState.COMPLETED, updated_at=self._clock.now())

    def _effective_part_size(self, context: VaultContext) -> int:
        return min(self._part_size, part_size_limit(premium=context.account.premium))

    def _new_temp_dir(self) -> Path:
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="batch-", dir=self._temp_dir))

    @contextmanager
    def _temp_file(self, suffix: str) -> Iterator[Path]:
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="blob-", suffix=suffix, dir=self._temp_dir, delete=False) as handle:
            path = Path(handle.name)
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)


class SQLiteUploadSessionStore:
    """`upload_sessions` rows (`UploadSessionStorePort`)."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def get(self, session_id: str) -> UploadSession | None:
        with session_scope(self._session_factory) as session:
            model = session.get(UploadSessionModel, session_id)
            return _session_from_model(model) if model is not None else None

    async def save(self, upload: UploadSession) -> None:
        with session_scope(self._session_factory) as session:
            session.merge(
                UploadSessionModel(
                    id=upload.id,
                    asset_id=upload.asset_id,
                    blob_ref_id=upload.blob_ref_id,
                    source_path=upload.source_path,
                    blob_kind=upload.blob_kind.value,
                    epoch=upload.params.epoch,
                    file_salt=upload.params.file_salt,
                    nonce_prefix=upload.params.nonce_prefix,
                    segment_size=upload.params.segment_size,
                    plaintext_size=upload.plaintext_size,
                    ciphertext_size=upload.ciphertext_size,
                    completed_parts=[_part_to_json(index, part) for index, part in enumerate(upload.completed_parts)],
                    state=upload.state,
                    error_code=None,
                    created_at=upload.created_at,
                    updated_at=upload.updated_at,
                )
            )

    async def delete(self, session_id: str) -> None:
        with session_scope(self._session_factory) as session:
            session.execute(delete(UploadSessionModel).where(UploadSessionModel.id == session_id))

    async def delete_for_blob(self, blob_ref_id: str) -> None:
        with session_scope(self._session_factory) as session:
            session.execute(delete(UploadSessionModel).where(UploadSessionModel.blob_ref_id == blob_ref_id))

    async def purge_completed(self, *, before: datetime) -> int:
        with session_scope(self._session_factory) as session:
            result: Any = session.execute(
                delete(UploadSessionModel).where(
                    UploadSessionModel.state == UploadState.COMPLETED, UploadSessionModel.updated_at < before
                )
            )
            return int(result.rowcount or 0)


def _session_from_model(model: UploadSessionModel) -> UploadSession:
    parts = sorted(model.completed_parts or [], key=lambda item: int(item["index"]))
    return UploadSession(
        id=model.id,
        blob_ref_id=model.blob_ref_id or "",
        asset_id=model.asset_id,
        source_path=model.source_path,
        blob_kind=BlobKind(model.blob_kind),
        params=BlobCipherParams(
            epoch=model.epoch,
            file_salt=bytes(model.file_salt),
            nonce_prefix=bytes(model.nonce_prefix),
            segment_size=model.segment_size,
        ),
        plaintext_size=int(model.plaintext_size),
        ciphertext_size=int(model.ciphertext_size),
        completed_parts=tuple(
            RemotePart(channel_id=int(item["channel_id"]), message_id=int(item["message_id"]), size_bytes=int(item["size_bytes"]))
            for item in parts
        ),
        state=model.state,
        created_at=require_aware(model.created_at),
        updated_at=aware(model.updated_at) or require_aware(model.created_at),
    )


def _part_to_json(index: int, part: RemotePart) -> dict[str, int]:
    return {"index": index, "channel_id": part.channel_id, "message_id": part.message_id, "size_bytes": part.size_bytes}


def _blob_ref(session: UploadSession, sha256: str) -> BlobRef:
    return BlobRef(
        id=session.blob_ref_id,
        asset_id=session.asset_id,
        backend=StorageBackend.TELEGRAM,
        kind=session.blob_kind,
        object_key=f"vault/{session.blob_ref_id}",
        size_bytes=session.plaintext_size,
        sha256=sha256,
        encryption=EncryptionMetadata(
            mode=EncryptionMode.AES_GCM_STREAM,
            key_epoch=session.params.epoch,
            format_version=BLOB_FORMAT_VERSION,
        ),
        parts=tuple(BlobPart.from_remote(index, part) for index, part in enumerate(session.completed_parts)),
    )


def _require_remote(blob_ref: BlobRef) -> None:
    if blob_ref.backend != StorageBackend.TELEGRAM or not blob_ref.parts:
        raise StorageUnavailableError(StorageBackend.TELEGRAM.value)
    if blob_ref.encryption.format_version != BLOB_FORMAT_VERSION:
        raise ValidationFailedError("Only blob format v2 is stored in the vault", {"blob_id": blob_ref.id})


def _check_part_size(remote: RemotePart, expected: int) -> None:
    if remote.size_bytes != expected:
        raise IntegrityError("blob_part")


def _session_id(asset_id: str | None, kind: BlobKind, sha256: str, size: int) -> str:
    digest = hashlib.sha256(f"{asset_id or ''}:{kind.value}:{sha256}:{size}".encode()).hexdigest()
    return f"up_{digest[:32]}"


def _size_and_sha256(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_COPY_CHUNK):
                digest.update(chunk)
                size += len(chunk)
    except FileNotFoundError as exc:
        raise StorageUnavailableError(StorageBackend.LOCAL.value) from exc
    return size, digest.hexdigest()


def _copy_range(source: Path, destination: Path, start: int, length: int) -> None:
    with source.open("rb") as reader, destination.open("wb") as writer:
        reader.seek(start)
        remaining = length
        while remaining > 0:
            chunk = reader.read(min(_COPY_CHUNK, remaining))
            if not chunk:
                raise IntegrityError("blob")
            writer.write(chunk)
            remaining -= len(chunk)


def _append(source: Path, destination: Path) -> None:
    with source.open("rb") as reader, destination.open("ab") as writer:
        shutil.copyfileobj(reader, writer, _COPY_CHUNK)
