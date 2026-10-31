from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from bento.adapters.fake_telegram import DocumentUpload, FakeTelegramCloud
from bento.domain.errors import StorageUnavailableError, ValidationFailedError
from bento.domain.sync import SyncMessageKind
from bento.domain.telegram import RemotePart, TelegramMediaKind
from bento.domain.vault import CHANNEL_TITLES, channel_about, VaultChannelRole, VaultLayout
from tests.integration.fake_telegram.support import make_device, run, sign_in


async def _vault(tmp_path: Path, vault_id: str = "vlt_demo"):
    device = make_device(tmp_path)
    await sign_in(device)
    layout = await device.runtime.transport.create_vault(vault_id)
    return device, layout


def test_create_vault_builds_channels_folder_and_is_idempotent(tmp_path: Path) -> None:
    async def scenario() -> None:
        device, layout = await _vault(tmp_path)
        cloud = FakeTelegramCloud(tmp_path)

        assert await device.runtime.transport.create_vault("vlt_demo") == layout
        assert await device.runtime.transport.find_vaults() == (layout,)
        for role in VaultChannelRole:
            chat = cloud.chat(layout.channel_id(role))
            assert chat.title == CHANNEL_TITLES[role.value]
            assert chat.about == channel_about(role, "vlt_demo")
            assert chat.creator and chat.muted
            assert chat.archived is (role != VaultChannelRole.INBOX)
            assert str(chat.id).startswith("-100")
        assert set(cloud.folders()["Bento"]) == {
            layout.files_channel_id,
            layout.sync_channel_id,
            layout.inbox_channel_id,
        }
        with pytest.raises(ValidationFailedError):
            await device.runtime.transport.create_vault("not a vault id")

    run(scenario())


