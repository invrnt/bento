"""Content imports persist their state and survive restarts (fakes only: no SQLite, no bridge)."""

from __future__ import annotations

import asyncio
import copy
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from bento.application.content_imports import IMPORT_FAILED_ATTENTION, ContentImportItem, ContentImportService
from bento.application.upload import UploadAssetResult
from bento.domain.imports import IMPORT_INTERRUPTED, ContentImport, ImportItemState
from bento.ports.device import ContentDescription, ContentHandleError, NotifierEvent


class MemoryStore:
    def __init__(self) -> None:
        self.jobs: dict[str, tuple[str, ContentImport]] = {}

    async def create(self, job: ContentImport, *, owner: str, at: datetime) -> None:
        self.jobs[job.id] = (owner, copy.deepcopy(job))

    async def save_item(self, import_id: str, item: ImportItemState) -> None:
        self.jobs[import_id][1].items[item.client_index] = copy.deepcopy(item)

    async def finish(self, import_id: str, *, at: datetime) -> None:
        self.jobs[import_id][1].done = True

    async def get(self, import_id: str) -> ContentImport | None:
        found = self.jobs.get(import_id)
        return copy.deepcopy(found[1]) if found else None

    async def unfinished(self, *, other_than_owner: str) -> list[ContentImport]:
        return [copy.deepcopy(job) for owner, job in self.jobs.values() if not job.done and owner != other_than_owner]

    async def replace_items(self, job: ContentImport, *, finished_at: datetime) -> None:
        owner = self.jobs[job.id][0]
        stored = copy.deepcopy(job)
        stored.done = True
        self.jobs[job.id] = (owner, stored)

    async def dismiss(self, import_id: str, *, at: datetime) -> bool:
        found = self.jobs.get(import_id)
        if found is None or not found[1].done:
            return False
        found[1].dismissed = True
        return True

    async def prune(self, *, keep: int) -> None: ...


class Notifier:
    def __init__(self) -> None:
        self.events: list[NotifierEvent] = []

    def emit(self, event: NotifierEvent) -> None:
        self.events.append(event)


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


class Handles:
    """Handle 1 is readable; anything else is unknown. `block` keeps adopt() waiting (a long import)."""

    def __init__(self, tmp: Path) -> None:
        self.path = tmp / "shared.bin"
        self.path.write_bytes(b"payload")
        self.block: asyncio.Event | None = None

    def describe(self, handle: int) -> ContentDescription:
        return ContentDescription(display_name="a.bin", mime_type="application/octet-stream")

    def adopt(self, handle: int) -> int:
        if handle != 1:
            raise ContentHandleError(handle)
        return os.open(self.path, os.O_RDONLY)


class Staging:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp

    def stage(self, stream: BinaryIO, filename: str) -> Path:
        target = self.tmp / f"staged-{filename}"
        target.write_bytes(stream.read())
        return target


class Ingestion:
    def __init__(self) -> None:
        self.gate: asyncio.Event | None = None

    async def upload_file(self, file) -> UploadAssetResult:  # noqa: ANN001
        if self.gate is not None:
            await self.gate.wait()

        class _Asset:
            id = "asset_1"

        return UploadAssetResult(asset=_Asset(), blob_ref=None, duplicate=False)  # type: ignore[arg-type]


def _service(tmp: Path, store: MemoryStore, notifier: Notifier, ingestion: Ingestion, owner: str) -> ContentImportService:
    return ContentImportService(
        imports=Handles(tmp),
        ingestion=ingestion,
        staging=Staging(tmp),
        notifier=notifier,
        store=store,
        clock=Clock(),
        owner=owner,
    )


def test_progress_is_persisted_and_failures_raise_attention(tmp_path: Path) -> None:
    async def scenario() -> None:
        store, notifier = MemoryStore(), Notifier()
        service = _service(tmp_path, store, notifier, Ingestion(), owner="p1")
        job = await service.start([ContentImportItem(fd_handle=1), ContentImportItem(fd_handle=7)])
        while not (await service.get(job.id)).done:  # type: ignore[union-attr]
            await asyncio.sleep(0.01)
        stored = await store.get(job.id)
        assert stored is not None and stored.done
        assert [(item.status, item.error) for item in stored.items] == [("done", None), ("failed", "content_unreadable")]
        names = [event.name for event in notifier.events]
        assert names[-2:] == ["attention", "transfer_finished"]
        assert notifier.events[-2].payload == {"code": IMPORT_FAILED_ATTENTION, "count": 1}

    asyncio.run(scenario())


def test_a_restart_fails_the_unfinished_items_with_import_interrupted(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = MemoryStore()
        ingestion = Ingestion()
        ingestion.gate = asyncio.Event()  # the first process never gets past the first item
        first = _service(tmp_path, store, Notifier(), ingestion, owner="p1")
        job = await first.start([ContentImportItem(fd_handle=1), ContentImportItem(fd_handle=1)])
        await asyncio.sleep(0.05)
        assert [item.status for item in (await store.get(job.id)).items] == ["importing", "pending"]  # type: ignore[union-attr]

        # A new process (another owner) finds it: the fds died with the old one.
        notifier = Notifier()
        second = _service(tmp_path, store, notifier, Ingestion(), owner="p2")
        recovered = await second.get(job.id)
        assert recovered is not None and recovered.done
        assert [(item.status, item.error) for item in recovered.items] == [("failed", IMPORT_INTERRUPTED)] * 2
        assert [event.payload for event in notifier.events] == [{"code": IMPORT_FAILED_ATTENTION, "count": 1}]
        assert await second.recover() == 0  # once per process
        assert await second.dismiss(job.id) is True
        ingestion.gate.set()

    asyncio.run(scenario())


def test_running_imports_are_not_dismissed_nor_interrupted_by_their_own_process(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = MemoryStore()
        ingestion = Ingestion()
        ingestion.gate = asyncio.Event()
        service = _service(tmp_path, store, Notifier(), ingestion, owner="p1")
        job = await service.start([ContentImportItem(fd_handle=1)])
        await asyncio.sleep(0.02)
        assert await service.dismiss(job.id) is False
        assert await service.recover() == 0
        ingestion.gate.set()
        while not (await service.get(job.id)).done:  # type: ignore[union-attr]
            await asyncio.sleep(0.01)

    asyncio.run(scenario())
