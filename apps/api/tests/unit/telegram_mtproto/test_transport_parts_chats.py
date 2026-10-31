from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path

import pytest
from telethon import errors, functions, types, utils

from bento.adapters.telegram_mtproto.chats import MtprotoTelegramChats
from bento.adapters.telegram_mtproto.parts import REQUEST_SIZE, MtprotoRemotePartStore
from bento.adapters.telegram_mtproto.transport import MtprotoVaultTransport
from bento.domain.errors import StorageUnavailableError, TelegramFloodWaitError, ValidationFailedError
from bento.domain.sync import SyncMessageKind
from bento.domain.telegram import RemotePart, TelegramChatKind, TelegramMediaKind
from bento.domain.vault import CHANNEL_TITLES, VaultChannelRole, VaultLayout, channel_about
from bento.infrastructure.mtproto.transfer import TokenBucket, TransferLimits
from tests.unit.telegram_mtproto.fake_telethon import ME, FakeTelethonClient, bento_channel, fail_on, make_session


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


def _signed_in(**session_options: object) -> tuple[FakeTelethonClient, object]:
    client = FakeTelethonClient("1signed-in")
    session, _ = make_session(client, **session_options)  # type: ignore[arg-type]
    return client, session


def _layout(client: FakeTelethonClient) -> VaultLayout:
    ids = {}
    for role in VaultChannelRole:
        channel = bento_channel(client, CHANNEL_TITLES[role.value], channel_about(role, "vlt_test"))
        ids[role] = utils.get_peer_id(channel.entity)
    return VaultLayout("vlt_test", ids[VaultChannelRole.FILES], ids[VaultChannelRole.SYNC], ids[VaultChannelRole.INBOX])


def test_create_vault_builds_broadcast_channels_mutes_archives_and_folders() -> None:
    async def scenario() -> None:
        client, session = _signed_in()
        bento_channel(client, "Bento · Archivos", channel_about(VaultChannelRole.FILES, "vlt_other"))
        bento_channel(client, "Bento fan club", "no marker")
        transport = MtprotoVaultTransport(session)  # type: ignore[arg-type]

        layout = await transport.create_vault("vlt_new")

        created = client.requests_of(functions.channels.CreateChannelRequest)
        assert [(request.title, request.about, request.broadcast) for request in created] == [
            (CHANNEL_TITLES[role.value], channel_about(role, "vlt_new"), True) for role in VaultChannelRole
        ]
        mutes = client.requests_of(functions.account.UpdateNotifySettingsRequest)
        assert len(mutes) == 3 and all(request.settings.mute_until == 2**31 - 1 for request in mutes)
        [folders] = client.requests_of(functions.folders.EditPeerFoldersRequest)
        archived = {utils.get_peer_id(item.peer): item.folder_id for item in folders.folder_peers}
        assert archived == {layout.files_channel_id: 1, layout.sync_channel_id: 1, layout.inbox_channel_id: 0}
        [folder] = client.requests_of(functions.messages.UpdateDialogFilterRequest)
        assert folder.id == 2 and folder.filter.title.text == "Bento"
        assert {utils.get_peer_id(peer) for peer in folder.filter.include_peers} == {
            layout.files_channel_id, layout.sync_channel_id, layout.inbox_channel_id
        }

        assert await transport.create_vault("vlt_new") == layout  # idempotent
        assert len(client.requests_of(functions.channels.CreateChannelRequest)) == 3
        assert len(client.requests_of(functions.messages.UpdateDialogFilterRequest)) == 1
        assert await transport.find_vaults() == (layout,)
        with pytest.raises(ValidationFailedError):
            await transport.create_vault("bad id")

    run(scenario())


def test_folder_and_mute_refusals_do_not_block_vault_creation() -> None:
    async def scenario() -> None:
        client, session = _signed_in()
        client.failures = [
            fail_on("UpdateNotifySettingsRequest", errors.ChannelPrivateError(request=None)),
            fail_on("GetDialogFiltersRequest", errors.FilterIdInvalidError(request=None)),
        ]
        layout = await MtprotoVaultTransport(session).create_vault("vlt_new")  # type: ignore[arg-type]
        assert layout.vault_id == "vlt_new"

        client2, session2 = _signed_in()
        client2.failures = [fail_on("CreateChannelRequest", errors.FloodWaitError(request=None, capture=3600))]
        with pytest.raises(TelegramFloodWaitError):
            await MtprotoVaultTransport(session2).create_vault("vlt_new")  # type: ignore[arg-type]

    run(scenario())


