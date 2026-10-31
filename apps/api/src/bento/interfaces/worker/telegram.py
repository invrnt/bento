"""Worker side of the Telegram account: the Inbox loop and the account/import job handlers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from bento.application.inbox import InboxService
from bento.application.ingestion import AssetIngestionService
from bento.application.telegram_import import TelegramImportService
from bento.domain.errors import DomainError, TelegramFloodWaitError, TelegramNotAvailableError
from bento.domain.jobs import Job, JobType
from bento.infrastructure.settings import Settings
from bento.ports.telegram import TelegramChatsPort, VaultTransportPort

LOGGER = logging.getLogger("bento.worker.telegram")

INBOX_POLL_SECONDS = 10.0
IDLE_SECONDS = 5.0
MAX_BACKOFF_SECONDS = 300.0
TELEGRAM_JOB_TYPES = frozenset({JobType.ACCOUNT_RELOAD, JobType.TELEGRAM_IMPORT, JobType.INBOX_IMPORT})


class TelegramJobHandlers:
    """`account_reload`, `telegram_import`, and `inbox_import`."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._inbox: InboxService | None = None
        self._imports: TelegramImportService | None = None

    def handles(self, job: Job) -> bool:
        return job.type in TELEGRAM_JOB_TYPES

    async def handle(self, job: Job) -> None:
        if job.type == JobType.ACCOUNT_RELOAD:
            await reload_account(self._settings)
        elif job.type == JobType.TELEGRAM_IMPORT:
            result = await self.imports().run(job)
            LOGGER.info(
                "Telegram import finished: %s imported, %s already present, %s failed",
                result.imported,
                result.duplicates,
                result.failed,
            )
        elif job.type == JobType.INBOX_IMPORT:
            await self.inbox().import_item(job)
        else:
            raise RuntimeError(f"Not a Telegram job: {job.type.value}")

    def inbox(self) -> InboxService:
        if self._inbox is None:
            self._inbox = create_inbox_service(self._settings)
        return self._inbox

    def imports(self) -> TelegramImportService:
        if self._imports is None:
            self._imports = create_import_service(self._settings)
        return self._imports


async def reload_account(settings: Settings) -> None:
    """The API signed in or out: reconnect with the stored session and forget cached vault state."""
    from bento.infrastructure.mtproto import wiring
    from bento.infrastructure.mtproto.runtime import reload_telegram_session

    try:
        runtime = wiring.telegram_runtime(settings)
    except TelegramNotAvailableError:
        runtime = None
    if runtime is not None:
        await reload_telegram_session(runtime)
    wiring.vault_session(settings).invalidate()


async def run_inbox_loop(settings: Settings, stop_event: asyncio.Event, *, service: InboxService | None = None) -> None:
    """Scan the Inbox on new-message activity (or every 10 s), and delete imported items after the keep window."""
    if settings.storage_backend == "local":
        return
    inbox = service
    failures = 0
    while not stop_event.is_set():
        try:
            inbox = inbox or create_inbox_service(settings)
            await inbox.scan()
            await inbox.cleanup()
            failures = 0
            await _wait_for_activity(settings, stop_event)
            continue
        except TelegramFloodWaitError as exc:
            delay = min(float(exc.retry_after_seconds), MAX_BACKOFF_SECONDS)
        except TelegramNotAvailableError:
            delay = MAX_BACKOFF_SECONDS
        except DomainError as exc:
            failures += 1
            delay = min(IDLE_SECONDS * 2**failures, MAX_BACKOFF_SECONDS)
            LOGGER.info("Inbox scan postponed: %s", exc.code)
        except Exception:  # noqa: BLE001 - the loop must survive anything and retry later
            failures += 1
            delay = min(IDLE_SECONDS * 2**failures, MAX_BACKOFF_SECONDS)
            LOGGER.exception("Inbox scan failed")
        await _sleep(stop_event, delay)


def create_inbox_service(settings: Settings) -> InboxService:
    from bento.adapters.jobs import SQLiteJobQueue
    from bento.adapters.repositories.devices import SQLiteDeviceRepository
    from bento.adapters.telegram_mtproto.vault_state import SQLiteInboxItems, SQLiteVaultState
    from bento.infrastructure.db.clock import SystemClock
    from bento.infrastructure.mtproto import wiring

    sessions = wiring.session_factory(settings)
    clock = SystemClock()

    def transport() -> VaultTransportPort | None:
        runtime = wiring.telegram_runtime(settings)
        return None if runtime is None else runtime.transport

    return InboxService(
        vault=wiring.vault_session(settings),
        transport=transport,
        items=SQLiteInboxItems(sessions),
        state=SQLiteVaultState(sessions, clock),
        jobs=SQLiteJobQueue(sessions, clock),
        devices=SQLiteDeviceRepository(sessions),
        ingestion=create_ingestion_service(settings),
        clock=clock,
        temp_dir=Path(settings.data_dir) / "cache" / "telegram" / "inbox",
        keep_hours=settings.inbox_keep_hours,
    )


def create_import_service(settings: Settings) -> TelegramImportService:
    from bento.adapters.jobs import SQLiteJobQueue
    from bento.infrastructure.db.clock import SystemClock
    from bento.infrastructure.mtproto import wiring

    def chats() -> TelegramChatsPort | None:
        runtime = wiring.telegram_runtime(settings)
        return None if runtime is None else runtime.chats

    return TelegramImportService(
        chats=chats,
        jobs=SQLiteJobQueue(wiring.session_factory(settings), SystemClock()),
        ingestion=create_ingestion_service(settings),
        temp_dir=Path(settings.data_dir) / "cache" / "telegram" / "import",
    )


def create_ingestion_service(settings: Settings) -> AssetIngestionService:
    """The upload endpoint's ingestion: local first, with the vault upload queued right away."""
    from bento.infrastructure.storage_pipeline import get_storage_pipeline

    return get_storage_pipeline(settings).ingestion


async def _wait_for_activity(settings: Settings, stop_event: asyncio.Event) -> None:
    """Until new Sync/Inbox activity, `INBOX_POLL_SECONDS`, or stop; a short pause while there is no vault."""
    from bento.infrastructure.mtproto import wiring

    context = await wiring.vault_session(settings).current()
    runtime = wiring.telegram_runtime(settings) if context is not None else None
    if context is None or runtime is None:
        await _sleep(stop_event, IDLE_SECONDS)
        return
    waiter = asyncio.ensure_future(runtime.transport.wait_for_activity(context.layout, INBOX_POLL_SECONDS))
    stopper = asyncio.ensure_future(stop_event.wait())
    try:
        await asyncio.wait({waiter, stopper}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopper.cancel()
        if not waiter.done():
            # `cancel()` only requests it; the waiter has no result until it has actually finished.
            waiter.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await waiter
    if not waiter.cancelled():
        waiter.result()


async def _sleep(stop_event: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        return
