"""Import photos, videos, and documents from Saved Messages or a chat the person picks.

Original messages are never touched. Items are imported by the `telegram_import` job through the normal
ingestion service, which deduplicates by sha256.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from bento.application.inbox import IngestionPort
from bento.application.ingestion import UploadedAssetFile
from bento.domain.assets import AssetOrigin
from bento.domain.errors import DomainError, StorageUnavailableError, TelegramFloodWaitError, ValidationFailedError
from bento.domain.jobs import Job, JobPriority, JobType
from bento.domain.telegram import TelegramChat, TelegramMediaItem
from bento.ports.jobs import JobQueuePort
from bento.ports.telegram import TelegramChatsPort

LOGGER = logging.getLogger("bento.telegram_import")

PAGE_SIZE = 60
MAX_RESOLVE_PAGES = 20
MAX_IMPORT_ITEMS = 1000

ChatsResolver = Callable[[], TelegramChatsPort | None]


@dataclass(frozen=True, slots=True)
class MediaPage:
    items: tuple[TelegramMediaItem, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ImportQueued:
    job_id: str
    queued: int


@dataclass(frozen=True, slots=True)
class ImportResult:
    imported: int
    duplicates: int
    failed: int


class TelegramImportService:
    def __init__(
        self,
        *,
        chats: ChatsResolver,
        jobs: JobQueuePort,
        ingestion: IngestionPort | None = None,
        temp_dir: Path | str | None = None,
    ) -> None:
        self._chats = chats
        self._jobs = jobs
        self._ingestion = ingestion
        self._temp_dir = Path(temp_dir) if temp_dir is not None else None

    async def list_chats(self, *, query: str | None = None, limit: int = 30) -> tuple[TelegramChat, ...]:
        return await self._require_chats().list_chats(query=query, limit=max(1, min(limit, 100)))

    async def list_media(self, chat_id: int, *, cursor: str | None = None, kind: str = "all") -> MediaPage:
        before = _parse_cursor(cursor)
        items = await self._require_chats().list_media(chat_id, before_message_id=before, limit=PAGE_SIZE, kind=kind)
        next_cursor = str(items[-1].message_id) if len(items) >= PAGE_SIZE else None
        return MediaPage(items=items, next_cursor=next_cursor)

    async def enqueue(self, chat_id: int, *, message_ids: tuple[int, ...] = (), all_items: bool = False) -> ImportQueued:
        if not all_items and not message_ids:
            raise ValidationFailedError("Choose what to import", {"reason": "nothing_selected"})
        wanted = set(message_ids)
        found: list[TelegramMediaItem] = []
        chats = self._require_chats()
        before: int | None = None
        for _ in range(MAX_RESOLVE_PAGES):
            page = await chats.list_media(chat_id, before_message_id=before, limit=PAGE_SIZE, kind="all")
            found.extend(item for item in page if all_items or item.message_id in wanted)
            if len(page) < PAGE_SIZE or len(found) >= MAX_IMPORT_ITEMS or (not all_items and len(found) == len(wanted)):
                break
            before = page[-1].message_id
        selected = found[:MAX_IMPORT_ITEMS]
        if not selected:
            raise ValidationFailedError("Nothing to import in that chat", {"reason": "no_media"})
        job = await self._jobs.enqueue(
            type=JobType.TELEGRAM_IMPORT,
            priority=int(JobPriority.METADATA),
            payload={
                "chat_id": chat_id,
                "items": [
                    {"message_id": item.message_id, "filename": item.filename, "mime_type": item.mime_type}
                    for item in selected
                ],
            },
        )
        return ImportQueued(job_id=job.id, queued=len(selected))

    async def run(self, job: Job) -> ImportResult:
        """`telegram_import` job. Item failures are skipped; the job fails only if nothing could be imported."""
        if self._ingestion is None or self._temp_dir is None:
            raise RuntimeError("Telegram import needs an ingestion service")
        chat_id = int(job.payload["chat_id"])
        items = job.payload.get("items") or []
        chats = self._require_chats()
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        imported = duplicates = failed = 0
        last_error: Exception | None = None
        for item in items:
            message_id = int(item["message_id"])
            with tempfile.NamedTemporaryFile(prefix="import-", dir=self._temp_dir, delete=False) as handle:
                temp_path = Path(handle.name)
            try:
                await chats.download_media(chat_id, message_id, temp_path)
                result = await self._ingestion.upload_file(
                    UploadedAssetFile(
                        source_path=temp_path,
                        original_filename=str(item.get("filename") or f"telegram-{message_id}"),
                        declared_mime_type=item.get("mime_type") or None,
                        origin=AssetOrigin.TELEGRAM_IMPORT,
                    )
                )
            except TelegramFloodWaitError:
                raise
            except DomainError as exc:
                failed += 1
                last_error = exc
                LOGGER.warning("Telegram item %s could not be imported: %s", message_id, exc.code)
                continue
            finally:
                temp_path.unlink(missing_ok=True)
            if result.duplicate:
                duplicates += 1
            else:
                imported += 1
        if items and failed == len(items) and last_error is not None:
            raise last_error
        return ImportResult(imported=imported, duplicates=duplicates, failed=failed)

    def _require_chats(self) -> TelegramChatsPort:
        chats = self._chats()
        if chats is None:
            raise StorageUnavailableError("telegram")
        return chats


def _parse_cursor(cursor: str | None) -> int | None:
    if cursor is None or not cursor.strip():
        return None
    try:
        value = int(cursor)
    except ValueError as exc:
        raise ValidationFailedError("Invalid cursor", {"cursor": cursor}) from exc
    if value <= 0:
        raise ValidationFailedError("Invalid cursor", {"cursor": cursor})
    return value
