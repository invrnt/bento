from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

ALBUM_MAX_DOCUMENTS = 10
"""Telegram sends at most 10 documents in one album (grouped media) request."""


class TelegramChatKind(StrEnum):
    SAVED = "saved"
    USER = "user"
    GROUP = "group"
    CHANNEL = "channel"


class TelegramMediaKind(StrEnum):
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"


@dataclass(frozen=True, slots=True)
class TelegramChat:
    id: int
    title: str
    kind: TelegramChatKind


@dataclass(frozen=True, slots=True)
class TelegramMediaItem:
    chat_id: int
    message_id: int
    kind: TelegramMediaKind
    filename: str
    mime_type: str
    size_bytes: int | None
    date: datetime


@dataclass(frozen=True, slots=True)
class InboxItem:
    message_id: int
    kind: TelegramMediaKind
    filename: str
    mime_type: str
    size_bytes: int | None
    date: datetime
    # The account's own reactions; every device of the account shares them, so they mark handled items.
    reactions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RemotePart:
    """One uploaded document holding a slice of a ciphertext stream."""

    channel_id: int
    message_id: int
    size_bytes: int
