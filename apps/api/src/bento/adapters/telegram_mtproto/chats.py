"""`TelegramChatsPort` over Telethon: chats the person may pick for sharing and import.

Bento's own vault channels are never offered, and nothing is read from or sent to a chat the person did not pick.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from telethon import functions, types

from bento.adapters.telegram_mtproto.media import message_media
from bento.adapters.telegram_mtproto.session import MtprotoSession
from bento.adapters.telegram_mtproto.transport import download_message
from bento.domain.errors import ValidationFailedError
from bento.domain.telegram import TelegramChat, TelegramChatKind, TelegramMediaItem, TelegramMediaKind
from bento.domain.vault import VAULT_TITLE_PREFIX, parse_channel_marker

SAVED_MESSAGES_TITLE = "Saved Messages"
MAX_CAPTION_CHARS = 1024
DIALOG_SCAN_LIMIT = 300
MEDIA_FILTERS = {"all", *(kind.value for kind in TelegramMediaKind)}
_SERVER_FILTERS: dict[str, Any] = {
    TelegramMediaKind.PHOTO.value: types.InputMessagesFilterPhotos,
    TelegramMediaKind.VIDEO.value: types.InputMessagesFilterVideo,
    TelegramMediaKind.AUDIO.value: types.InputMessagesFilterMusic,
    TelegramMediaKind.DOCUMENT.value: types.InputMessagesFilterDocument,
}


class MtprotoTelegramChats:
    def __init__(self, session: MtprotoSession) -> None:
        self._session = session

    async def list_chats(self, *, query: str | None = None, limit: int = 30) -> tuple[TelegramChat, ...]:
        needle = (query or "").strip().casefold()
        wanted = max(0, limit)

        async def scan(client: Any) -> tuple[TelegramChat, ...]:
            saved: list[TelegramChat] = []
            others: list[TelegramChat] = []
            async for dialog in client.iter_dialogs(limit=DIALOG_SCAN_LIMIT):
                chat = await self._chat(client, dialog)
                if chat is None or needle not in chat.title.casefold():
                    continue
                (saved if chat.kind == TelegramChatKind.SAVED else others).append(chat)
                if len(saved) + len(others) >= wanted and saved:
                    break
            if not saved and needle in SAVED_MESSAGES_TITLE.casefold():
                me = await client.get_me()
                if me is not None:
                    saved.append(TelegramChat(id=int(me.id), title=SAVED_MESSAGES_TITLE, kind=TelegramChatKind.SAVED))
            return tuple((saved + others)[:wanted])

        return await self._session.call(scan)

    async def send_file(self, chat_id: int, source: Path, *, filename: str, caption: str | None = None) -> None:
        if caption is not None and len(caption) > MAX_CAPTION_CHARS:
            raise ValidationFailedError("Caption is too long", {"max_length": MAX_CAPTION_CHARS})
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        async def send(client: Any) -> None:
            peer = await self._session.input_peer(client, chat_id)
            async with self._session.transfers.upload_slot():
                await client.send_file(
                    peer,
                    str(source),
                    caption=caption or "",
                    parse_mode=None,
                    force_document=True,
                    attributes=[types.DocumentAttributeFilename(file_name=filename)],
                    mime_type=mime_type,
                )

        await self._session.call(send)

    async def list_media(
        self, chat_id: int, *, before_message_id: int | None = None, limit: int = 60, kind: str = "all"
    ) -> tuple[TelegramMediaItem, ...]:
        """Newest first, older than `before_message_id`."""
        if kind not in MEDIA_FILTERS:
            raise ValidationFailedError("Unknown media kind", {"kind": kind})
        wanted = max(0, limit)
        server_filter = _SERVER_FILTERS.get(kind)
        scan_cap = None if server_filter is not None else max(wanted * 10, 600)

        async def scan(client: Any) -> tuple[TelegramMediaItem, ...]:
            peer = await self._session.input_peer(client, chat_id)
            items: list[TelegramMediaItem] = []
            if wanted == 0:
                return ()
            iterator = client.iter_messages(
                peer,
                offset_id=before_message_id or 0,
                filter=server_filter() if server_filter is not None else None,
                limit=scan_cap,
            )
            async for message in iterator:
                media = message_media(message)
                if media is None or (kind != "all" and media.kind.value != kind):
                    continue
                items.append(
                    TelegramMediaItem(
                        chat_id=chat_id,
                        message_id=int(message.id),
                        kind=media.kind,
                        filename=media.filename,
                        mime_type=media.mime_type,
                        size_bytes=media.size_bytes,
                        date=message.date,
                    )
                )
                if len(items) >= wanted:
                    break
            return tuple(items)

        return await self._session.call(scan)

    async def download_media(self, chat_id: int, message_id: int, destination: Path) -> Path:
        async def download(client: Any) -> Path:
            peer = await self._session.input_peer(client, chat_id)
            async with self._session.transfers.download_slot():
                await download_message(client, peer, message_id, Path(destination))
            return Path(destination)

        return await self._session.call(download)

    async def _chat(self, client: Any, dialog: Any) -> TelegramChat | None:
        entity = dialog.entity
        peer_id = int(dialog.id)
        self._session.remember_peer(peer_id, dialog.input_entity)
        if isinstance(entity, types.User):
            if entity.is_self:
                return TelegramChat(id=peer_id, title=SAVED_MESSAGES_TITLE, kind=TelegramChatKind.SAVED)
            return TelegramChat(id=peer_id, title=dialog.name or "", kind=TelegramChatKind.USER)
        if isinstance(entity, types.Channel) and entity.broadcast:
            if entity.creator and (entity.title or "").startswith(VAULT_TITLE_PREFIX):
                full = await client(functions.channels.GetFullChannelRequest(channel=entity))
                if parse_channel_marker(full.full_chat.about or "") is not None:
                    return None
            return TelegramChat(id=peer_id, title=dialog.name or "", kind=TelegramChatKind.CHANNEL)
        if isinstance(entity, (types.Chat, types.Channel)):
            return TelegramChat(id=peer_id, title=dialog.name or "", kind=TelegramChatKind.GROUP)
        return None
