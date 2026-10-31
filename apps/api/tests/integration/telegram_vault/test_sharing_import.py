from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bento.adapters.fake_telegram import FAKE_USER
from bento.adapters.jobs import SQLiteJobQueue
from bento.adapters.repositories import SQLiteAssetRepository
from bento.application.ingestion import UploadedAssetFile
from bento.application.sharing import SharingService
from bento.application.telegram_import import PAGE_SIZE, TelegramImportService
from bento.domain.errors import AssetNotFoundError, StorageUnavailableError, ValidationFailedError
from bento.domain.jobs import JobType
from bento.domain.telegram import TelegramChatKind
from tests.integration.telegram_vault.support import local_ingestion, make_vault_device

CARLOS = 777000002


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


class LocalContent:
    def __init__(self, paths: dict[str, Path]) -> None:
        self.paths = paths

    async def materialize_original(self, asset_id: str) -> Path:
        return self.paths[asset_id]

    async def read_range(self, asset_id: str, start: int, length: int) -> bytes:
        return self.paths[asset_id].read_bytes()[start : start + length]


def test_sharing_sends_a_decrypted_copy_with_the_visible_name(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_vault_device(tmp_path, tmp_path / "cloud", "desk")
        await device.sign_in()
        source = tmp_path / "upload.tmp"
        source.write_bytes(b"factura de luz")
        result = await local_ingestion(device).upload_file(UploadedAssetFile(source, "factura.txt", "text/plain"))
        cached = tmp_path / "cache-copy"
        cached.write_bytes(b"factura de luz")
        sharing = SharingService(
            assets=SQLiteAssetRepository(device.sessions),
            content=lambda: LocalContent({result.asset.id: cached}),
            chats=lambda: device.runtime.chats,
        )

        await sharing.share(result.asset.id, CARLOS, caption="  Para ti ")

        message = device.cloud.read_chat(CARLOS)[1][-1]
        assert message.media is not None and message.media.filename == "factura.txt"
        assert message.text == "Para ti"
        assert device.cloud.document_path(CARLOS, message.id).read_bytes() == b"factura de luz"
        with pytest.raises(AssetNotFoundError):
            await sharing.share("asset_missing", CARLOS)
        with pytest.raises(ValidationFailedError):
            await sharing.share(result.asset.id, CARLOS, caption="x" * 1025)
        offline = SharingService(assets=SQLiteAssetRepository(device.sessions), content=lambda: LocalContent({}), chats=lambda: None)
        with pytest.raises(StorageUnavailableError):
            await offline.share(result.asset.id, CARLOS)

    run(scenario())


def test_import_lists_media_queues_a_job_and_dedupes(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_vault_device(tmp_path, tmp_path / "cloud", "desk")
        await device.sign_in()
        await device.vault.create()
        jobs = SQLiteJobQueue(device.sessions, device.clock)
        service = TelegramImportService(
            chats=lambda: device.runtime.chats,
            jobs=jobs,
            ingestion=local_ingestion(device),
            temp_dir=device.data_dir / "cache" / "telegram" / "import",
        )

        chats = await service.list_chats()
        assert chats[0].kind == TelegramChatKind.SAVED and chats[0].id == FAKE_USER.user_id
        assert all(not chat.title.startswith("Bento ·") for chat in chats)
        page = await service.list_media(FAKE_USER.user_id)
        assert [item.filename for item in page.items] == ["atardecer.jpg", "recibo-cafe.pdf"]
        assert page.next_cursor is None
        assert (await service.list_media(FAKE_USER.user_id, kind="photo")).items[0].filename == "atardecer.jpg"
        with pytest.raises(ValidationFailedError):
            await service.list_media(FAKE_USER.user_id, cursor="abc")
        with pytest.raises(ValidationFailedError):
            await service.enqueue(FAKE_USER.user_id)
        with pytest.raises(ValidationFailedError):
            await service.enqueue(FAKE_USER.user_id, message_ids=(999,))

        queued = await service.enqueue(FAKE_USER.user_id, all_items=True)
        assert queued.queued == 2
        job = await jobs.get(queued.job_id)
        assert job is not None and job.type == JobType.TELEGRAM_IMPORT

        result = await service.run(job)

        assert (result.imported, result.duplicates, result.failed) == (2, 0, 0)
        again = await service.run(job)
        assert (again.imported, again.duplicates) == (0, 2)
        # Original messages are untouched.
        assert len([message for message in device.cloud.read_chat(FAKE_USER.user_id)[1] if message.media]) == 2
        single = await service.enqueue(CARLOS, message_ids=(2,))
        assert single.queued == 1

    run(scenario())


def test_import_pages_through_long_chats(tmp_path: Path) -> None:
    async def scenario() -> None:
        from bento.adapters.fake_telegram import DocumentUpload

        device = make_vault_device(tmp_path, tmp_path / "cloud", "desk")
        await device.sign_in()
        cloud = device.cloud
        for index in range(PAGE_SIZE + 5):
            cloud.post_message(CARLOS, document=DocumentUpload(f"nota {index}".encode(), f"nota-{index}.txt"))
        service = TelegramImportService(chats=lambda: device.runtime.chats, jobs=SQLiteJobQueue(device.sessions, device.clock))

        first = await service.list_media(CARLOS)
        assert len(first.items) == PAGE_SIZE and first.next_cursor is not None
        second = await service.list_media(CARLOS, cursor=first.next_cursor)
        assert {item.message_id for item in first.items}.isdisjoint(item.message_id for item in second.items)
        assert (await service.enqueue(CARLOS, all_items=True)).queued == PAGE_SIZE + 5 + 2

    run(scenario())
