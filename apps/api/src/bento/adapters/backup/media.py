"""Phone-media backup adapters: streaming hash/staging and the SQL queries behind dedupe and "Liberar espacio"."""

from __future__ import annotations

import hashlib
import tempfile
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.mappers import aware
from bento.application.ingestion.metadata import sanitize_filename
from bento.domain.backup import BackupFile, BackupFileState
from bento.domain.storage import BlobKind, StorageBackend
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AssetModel, BackupFileModel, BlobRefModel

CHUNK = 1024 * 1024


class LocalMediaStaging:
    """Reads a content stream once per call; staged copies land next to the blob store (same volume)."""

    def __init__(self, staging_dir: Path | str) -> None:
        self._staging_dir = Path(staging_dir)

    def sha256(self, stream: BinaryIO) -> str:
        digest = hashlib.sha256()
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
        return digest.hexdigest()

    def stage(self, stream: BinaryIO, filename: str) -> Path:
        self._staging_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(sanitize_filename(filename) or "media").suffix[:16]
        descriptor, raw = tempfile.mkstemp(prefix="phone-", suffix=suffix, dir=self._staging_dir)
        path = Path(raw)
        try:
            with open(descriptor, "wb") as target:
                while chunk := stream.read(CHUNK):
                    target.write(chunk)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path


class SQLiteMediaBackupCatalog:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def asset_for_sha256(self, sha256: str) -> str | None:
        with session_scope(self._session_factory) as session:
            return session.scalar(
                select(AssetModel.id).where(AssetModel.sha256 == sha256, AssetModel.deleted_at.is_(None)).limit(1)
            )

    async def done_media_files(self, source_ids: tuple[str, ...]) -> tuple[BackupFile, ...]:
        if not source_ids:
            return ()
        from bento.adapters.backup.repositories import _file_from_model

        with session_scope(self._session_factory) as session:
            models = session.scalars(
                select(BackupFileModel).where(
                    BackupFileModel.source_id.in_(source_ids),
                    BackupFileModel.state == BackupFileState.DONE.value,
                    BackupFileModel.source_key.is_not(None),
                    BackupFileModel.asset_id.is_not(None),
                )
            )
            return tuple(_file_from_model(model) for model in models)

    async def verified_originals(self, asset_ids: tuple[str, ...]) -> dict[str, str]:
        if not asset_ids:
            return {}
        with session_scope(self._session_factory) as session:
            rows = session.execute(
                select(AssetModel.id, AssetModel.sha256)
                .join(BlobRefModel, BlobRefModel.asset_id == AssetModel.id)
                .where(
                    AssetModel.id.in_(asset_ids),
                    AssetModel.deleted_at.is_(None),
                    BlobRefModel.kind == BlobKind.ORIGINAL.value,
                    BlobRefModel.backend == StorageBackend.TELEGRAM.value,
                )
            ).all()
        return {str(asset_id): str(sha256) for asset_id, sha256 in rows}

    async def mark_freed(self, source_ids: tuple[str, ...], media_ids: tuple[str, ...]) -> int:
        if not source_ids or not media_ids:
            return 0
        with session_scope(self._session_factory) as session:
            result = session.execute(
                update(BackupFileModel)
                .where(
                    BackupFileModel.source_id.in_(source_ids),
                    BackupFileModel.source_key.in_(media_ids),
                    BackupFileModel.state == BackupFileState.DONE.value,
                )
                .values(state=BackupFileState.FREED.value)
            )
            return int(result.rowcount or 0)

    async def summary(self, since: datetime) -> tuple[int, datetime | None]:
        with session_scope(self._session_factory) as session:
            done = BackupFileModel.state == BackupFileState.DONE.value
            today = int(session.scalar(select(func.count()).where(done, BackupFileModel.updated_at >= since)) or 0)
            last = session.scalar(select(func.max(BackupFileModel.updated_at)).where(done))
        return today, aware(last)