def test_create_vault_completes_a_partially_created_vault(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_device(tmp_path)
        await sign_in(device)
        cloud = FakeTelegramCloud(tmp_path)
        files = cloud.create_channel(CHANNEL_TITLES["files"], channel_about(VaultChannelRole.FILES, "vlt_half"))

        layout = await device.runtime.transport.create_vault("vlt_half")

        assert layout.files_channel_id == files.id
        assert await device.runtime.transport.find_vaults() == (layout,)

    run(scenario())


def test_find_vaults_follows_discovery_rules(tmp_path: Path) -> None:
    async def scenario() -> None:
        device, layout = await _vault(tmp_path)
        cloud = FakeTelegramCloud(tmp_path)
        for role in VaultChannelRole:
            cloud.create_channel(f"Bento · {role.value}", channel_about(role, "vlt_foreign"), creator=False)
        cloud.create_channel("Bento · Archivos", channel_about(VaultChannelRole.FILES, "vlt_incomplete"))
        cloud.create_channel("Noticias", channel_about(VaultChannelRole.SYNC, "vlt_retitled"))
        second = await device.runtime.transport.create_vault("vlt_second")

        assert await device.runtime.transport.find_vaults() == (layout, second)

    run(scenario())


def test_header_is_posted_pinned_and_replaced(tmp_path: Path) -> None:
    async def scenario() -> None:
        device, layout = await _vault(tmp_path)
        transport = device.runtime.transport
        assert await transport.read_header_text(layout) is None

        first = await transport.publish_header_text(layout, '{"bento":"vault-header","v":1,"n":1}')
        second = await transport.publish_header_text(layout, '{"bento":"vault-header","v":1,"n":2}')

        assert second > first
        assert await transport.read_header_text(layout) == '{"bento":"vault-header","v":1,"n":2}'
        assert FakeTelegramCloud(tmp_path).message(layout.sync_channel_id, first) is not None
        with pytest.raises(ValidationFailedError):
            await transport.publish_header_text(layout, "x" * 4097)
        await transport.delete_sync_messages(layout, (second,))
        assert await transport.read_header_text(layout) is None

    run(scenario())


def test_sync_documents_and_text_are_listed_in_order_with_kinds(tmp_path: Path) -> None:
    async def scenario() -> None:
        device, layout = await _vault(tmp_path)
        transport = device.runtime.transport
        batch = await transport.post_sync_document(layout, SyncMessageKind.BATCH, b"sealed-batch")
        header = await transport.publish_header_text(layout, '{"bento":"vault-header","v":1}')
        pairing = await transport.post_sync_text(layout, SyncMessageKind.PAIRING, '{"bento":"pair_request","id":"r1"}')
        FakeTelegramCloud(tmp_path).post_message(layout.sync_channel_id, text="hola desde el móvil")
        snapshot = await transport.post_sync_document(layout, SyncMessageKind.SNAPSHOT, b"s" * 300)

        listed = await transport.list_sync_messages(layout, after_message_id=0)

        assert [(item.message_id, item.kind) for item in listed] == [
            (batch.message_id, SyncMessageKind.BATCH),
            (header, SyncMessageKind.HEADER),
            (pairing.message_id, SyncMessageKind.PAIRING),
            (snapshot.message_id, SyncMessageKind.SNAPSHOT),
        ]
        assert listed[0] == batch and batch.filename.endswith(".bsync") and batch.size_bytes == 12
        assert listed[2].text == '{"bento":"pair_request","id":"r1"}' and listed[2].filename == ""
        assert snapshot.filename.endswith(".bsnap")
        assert await transport.list_sync_messages(layout, after_message_id=header, limit=1) == (listed[2],)
        assert await transport.download_sync_document(layout, batch.message_id) == b"sealed-batch"
        assert await transport.download_sync_document(layout, batch.message_id, max_bytes=12) == b"sealed-batch"
        with pytest.raises(ValidationFailedError):
            await transport.download_sync_document(layout, batch.message_id, max_bytes=11)
        with pytest.raises(ValidationFailedError):
            await transport.post_sync_document(layout, SyncMessageKind.HEADER, b"{}")

        await transport.delete_sync_messages(layout, (batch.message_id, 999))

        assert [item.message_id for item in await transport.list_sync_messages(layout, after_message_id=0)] == [
            header,
            pairing.message_id,
            snapshot.message_id,
        ]
        with pytest.raises(StorageUnavailableError):
            await transport.download_sync_document(layout, batch.message_id)
        with pytest.raises(StorageUnavailableError):
            await transport.download_sync_document(layout, pairing.message_id)

    run(scenario())


def test_wait_for_activity_detects_new_sync_and_inbox_messages(tmp_path: Path) -> None:
    async def scenario() -> None:
        device, layout = await _vault(tmp_path)
        transport = device.runtime.transport
        cloud = FakeTelegramCloud(tmp_path)
        await transport.list_sync_messages(layout, after_message_id=0)
        await transport.list_inbox(layout, after_message_id=0)

        started = time.monotonic()
        assert await transport.wait_for_activity(layout, 0.3) is False
        assert time.monotonic() - started >= 0.3

        async def post_later(channel_id: int) -> None:
            await asyncio.sleep(0.25)
            await asyncio.to_thread(
                cloud.post_message, channel_id, document=DocumentUpload(b"x", "photo.jpg", "image/jpeg")
            )

        for channel_id in (layout.sync_channel_id, layout.inbox_channel_id):
            waiter = asyncio.create_task(transport.wait_for_activity(layout, 5))
            await post_later(channel_id)
            started = time.monotonic()
            assert await waiter is True
            assert time.monotonic() - started < 1

        # Arrivals between a listing and the wait are not missed, and are reported once.
        await transport.list_sync_messages(layout, after_message_id=0)
        cloud.post_message(layout.sync_channel_id, text='{"bento":"pair_offer"}')
        assert await transport.wait_for_activity(layout, 5) is True
        assert await transport.wait_for_activity(layout, 0.2) is False

    run(scenario())


def test_inbox_items_download_react_and_delete(tmp_path: Path) -> None:
    async def scenario() -> None:
        device, layout = await _vault(tmp_path)
        transport = device.runtime.transport
        cloud = FakeTelegramCloud(tmp_path)
        cloud.post_message(layout.inbox_channel_id, text="solo texto")
        photo = cloud.post_message(
            layout.inbox_channel_id, document=DocumentUpload(b"jpeg-bytes", "foto.jpg"), text="mira"
        )
        report = cloud.post_message(layout.inbox_channel_id, document=DocumentUpload(b"%PDF", "informe.pdf"))

        items = await transport.list_inbox(layout, after_message_id=0)

        assert [(item.message_id, item.kind, item.filename, item.mime_type, item.size_bytes) for item in items] == [
            (photo.id, TelegramMediaKind.PHOTO, "foto.jpg", "image/jpeg", 10),
            (report.id, TelegramMediaKind.DOCUMENT, "informe.pdf", "application/pdf", 4),
        ]
        assert await transport.list_inbox(layout, after_message_id=photo.id) == (items[1],)
        assert await transport.list_inbox(layout, after_message_id=0, limit=1) == (items[0],)
        target = await transport.download_inbox_item(layout, photo.id, tmp_path / "out" / "foto.jpg")
        assert target.read_bytes() == b"jpeg-bytes"

        await transport.react_inbox_item(layout, photo.id, "⚠️")
        await transport.react_inbox_item(layout, photo.id, "✅")
        assert cloud.message(layout.inbox_channel_id, photo.id).reactions == ("✅",)  # type: ignore[union-attr]
        with pytest.raises(StorageUnavailableError):
            await transport.react_inbox_item(layout, 999, "✅")

        await transport.delete_inbox_items(layout, (photo.id,))
        assert [item.message_id for item in await transport.list_inbox(layout, after_message_id=0)] == [report.id]

    run(scenario())


def test_remote_parts_upload_download_range_and_delete(tmp_path: Path) -> None:
    async def scenario() -> None:
        device, layout = await _vault(tmp_path)
        parts = device.runtime.parts
        source = tmp_path / "part.bin"
        source.write_bytes(bytes(range(256)) * 4)

        first = await parts.upload_part(layout, source, filename="a1b2.bpart")
        second = await parts.upload_part(layout, source, filename="c3d4.bpart")

        assert first == RemotePart(channel_id=layout.files_channel_id, message_id=first.message_id, size_bytes=1024)
        assert second.message_id == first.message_id + 1
        downloaded = await parts.download_part(first, tmp_path / "down" / "part.bin")
        assert downloaded.read_bytes() == source.read_bytes()
        assert await parts.read_part_range(first, 250, 10) == bytes([250, 251, 252, 253, 254, 255, 0, 1, 2, 3])
        assert await parts.read_part_range(first, 1020, 100) == bytes([252, 253, 254, 255])
        with pytest.raises(ValidationFailedError):
            await parts.read_part_range(first, -1, 1)
        chat_message = FakeTelegramCloud(tmp_path).message(layout.files_channel_id, first.message_id)
        assert chat_message is not None and chat_message.media is not None
        assert (chat_message.media.filename, chat_message.media.mime_type) == ("a1b2.bpart", "application/octet-stream")

        await parts.delete_parts((first, second, RemotePart(layout.files_channel_id, 999, 1)))

        with pytest.raises(StorageUnavailableError):
            await parts.download_part(first, tmp_path / "gone.bin")
        assert not list((tmp_path / "chats" / str(layout.files_channel_id) / "docs").iterdir())

    run(scenario())


def test_vault_calls_require_a_signed_in_instance(tmp_path: Path) -> None:
    async def scenario() -> None:
        _, layout = await _vault(tmp_path)
        stranger = make_device(tmp_path)

        for call in (
            stranger.runtime.transport.find_vaults(),
            stranger.runtime.transport.read_header_text(layout),
            stranger.runtime.parts.read_part_range(RemotePart(layout.files_channel_id, 1, 1), 0, 1),
            stranger.runtime.chats.list_chats(),
        ):
            with pytest.raises(Exception) as error:
                await call
            assert getattr(error.value, "code", None) == "telegram_not_authorized"
        missing = VaultLayout(vault_id="vlt_x", files_channel_id=-1, sync_channel_id=-2, inbox_channel_id=-3)
        device, _ = await _vault(tmp_path / "other")
        with pytest.raises(StorageUnavailableError):
            await device.runtime.transport.list_sync_messages(missing, after_message_id=0)

    run(scenario())
