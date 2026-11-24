"""Imports of shared/SAF content handed over as file descriptors (`api/android-endpoints.md` §4).

Kotlin opens the content URI, detaches the fd, and registers it under a one-time handle; this service adopts the
fd, streams it once into a staging file, and ingests it local-first with `origin=device` (the existing upload
rules sanitize the display name). Imports run in the background; progress is kept per process.
"""

from __future__ import annotations

import asyncio
import os
import threading
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Protocol

from bento.application.ingestion.assets import UploadedAssetFile
from bento.application.ingestion.metadata import sanitize_filename
from bento.application.upload import UploadAssetResult
from bento.domain.errors import DomainError, ValidationFailedError
from bento.ports.device import ContentHandleError, ContentImportsPort, NotifierPort, transfer_finished, transfer_progress

MAX_IMPORT_ITEMS = 500
KEEP_FINISHED_IMPORTS = 50


class ImportIngestionPort(Protocol):
    async def upload_file(self, file: UploadedAssetFile) -> UploadAssetResult: ...


class ImportStagingPort(Protocol):
    def stage(self, stream: BinaryIO, filename: str) -> Path: ...


@dataclass(frozen=True, slots=True)
class ContentImportItem:
    fd_handle: int
    display_name: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None


@dataclass(slots=True)
class ImportItemState:
    client_index: int
    status: str = "pending"  # pending | importing | done | duplicate | failed
    asset_id: str | None = None
    error: str | None = None


@dataclass(slots=True)
class ContentImport:
    id: str
    items: list[ImportItemState]
    folder_id: str | None = None
    album_id: str | None = None
    done: bool = False
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in self.items:
            result[item.status] = result.get(item.status, 0) + 1
        return result


class ContentImportService:
    def __init__(
        self,
        *,
        imports: ContentImportsPort,
        ingestion: ImportIngestionPort,
        staging: ImportStagingPort,
        notifier: NotifierPort,
        add_to_album: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> None:
        self._imports = imports
        self._ingestion = ingestion
        self._staging = staging
        self._notifier = notifier
        self._add_to_album = add_to_album
        self._lock = threading.Lock()
        self._registry: dict[str, ContentImport] = {}

    def start(
        self, items: list[ContentImportItem], *, folder_id: str | None = None, album_id: str | None = None
    ) -> ContentImport:
        if not items or len(items) > MAX_IMPORT_ITEMS:
            raise ValidationFailedError("An import needs between 1 and 500 items", {"maximum": MAX_IMPORT_ITEMS})
        job = ContentImport(
            id=f"imp_{uuid.uuid4().hex}",
            items=[ImportItemState(client_index=index) for index in range(len(items))],
            folder_id=folder_id,
            album_id=album_id,
        )
        with self._lock:
            self._registry[job.id] = job
            finished = [key for key, value in self._registry.items() if value.done]
            for key in finished[:-KEEP_FINISHED_IMPORTS]:
                self._registry.pop(key, None)
        job.task = asyncio.get_running_loop().create_task(self._run(job, items))
        return job

    def get(self, import_id: str) -> ContentImport | None:
        with self._lock:
            return self._registry.get(import_id)

    async def _run(self, job: ContentImport, items: list[ContentImportItem]) -> None:
        total = len(items)
        for index, item in enumerate(items):
            state = job.items[index]
            state.status = "importing"
            try:
                result = await self._import_one(item, folder_id=job.folder_id)
            except DomainError as exc:
                state.status, state.error = "failed", exc.code[:64]
            except (ContentHandleError, OSError):
                state.status, state.error = "failed", "content_unreadable"
            else:
                state.asset_id = result.asset.id
                state.status = "duplicate" if result.duplicate else "done"
                if job.album_id is not None and self._add_to_album is not None:
                    try:
                        await self._add_to_album(job.album_id, result.asset.id)
                    except DomainError:
                        state.error = "album_unavailable"
            self._notifier.emit(transfer_progress("import", done=index + 1, total=total))
        failed = sum(1 for state in job.items if state.status == "failed")
        self._notifier.emit(transfer_finished("import", count=total - failed, failed=failed))
        job.done = True

    async def _import_one(self, item: ContentImportItem, *, folder_id: str | None) -> UploadAssetResult:
        description = None
        if not item.display_name or not item.mime_type:
            description = await asyncio.to_thread(self._imports.describe, item.fd_handle)
        name = sanitize_filename(item.display_name or (description.display_name if description else "")) or "archivo"
        mime = item.mime_type or (description.mime_type if description else None)
        descriptor = await asyncio.to_thread(self._imports.adopt, item.fd_handle)
        try:
            stream = os.fdopen(descriptor, "rb", buffering=1024 * 1024)
        except OSError:
            os.close(descriptor)
            raise
        with stream:
            staged = await asyncio.to_thread(self._staging.stage, stream, name)
        try:
            return await self._ingestion.upload_file(
                UploadedAssetFile(
                    source_path=staged,
                    original_filename=name,
                    declared_mime_type=mime,
                    folder_id=folder_id,
                    allow_duplicate=True,
                )
            )
        finally:
            staged.unlink(missing_ok=True)