def test_header_is_posted_as_plain_text_pinned_and_the_previous_unpinned() -> None:
    async def scenario() -> None:
        client, session = _signed_in()
        layout = _layout(client)
        transport = MtprotoVaultTransport(session)  # type: ignore[arg-type]
        assert await transport.read_header_text(layout) is None
        header = json.dumps({"bento": "vault-header", "mac": "a__b__c"})

        first = await transport.publish_header_text(layout, header)
        second = await transport.publish_header_text(layout, header.replace("a__b", "z__b"))

        assert all(call["parse_mode"] is None for call in client.calls_of("send_message"))
        assert client.calls_of("unpin_message") == [{"id": first}]
        assert await transport.read_header_text(layout) == header.replace("a__b", "z__b")
        sync = client.channel(layout.sync_channel_id)
        assert sync.pinned == second
        assert not [message for message in sync.messages if message.action is not None]  # service messages removed
        with pytest.raises(ValidationFailedError):
            await transport.publish_header_text(layout, "x" * 4097)

    run(scenario())


def test_sync_documents_and_listing() -> None:
    async def scenario() -> None:
        client, session = _signed_in()
        layout = _layout(client)
        transport = MtprotoVaultTransport(session)  # type: ignore[arg-type]

        batch = await transport.post_sync_document(layout, SyncMessageKind.BATCH, b"sealed")
        text = await transport.post_sync_text(layout, SyncMessageKind.PAIRING, '{"bento": "pair_request"}')
        client.post(layout.sync_channel_id, message="hello, not bento")
        client.post(layout.sync_channel_id, data=b"x", filename="photo.jpg")
        await transport.publish_header_text(layout, '{"bento": "vault-header"}')

        [upload] = client.calls_of("send_file")
        assert upload["force_document"] is True and isinstance(upload["file"], io.BytesIO)
        assert upload["attributes"][0].file_name == batch.filename and batch.filename.endswith(".bsync")
        listed = await transport.list_sync_messages(layout, after_message_id=0)
        assert [(ref.kind, ref.message_id) for ref in listed] == [
            (SyncMessageKind.BATCH, batch.message_id),
            (SyncMessageKind.PAIRING, text.message_id),
            (SyncMessageKind.HEADER, listed[-1].message_id),
        ]
        assert listed[1].text == '{"bento": "pair_request"}'
        assert await transport.list_sync_messages(layout, after_message_id=batch.message_id, limit=1) == (listed[1],)
        assert client.calls_of("iter_messages")[-1]["reverse"] is True
        with pytest.raises(ValidationFailedError):
            await transport.post_sync_document(layout, SyncMessageKind.HEADER, b"")

        client.expire_downloads_after = 0
        assert await transport.download_sync_document(layout, batch.message_id) == b"sealed"
        assert len(client.calls_of("download_media")) == 2  # retried with a refreshed message
        # The size limit is checked on the freshly fetched message, before anything is downloaded.
        with pytest.raises(ValidationFailedError):
            await transport.download_sync_document(layout, batch.message_id, max_bytes=5)
        assert len(client.calls_of("download_media")) == 2
        assert await transport.download_sync_document(layout, batch.message_id, max_bytes=6) == b"sealed"
        await transport.delete_sync_messages(layout, (batch.message_id,))
        with pytest.raises(StorageUnavailableError):
            await transport.download_sync_document(layout, batch.message_id)

    run(scenario())


