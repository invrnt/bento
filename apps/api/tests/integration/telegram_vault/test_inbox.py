from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from bento.adapters.fake_telegram import DocumentUpload
from bento.adapters.jobs import SQLiteJobQueue
from bento.adapters.repositories import SQLiteAssetRepository
from bento.adapters.telegram_mtproto.vault_state import SQLiteInboxItems
from bento.application.inbox import InboxService, InboxState
from bento.domain.assets import AssetOrigin
from bento.domain.errors import UploadTooLargeError
from bento.domain.jobs import Job, JobType
from tests.integration.telegram_vault.support import VaultDevice, local_ingestion, make_vault_device


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


class RefusingIngestion:
    async def upload_file(self, file: object) -> object:
        raise UploadTooLargeError(10, 1)


def _inbox(device: VaultDevice, *, keep_hours: int = 24, ingestion: object | None = None) -> tuple[InboxService, SQLiteJobQueue, SQLiteInboxItems]:
    jobs = SQLiteJobQueue(device.sessions, device.clock)
    items = SQLiteInboxItems(device.sessions)
    service = InboxService(
        vault=device.vault,
        transport=lambda: device.runtime.transport,
        items=items,
        state=device.state,
        jobs=jobs,
        devices=device.devices,
        ingestion=ingestion or local_ingestion(device),  # type: ignore[arg-type]
        clock=device.clock,
        temp_dir=device.data_dir / "cache" / "telegram" / "inbox",
        keep_hours=keep_hours,
    )
    return service, jobs, items


async def _queued(jobs: SQLiteJobQueue) -> list[Job]:
    items, _ = await jobs.list(limit=100)
    return [job for job in items if job.type == JobType.INBOX_IMPORT]


async def _ready(tmp_path: Path, name: str = "desk") -> VaultDevice:
    device = make_vault_device(tmp_path, tmp_path / "cloud", name)
    await device.sign_in()
    await device.vault.create()
    return device


def _post(device: VaultDevice, inbox_id: int, data: bytes, filename: str) -> int:
    message = device.cloud.post_message(inbox_id, document=DocumentUpload(data, filename), date=device.clock.now())
    return message.id


