"""Shared doubles for storage pipeline, content, backup, trash, and activity tests.

`VaultRemoteBlobStore` is an in-memory-state `RemoteBlobStorePort` that really encrypts with the v2
`StreamingBlobCipher` and stores ciphertext parts in the Stage 14 fake Telegram cloud.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config

from bento.adapters.security import StreamingBlobCipher, VaultCrypto
from bento.application.media.service import GeneratedMediaFile
from bento.domain.assets import Asset, AssetMetadata
from bento.domain.errors import ValidationFailedError
from bento.domain.security import EncryptionMetadata, EncryptionMode
from bento.domain.storage import BlobKind, BlobPart, BlobRef, StorageBackend
from bento.domain.telegram import RemotePart
from bento.infrastructure.db.engine import sqlite_url
from bento.infrastructure.settings import Settings
from bento.infrastructure.storage_pipeline import StoragePipelineComponents, build_storage_pipeline
from bento.interfaces.worker.storage_pipeline import StoragePipelineJobHandler
from tests.integration.fake_telegram.support import make_device, sign_in

API_ROOT = Path(__file__).parents[3]


def migrated_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    (data_dir / "db").mkdir(parents=True, exist_ok=True)
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", sqlite_url(data_dir / "db" / "bento.sqlite3"))
    command.upgrade(config, "head")
    return data_dir


class VaultRemoteBlobStore:
    def __init__(self, parts: Any, layout: Any, keyring: Any, *, work_dir: Path, part_size: int = 64 * 1024) -> None:
        self._parts = parts
        self._layout = layout
        self._keyring = keyring
        self._cipher = StreamingBlobCipher(segment_size=4096)
        self._work_dir = work_dir
        self._part_size = part_size
        self.failures: list[Exception] = []
        self.delete_failures: list[Exception] = []
        self.stored: list[BlobRef] = []
        self.deleted: list[str] = []
        self.range_reads: list[tuple[int, int]] = []
        self.downloads: list[str] = []
        self.cloud_dir = Path()

    async def probe(self) -> bool:
        return True

    async def store(
        self,
        source_ref: str,
        *,
        asset_id: str | None,
        kind: BlobKind,
        metadata: AssetMetadata,
        encryption: EncryptionMetadata | None = None,
    ) -> BlobRef:
        del encryption
        if self.failures:
            raise self.failures.pop(0)
        source = Path(source_ref)
        if hashlib.sha256(source.read_bytes()).hexdigest() != metadata.sha256:
            raise ValidationFailedError("source changed")
        self._work_dir.mkdir(parents=True, exist_ok=True)
        encrypted = self._work_dir / f"{uuid.uuid4().hex}.enc"
        params = self._cipher.new_params(self._keyring)
        result = await self._cipher.encrypt_file(source, encrypted, keyring=self._keyring, params=params)
        ciphertext = encrypted.read_bytes()
        encrypted.unlink()
        remote_parts: list[BlobPart] = []
        for index, offset in enumerate(range(0, len(ciphertext), self._part_size)):
            chunk = self._work_dir / f"{uuid.uuid4().hex}.bpart"
            chunk.write_bytes(ciphertext[offset : offset + self._part_size])
            part = await self._parts.upload_part(self._layout, chunk, filename=chunk.name)
            chunk.unlink()
            remote_parts.append(BlobPart.from_remote(index, part))
        blob_id = f"tg_{uuid.uuid4().hex}"
        ref = BlobRef(
            id=blob_id,
            asset_id=asset_id,
            backend=StorageBackend.TELEGRAM,
            kind=kind,
            object_key=f"vault/{blob_id}",
            size_bytes=result.plaintext_size,
            sha256=result.plaintext_sha256,
            encryption=EncryptionMetadata(
                mode=EncryptionMode.AES_GCM_STREAM, key_epoch=params.epoch, format_version=2
            ),
            parts=tuple(remote_parts),
        )
        self.stored.append(ref)
        return ref

    async def get(self, blob_id: str) -> BlobRef | None:
        del blob_id
        return None

    async def download(self, blob_ref: BlobRef, destination_path: Path | str) -> Path:
        self.downloads.append(blob_ref.id)
        encrypted = self._work_dir / f"{uuid.uuid4().hex}.download"
        self._work_dir.mkdir(parents=True, exist_ok=True)
        with encrypted.open("wb") as handle:
            for part in blob_ref.parts:
                piece = self._work_dir / f"{uuid.uuid4().hex}.piece"
                await self._parts.download_part(part.remote(), piece)
                handle.write(piece.read_bytes())
                piece.unlink()
        destination = Path(destination_path)
        await self._cipher.decrypt_file(encrypted, destination, keyring=self._keyring)
        encrypted.unlink()
        return destination

    async def read_range(self, blob_ref: BlobRef, start: int, length: int) -> bytes:
        self.range_reads.append((start, length))
        parts = blob_ref.parts

        async def read(offset: int, size: int) -> bytes:
            data = bytearray()
            position = 0
            for part in parts:
                end = position + part.size_bytes
                if end > offset and position < offset + size:
                    local = max(offset - position, 0)
                    wanted = min(end, offset + size) - (position + local)
                    data += await self._parts.read_part_range(part.remote(), local, wanted)
                position = end
            return bytes(data)

        return await self._cipher.decrypt_range(
            read,
            ciphertext_size=sum(part.size_bytes for part in parts),
            start=start,
            length=length,
            keyring=self._keyring,
        )

    async def delete(self, blob_id: str) -> None:
        del blob_id

    async def delete_ref(self, blob_ref: BlobRef) -> None:
        if self.delete_failures:
            raise self.delete_failures.pop(0)
        await self._parts.delete_parts(tuple(part.remote() for part in blob_ref.parts))
        self.deleted.append(blob_ref.id)

    def remote_exists(self, part: RemotePart | BlobPart) -> bool:
        from bento.adapters.fake_telegram import FakeTelegramCloud

        remote = part.remote() if isinstance(part, BlobPart) else part
        return FakeTelegramCloud(self.cloud_dir).message(remote.channel_id, remote.message_id) is not None


async def vault_remote_store(tmp_path: Path, *, part_size: int = 64 * 1024) -> VaultRemoteBlobStore:
    cloud_dir = tmp_path / "fake-telegram"
    device = make_device(cloud_dir)
    await sign_in(device)
    layout = await device.runtime.transport.create_vault("vlt_pipeline")
    keyring = VaultCrypto().generate_keyring("vlt_pipeline")
    store = VaultRemoteBlobStore(device.runtime.parts, layout, keyring, work_dir=tmp_path / "remote-work", part_size=part_size)
    store.cloud_dir = cloud_dir
    return store


@dataclass
class RemoteSwitch:
    """Provider whose vault readiness tests can flip."""

    store: Any = None

    def __call__(self) -> Any:
        return self.store


def pipeline_for(
    data_dir: Path,
    remote: RemoteSwitch,
    *,
    storage_backend: str = "fake",
    full_fetch_threshold: int = 32 * 1024 * 1024,
    cache_grace_seconds: int = 600,
    **settings: Any,
) -> StoragePipelineComponents:
    return build_storage_pipeline(
        Settings(data_dir=str(data_dir), storage_backend=storage_backend, **settings),
        remote=remote,
        full_fetch_threshold=full_fetch_threshold,
        cache_grace_seconds=cache_grace_seconds,
    )


@dataclass
class JobRunner:
    """Runs due jobs through the real worker dispatcher (failures → retry with backoff)."""

    components: StoragePipelineComponents
    handled: list[str] = field(default_factory=list)

    async def run_all(self, *, max_jobs: int = 100, types: set[str] | None = None) -> int:
        from bento.interfaces.worker.dispatch import WorkerDispatcher

        dispatcher = WorkerDispatcher(
            jobs=self.components.jobs,
            media=_NoMedia(),  # type: ignore[arg-type]
            clock=self.components.clock,
            worker_id="test-worker",
            storage_pipeline=StoragePipelineJobHandler(self.components),
        )
        processed = 0
        while processed < max_jobs:
            job = await _peek(self.components, types)
            if job is None:
                break
            assert await dispatcher.process_one()
            self.handled.append(job.type.value)
            processed += 1
        return processed


async def _peek(components: StoragePipelineComponents, types: set[str] | None):  # type: ignore[no-untyped-def]
    from sqlalchemy import or_, select

    from bento.adapters.repositories.mappers import job_from_model
    from bento.infrastructure.db.engine import session_scope
    from bento.infrastructure.db.models import JobModel

    now = components.clock.now()
    with session_scope(components.session_factory) as session:
        statement = (
            select(JobModel)
            .where(
                JobModel.status.in_(["queued", "retrying"]),
                or_(JobModel.run_after.is_(None), JobModel.run_after <= now),
            )
            .order_by(JobModel.priority.asc(), JobModel.created_at.asc(), JobModel.id.asc())
            .limit(1)
        )
        model = session.scalar(statement)
        if model is None:
            return None
        job = job_from_model(model)
        if types is not None and job.type.value not in types:
            return None
        return job


class _NoMedia:
    async def process_asset_media(self, asset_id: str) -> tuple[BlobRef, ...]:
        del asset_id
        return ()


class FakeMediaGenerator:
    def __init__(self, root: Path) -> None:
        self._root = root

    async def generate(self, asset: Asset, source_path: Path) -> tuple[GeneratedMediaFile, ...]:
        target = self._root / asset.id
        target.mkdir(parents=True, exist_ok=True)
        files = []
        for kind, label in ((BlobKind.THUMBNAIL, "thumb"), (BlobKind.PREVIEW, "preview")):
            path = target / f"{label}.jpg"
            path.write_bytes(f"{label}:{asset.id}:{source_path.read_bytes()[:16]!r}".encode())
            content = path.read_bytes()
            files.append(
                GeneratedMediaFile(
                    path=path,
                    kind=kind,
                    filename=f"{label}.jpg",
                    mime_type="image/jpeg",
                    size_bytes=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                    width=32,
                    height=32,
                )
            )
        return tuple(files)

    async def cleanup(self, generated_files: tuple[GeneratedMediaFile, ...]) -> None:
        for generated in generated_files:
            generated.path.unlink(missing_ok=True)


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


def age(path: Path, seconds: float = 3600) -> None:
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def utc(minutes: int = 0) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)