def test_inbox_listing_reactions_and_activity(tmp_path: Path) -> None:
    async def scenario() -> None:
        client, session = _signed_in()
        layout = _layout(client)
        transport = MtprotoVaultTransport(session)  # type: ignore[arg-type]
        photo = client.post(layout.inbox_channel_id, data=b"\xff\xd8", photo=object(), mime_type="image/jpeg")
        video = client.post(layout.inbox_channel_id, data=b"mp4", filename="clip.mp4", mime_type="video/mp4", video=object())
        client.post(layout.inbox_channel_id, message="text only")
        client.post(layout.inbox_channel_id, data=b"webp", filename="s.webp", sticker=object())

        items = await transport.list_inbox(layout, after_message_id=0)

        assert [(item.message_id, item.kind, item.filename) for item in items] == [
            (photo.id, TelegramMediaKind.PHOTO, f"telegram-{photo.id}.jpg"),
            (video.id, TelegramMediaKind.VIDEO, "clip.mp4"),
        ]
        await transport.react_inbox_item(layout, photo.id, "✅")
        [reaction] = client.requests_of(functions.messages.SendReactionRequest)
        assert reaction.msg_id == photo.id and reaction.reaction == [types.ReactionEmoji(emoticon="✅")]
        assert (await transport.list_inbox(layout, after_message_id=0))[0].reactions == ("✅",)
        client.allowed_reactions = {"👍"}
        with pytest.raises(ValidationFailedError):
            await transport.react_inbox_item(layout, photo.id, "✅")

        destination = tmp_path / "inbox.bin"
        await transport.download_inbox_item(layout, video.id, destination)
        assert destination.read_bytes() == b"mp4"
        await transport.delete_inbox_items(layout, (photo.id,))
        assert [item.message_id for item in await transport.list_inbox(layout, after_message_id=0)] == [video.id]

        assert await transport.wait_for_activity(layout, 0.01) is False
        [(callback, event)] = client.handlers
        await callback(event)
        assert await transport.wait_for_activity(layout, 1.0) is True

    run(scenario())


def test_parts_upload_with_filename_bandwidth_and_albums(tmp_path: Path) -> None:
    async def scenario() -> None:
        consumed: list[int] = []

        class Limits(TransferLimits):
            async def consume_upload(self, size_bytes: int) -> None:
                consumed.append(size_bytes)

        client, session = _signed_in(transfers=Limits(parallel_transfers=1, upload_bucket=TokenBucket(lambda: 0)))
        layout = _layout(client)
        parts = MtprotoRemotePartStore(session)  # type: ignore[arg-type]
        source = tmp_path / "cipher.tmp"
        source.write_bytes(b"c" * 1000)

        part = await parts.upload_part(layout, source, filename="abc.bpart")

        [call] = client.calls_of("send_file")
        assert call["force_document"] is True and call["attributes"][0].file_name == "abc.bpart"
        assert call["mime_type"] == "application/octet-stream"
        assert part == RemotePart(channel_id=layout.files_channel_id, message_id=part.message_id, size_bytes=1000)
        assert sum(consumed) == 1000  # every uploaded byte went through the bandwidth budget

        items = []
        for index in range(12):
            path = tmp_path / f"tmp-{index}"
            path.write_bytes(bytes([index]) * (index + 1))
            items.append((path, f"part-{index}.bpart"))
        uploaded = await parts.upload_parts(layout, items)

        albums = [call["file"] for call in client.calls_of("send_file")[1:]]
        assert [len(album) for album in albums] == [10, 2]
        assert [Path(name).name for name in albums[0][:2]] == ["part-0.bpart", "part-1.bpart"]
        assert [item.size_bytes for item in uploaded] == list(range(1, 13))

    run(scenario())


