"""Send a decrypted copy of a file to a Telegram chat the person picks (an explicit plaintext disclosure)."""

from __future__ import annotations

from collections.abc import Callable

from bento.domain.errors import AssetNotFoundError, StorageUnavailableError, ValidationFailedError
from bento.ports.content import AssetContentPort
from bento.ports.repositories import AssetRepositoryPort
from bento.ports.telegram import TelegramChatsPort

MAX_CAPTION_CHARS = 1024


class SharingService:
    def __init__(
        self,
        *,
        assets: AssetRepositoryPort,
        content: Callable[[], AssetContentPort],
        chats: Callable[[], TelegramChatsPort | None],
    ) -> None:
        self._assets = assets
        self._content = content
        self._chats = chats

    async def share(self, asset_id: str, chat_id: int, *, caption: str | None = None) -> None:
        asset = await self._assets.get(asset_id)
        if asset is None or asset.is_deleted:
            raise AssetNotFoundError(asset_id)
        caption = caption.strip() if caption else None
        if caption and len(caption) > MAX_CAPTION_CHARS:
            raise ValidationFailedError("Caption is too long", {"max_length": MAX_CAPTION_CHARS})
        chats = self._chats()
        if chats is None:
            raise StorageUnavailableError("telegram")
        source = await self._content().materialize_original(asset_id)
        # The person sees the file under its current name in Bento, so that is the name the recipient gets.
        await chats.send_file(chat_id, source, filename=asset.filename, caption=caption or None)
