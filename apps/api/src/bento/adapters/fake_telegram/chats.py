from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from bento.adapters.fake_telegram import store
from bento.adapters.fake_telegram.cloud import DocumentUpload, FakeChat
from bento.adapters.fake_telegram.session import FakeTelegramSession
from bento.domain.errors import ValidationFailedError
from bento.domain.telegram import TelegramChat, TelegramChatKind, TelegramMediaItem, TelegramMediaKind
from bento.domain.vault import parse_channel_marker

_MEDIA_FILTERS = {"all", *(kind.value for kind in TelegramMediaKind)}
_EPOCH = datetime.min.replace(tzinfo=UTC)


class FakeTelegramChats:
    """Dialogs the user may pick for sharing/import. Bento's own vault channels are never offered."""

    def __init__(self, session: FakeTelegramSession) -> None:
        self._session = session
        self._cloud = session.cloud

    async def list_chats(self, *, query: str | None = None, limit: int = 30) -> tuple[TelegramChat, ...]:
        dialogs = await self._session.call(self._cloud.dialogs)
        needle = (query or "").strip().casefold()
        visible = [
            chat
            for chat in dialogs
            if not (chat.kind == TelegramChatKind.CHANNEL and parse_channel_marker(chat.about) is not None)
            and needle in chat.title.casefold()
        ]
        visible.sort(key=_dialog_order)
        return tuple(TelegramChat(id=chat.id, title=chat.title, kind=chat.kind) for chat in visible[: max(0, limit)])

    async def send_file(self, chat_id: int, source: Path, *, filename: str, caption: str | None = None) -> None:
        upload = DocumentUpload(Path(source), filename, kind=TelegramMediaKind.DOCUMENT)
        await self._session.call(self._cloud.post_message, chat_id, text=caption, document=upload)

    async def list_media(
        self, chat_id: int, *, before_message_id: int | None = None, limit: int = 60, kind: str = "all"
    ) -> tuple[TelegramMediaItem, ...]:
        if kind not in _MEDIA_FILTERS:
            raise ValidationFailedError("Unknown media kind", {"kind": kind})
        _, messages = await self._session.call(self._cloud.read_chat, chat_id)
        items = [
            TelegramMediaItem(
                chat_id=chat_id,
                message_id=message.id,
                kind=message.media.kind,
                filename=message.media.filename,
                mime_type=message.media.mime_type,
                size_bytes=message.media.size_bytes,
                date=message.date,
            )
            for message in reversed(messages)
            if message.media is not None
            and (before_message_id is None or message.id < before_message_id)
            and (kind == "all" or message.media.kind.value == kind)
        ]
        return tuple(items[: max(0, limit)])

    async def download_media(self, chat_id: int, message_id: int, destination: Path) -> Path:
        path = await self._session.call(self._cloud.document_path, chat_id, message_id)
        await self._session.run(store.copy_file, path, Path(destination))
        return Path(destination)


def _dialog_order(chat: FakeChat) -> tuple[bool, float]:
    """Saved Messages first, then most recent activity."""
    return chat.kind != TelegramChatKind.SAVED, -(chat.last_message_at or _EPOCH).timestamp()