def test_part_downloads_resume_after_a_file_reference_refresh(tmp_path: Path) -> None:
    async def scenario() -> None:
        client, session = _signed_in()
        layout = _layout(client)
        data = os.urandom(3 * REQUEST_SIZE + 123)
        message = client.post(layout.files_channel_id, data=data, filename="x.bpart")
        part = RemotePart(layout.files_channel_id, message.id, len(data))
        parts = MtprotoRemotePartStore(session)  # type: ignore[arg-type]
        client.expire_downloads_after = 2  # two chunks, then the reference expires

        destination = await parts.download_part(part, tmp_path / "part.bin")

        assert destination.read_bytes() == data
        offsets = [call["offset"] for call in client.calls_of("iter_download")]
        assert offsets == [0, 2 * REQUEST_SIZE]  # resumed where it stopped, nothing fetched twice
        assert client.downloaded_bytes == len(data)

        client.downloaded_bytes = 0
        start = REQUEST_SIZE + 10
        assert await parts.read_part_range(part, start, 50) == data[start : start + 50]
        assert client.calls_of("iter_download")[-1]["offset"] == REQUEST_SIZE
        assert client.downloaded_bytes == REQUEST_SIZE  # only the chunk holding the range
        assert await parts.read_part_range(part, len(data) - 5, 100) == data[-5:]
        assert await parts.read_part_range(part, len(data), 10) == b""

        await parts.delete_parts((part,))
        with pytest.raises(StorageUnavailableError):
            await parts.download_part(part, tmp_path / "gone.bin")

    run(scenario())


def test_chats_hide_vault_channels_and_classify_the_rest(tmp_path: Path) -> None:
    async def scenario() -> None:
        client, session = _signed_in()
        layout = _layout(client)
        friend = types.User(id=777000002, first_name="Carlos", access_hash=3)
        group = types.Chat(id=400000001, title="Familia", photo=types.ChatPhotoEmpty(), participants_count=3, date=None, version=1)
        news = types.Channel(id=55, title="Noticias", photo=types.ChatPhotoEmpty(), date=None, broadcast=True, access_hash=5)
        from tests.unit.telegram_mtproto.fake_telethon import FakeDialog

        for entity, name in ((friend, "Carlos Ruiz"), (group, "Familia"), (news, "Noticias")):
            client.dialogs.append(FakeDialog(utils.get_peer_id(entity), entity, utils.get_input_peer(entity), name))
        chats = MtprotoTelegramChats(session)  # type: ignore[arg-type]

        listed = await chats.list_chats()

        assert [(chat.title, chat.kind) for chat in listed] == [
            ("Saved Messages", TelegramChatKind.SAVED),
            ("Carlos Ruiz", TelegramChatKind.USER),
            ("Familia", TelegramChatKind.GROUP),
            ("Noticias", TelegramChatKind.CHANNEL),
        ]
        assert all(chat.id not in {layout.files_channel_id, layout.sync_channel_id, layout.inbox_channel_id} for chat in listed)
        assert [chat.title for chat in await chats.list_chats(query="fam")] == ["Familia"]

        source = tmp_path / "plain"
        source.write_bytes(b"hola")
        await chats.send_file(friend.id, source, filename="carta.pdf", caption="Para ti")
        sent = client.calls_of("send_file")[-1]
        assert sent["force_document"] is True and sent["caption"] == "Para ti" and sent["parse_mode"] is None
        assert sent["attributes"][0].file_name == "carta.pdf" and sent["mime_type"] == "application/pdf"
        with pytest.raises(ValidationFailedError):
            await chats.send_file(friend.id, source, filename="a.txt", caption="x" * 1025)

        me = utils.get_peer_id(ME)
        client.post(me, message="note")
        photo = client.post(me, data=b"\xff\xd8", photo=object(), mime_type="image/jpeg")
        document = client.post(me, data=b"%PDF", filename="r.pdf", mime_type="application/pdf")
        media = await chats.list_media(me)
        assert [(item.message_id, item.kind) for item in media] == [
            (document.id, TelegramMediaKind.DOCUMENT), (photo.id, TelegramMediaKind.PHOTO)
        ]
        photos = await chats.list_media(me, kind="photo")
        assert [item.message_id for item in photos] == [photo.id]
        assert isinstance(client.calls_of("iter_messages")[-1]["filter"], types.InputMessagesFilterPhotos)
        assert [item.message_id for item in await chats.list_media(me, before_message_id=document.id)] == [photo.id]
        with pytest.raises(ValidationFailedError):
            await chats.list_media(me, kind="sticker")
        await chats.download_media(me, document.id, tmp_path / "r.pdf")
        assert (tmp_path / "r.pdf").read_bytes() == b"%PDF"

    run(scenario())
