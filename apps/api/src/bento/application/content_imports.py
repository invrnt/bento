"""Imports of shared/SAF content handed over as file descriptors (`api/android-endpoints.md` §4).

Kotlin opens the content URI, detaches the fd, and registers it under a one-time handle; this service adopts the
fd, streams it once into a staging file, and ingests it local-first with `origin=device` (the existing upload
rules sanitize the display name). Imports run in the background; their state is persisted item by item, so
`GET /android/imports/{id}` still answers after a restart. A restart kills the fds, so the unfinished items of
an earlier process are failed with `import_interrupted` (the app offers to share them again), and every import
with failures shows as an Activity item until it is dismissed.
"""

from __future__ import annotations

import asyncio
import os
import threading
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from bento.application.ingestion.assets import UploadedAssetFile
from bento.application.ingestion.metadata import sanitize_filename
from bento.application.upload import UploadAssetResult
from bento.domain.errors import DomainError, ValidationFailedError
from bento.domain.imports import (
    ALBUM_UNAVAILABLE,
    CONTENT_UNREADABLE,
    ContentImport,
    ImportItemState,
    ImportItemStatus,
)
from bento.ports.device import (
    ContentHandleError,
    ContentImportsPort,
    NotifierPort,
    transfer_finished,
    transfer_progress,
)
from bento.ports.imports import ContentImportStorePort
from bento.ports.repositories import ClockPort

__all__ = [
    "IMPORT_FAILED_ATTENTION",
    "PROCESS_OWNER",
    "ContentImport",
    "ContentImportItem",
    "ContentImportService",
    "ImportItemState",
]

MAX_IMPORT_ITEMS = 500
KEEP_FINISHED_IMPORTS = 50
IMPORT_FAILED_ATTENTION = "import_failed"
"""Activity item code of imports with failed items (the Activity announcer notifies `attention` for it)."""
PROCESS_OWNER = uuid.uuid4().hex
"""This process: imports owned by another one lost their fds."""


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


class ContentImportService:
    def __init__(
        self,
        *,
        imports: ContentImportsPort,
        ingestion: ImportIngestionPort,
        staging: ImportStagingPort,
        notifier: NotifierPort,
        store: ContentImportStorePort,
        clock: ClockPort,
        add_to_album: Callable[[str, str], Awaitable[None]] | None = None,
        owner: str = PROCESS_OWNER,
    ) -> None:
        self._imports = imports
        self._ingestion = ingestion
        self._staging = staging
        self._notifier = notifier
        self._store = store
        self._clock = clock
        self._add_to_album = add_to_album
        self._owner = owner
        self._lock = threading.Lock()
        self._running: dict[str, ContentImport] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._recovered = False

    async def start(
        self, items: list[ContentImportItem], *, folder_id: str | None = None, album_id: str | None = None
    ) -> ContentImport:
        if not items or len(items) > MAX_IMPORT_ITEMS:
            raise ValidationFailedError("An import needs between 1 and 500 items", {"maximum": MAX_IMPORT_ITEMS})
        await self.recover()
        job = ContentImport(
            id=f"imp_{uuid.uuid4().hex}",
            items=[ImportItemState(client_index=index) for index in range(len(items))],
            folder_id=folder_id,
            album_id=album_id,
        )
        await self._store.create(job, owner=self._owner, at=self._clock.now())
        await self._store.prune(keep=KEEP_FINISHED_IMPORTS)
        with self._lock:
            self._running[job.id] = job
        task = asyncio.get_running_loop().create_task(self._run(job, items))
        self._tasks[job.id] = task
        task.add_done_callback(lambda _task, key=job.id: self._tasks.pop(key, None))
        return job

    async def get(self, import_id: str) -> ContentImport | None:
        with self._lock:
            running = self._running.get(import_id)
        if running is not None:
            return running
        await self.recover()
        return await self._store.get(import_id)

    async def dismiss(self, import_id: str) -> bool:
        """Hides a finished import's Activity item; running imports cannot be dismissed."""
        with self._lock:
            if import_id in self._running:
                return False
        return await self._store.dismiss(import_id, at=self._clock.now())

    async def recover(self) -> int:
        """Once per process: fails the unfinished items of imports an earlier process started (their fds are
        gone). Returns how many items it failed."""
        if self._recovered:
            return 0
        self._recovered = True
        interrupted = 0
        for job in await self._store.unfinished(other_than_owner=self._owner):
            interrupted += job.interrupt()
            await self._store.replace_items(job, finished_at=self._clock.now())
        return interrupted

    async def _run(self, job: ContentImport, items: list[ContentImportItem]) -> None:
        total = len(items)
        try:
            for index, item in enumerate(items):
                state = job.items[index]
                state.status = ImportItemStatus.IMPORTING.value
                await self._store.save_item(job.id, state)
                try:
                    result = await self._import_one(item, folder_id=job.folder_id)
                except DomainError as exc:
                    state.status, state.error = ImportItemStatus.FAILED.value, exc.code[:64]
                except (ContentHandleError, OSError):
                    state.status, state.error = ImportItemStatus.FAILED.value, CONTENT_UNREADABLE
                else:
                    state.asset_id = result.asset.id
                    state.status = ImportItemStatus.DUPLICATE.value if result.duplicate else ImportItemStatus.DONE.value
                    if job.album_id is not None and self._add_to_album is not None:
                        try:
                            await self._add_to_album(job.album_id, result.asset.id)
                        except DomainError:
                            state.error = ALBUM_UNAVAILABLE
                await self._store.save_item(job.id, state)
                self._notifier.emit(transfer_progress("import", done=index + 1, total=total))
        except asyncio.CancelledError:
            # Stopping the engine mid-import: the rest cannot resume (the fds close with the process).
            job.interrupt()
            try:
                await asyncio.shield(self._store.replace_items(job, finished_at=self._clock.now()))
            finally:
                self._forget(job.id)
            raise
        except Exception:
            job.interrupt()
            await self._store.replace_items(job, finished_at=self._clock.now())
            self._forget(job.id)
            raise
        await self._store.finish(job.id, at=self._clock.now())
        job.done = True
        self._forget(job.id)
        failed = job.failed
        self._notifier.emit(transfer_finished("import", count=total - failed, failed=failed))

    def _forget(self, import_id: str) -> None:
        with self._lock:
            self._running.pop(import_id, None)

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