def test_inbox_lifecycle_import_react_and_delete_after_the_keep_window(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = await _ready(tmp_path)
        inbox_id = (await device.vault.require()).layout.inbox_channel_id
        service, jobs, items = _inbox(device, keep_hours=24)
        photo = _post(device, inbox_id, b"\xff\xd8 forwarded photo", "foto.jpg")
        device.cloud.post_message(inbox_id, text="just a comment")

        assert await service.scan() == 1
        assert await service.scan() == 0  # recorded: never queued twice
        [job] = await _queued(jobs)
        assert job.payload == {"message_id": photo, "filename": "foto.jpg", "mime_type": "image/jpeg"}
        assert device.cloud.message(inbox_id, photo).reactions == ("👀",)

        asset_id = await service.import_item(job)

        asset = await SQLiteAssetRepository(device.sessions).get(asset_id)
        assert asset is not None and asset.filename == "foto.jpg"
        # Telegram API terms: files from Telegram never feed OCR or embeddings.
        assert asset.origin == AssetOrigin.TELEGRAM_INBOX and not asset.ai_indexing_allowed
        assert device.cloud.message(inbox_id, photo).reactions == ("✅",)
        record = await items.get(photo)
        assert record is not None and record.state == InboxState.DONE and record.asset_id == asset_id
        assert await service.import_item(job) == asset_id  # idempotent on retries

        assert await service.cleanup() == 0
        device.clock.advance(hours=25)
        assert await service.cleanup() == 1
        assert device.cloud.message(inbox_id, photo) is None
        assert (await items.get(photo)).state == InboxState.DELETED  # type: ignore[union-attr]

    run(scenario())


def test_zero_keep_hours_deletes_right_after_import(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = await _ready(tmp_path)
        inbox_id = (await device.vault.require()).layout.inbox_channel_id
        service, jobs, _ = _inbox(device, keep_hours=0)
        message_id = _post(device, inbox_id, b"%PDF-1.4 recibo", "recibo.pdf")
        await service.scan()
        [job] = await _queued(jobs)

        await service.import_item(job)

        assert device.cloud.message(inbox_id, message_id) is None

    run(scenario())


def test_failed_imports_react_with_a_warning_and_are_recorded(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = await _ready(tmp_path)
        inbox_id = (await device.vault.require()).layout.inbox_channel_id
        service, jobs, items = _inbox(device, ingestion=RefusingIngestion())
        message_id = _post(device, inbox_id, b"huge", "huge.bin")
        await service.scan()
        [job] = await _queued(jobs)

        try:
            await service.import_item(job)
        except UploadTooLargeError:
            pass
        else:
            raise AssertionError("the failure must reach the job")

        assert device.cloud.message(inbox_id, message_id).reactions == ("⚠️",)
        record = await items.get(message_id)
        assert record is not None and record.state == InboxState.FAILED and record.error_code == "upload_too_large"
        assert [item.message_id for item in await service.failures()] == [message_id]

    run(scenario())


def test_reactions_fall_back_when_the_channel_restricts_them(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = await _ready(tmp_path)
        inbox_id = (await device.vault.require()).layout.inbox_channel_id
        service, jobs, items = _inbox(device)
        transport = device.runtime.transport
        original = transport.react_inbox_item

        async def picky(layout, message_id, emoji):  # type: ignore[no-untyped-def]
            if emoji != "👍":
                from bento.domain.errors import ValidationFailedError

                raise ValidationFailedError("reaction not allowed")
            await original(layout, message_id, emoji)

        transport.react_inbox_item = picky  # type: ignore[method-assign]
        message_id = _post(device, inbox_id, b"\xff\xd8 photo", "a.jpg")
        await service.scan()
        [job] = await _queued(jobs)
        await service.import_item(job)

        assert device.cloud.message(inbox_id, message_id).reactions == ("👍",)
        assert (await items.get(message_id)).state == InboxState.DONE  # type: ignore[union-attr]

    run(scenario())


def test_devices_of_one_account_import_each_item_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        leader = await _ready(tmp_path, "leader")
        context = await leader.vault.require()
        follower = make_vault_device(tmp_path, tmp_path / "cloud", "follower")
        await follower.sign_in()
        await follower.vault.install(context.layout, context.keyring)
        [leader_row] = await leader.devices.list()
        [follower_row] = await follower.devices.list()
        # Each device knows the other (the sync engine replicates device rows); the leader joined first.
        joined_later = replace(follower_row, added_at=leader_row.added_at + timedelta(hours=1))
        await follower.devices.save(joined_later)
        await follower.devices.save(replace(leader_row, current=False))
        await leader.devices.save(replace(joined_later, current=False))
        inbox_id = context.layout.inbox_channel_id
        leader_inbox, leader_jobs, _ = _inbox(leader)
        follower_inbox, follower_jobs, follower_items = _inbox(follower)

        fresh = _post(leader, inbox_id, b"\xff\xd8 new", "new.jpg")
        assert await follower_inbox.scan() == 0  # the follower waits for the leader
        assert await leader_inbox.scan() == 1
        follower.clock.advance(minutes=5)
        assert await follower_inbox.scan() == 0  # claimed by the leader (👀)
        assert (await follower_items.get(fresh)).state == InboxState.SKIPPED  # type: ignore[union-attr]

        orphan = _post(leader, inbox_id, b"\xff\xd8 orphan", "orphan.jpg")
        follower.clock.advance(minutes=5)
        leader.cloud.set_reaction(inbox_id, orphan, "✅")
        assert await follower_inbox.scan() == 0  # already handled by another device
        unclaimed = _post(follower, inbox_id, b"\xff\xd8 late", "late.jpg")
        follower.clock.advance(minutes=3)
        assert await follower_inbox.scan() == 1  # the leader is away: the follower steps in
        assert [job.payload["message_id"] for job in await _queued(follower_jobs)] == [unclaimed]
        assert [job.payload["message_id"] for job in await _queued(leader_jobs)] == [fresh]

    run(scenario())

