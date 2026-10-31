"""What a Telethon message carries, in Bento terms."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from typing import Any

from bento.domain.telegram import TelegramMediaKind


@dataclass(frozen=True, slots=True)
class MessageMedia:
    kind: TelegramMediaKind
    filename: str
    mime_type: str
    size_bytes: int | None


def message_media(message: Any) -> MessageMedia | None:
    """Photos and documents (videos, audio, files). Stickers, polls, links, contacts, and services are ignored."""
    if message is None or getattr(message, "action", None) is not None:
        return None
    photo = getattr(message, "photo", None)
    document = getattr(message, "document", None)
    if photo is None and document is None:
        return None
    if document is not None and getattr(message, "sticker", None) is not None:
        return None
    file = getattr(message, "file", None)
    mime_type = (getattr(file, "mime_type", None) or ("image/jpeg" if photo is not None else "")) or "application/octet-stream"
    name = getattr(file, "name", None)
    if not name:
        extension = getattr(file, "ext", None) or mimetypes.guess_extension(mime_type) or ""
        name = f"telegram-{message.id}{extension}"
    if photo is not None:
        kind = TelegramMediaKind.PHOTO
    elif getattr(message, "video", None) is not None or getattr(message, "gif", None) is not None:
        kind = TelegramMediaKind.VIDEO
    elif getattr(message, "audio", None) is not None or getattr(message, "voice", None) is not None:
        kind = TelegramMediaKind.AUDIO
    else:
        kind = kind_for_mime(mime_type)
    size = getattr(file, "size", None)
    return MessageMedia(kind=kind, filename=name, mime_type=mime_type, size_bytes=int(size) if size is not None else None)


def kind_for_mime(mime_type: str) -> TelegramMediaKind:
    family = mime_type.split("/", 1)[0]
    return {
        "image": TelegramMediaKind.PHOTO,
        "video": TelegramMediaKind.VIDEO,
        "audio": TelegramMediaKind.AUDIO,
    }.get(family, TelegramMediaKind.DOCUMENT)


def own_reactions(message: Any) -> tuple[str, ...]:
    """Emoji reactions set by this account (shared by all its sessions)."""
    reactions = getattr(message, "reactions", None)
    results = getattr(reactions, "results", None) or ()
    chosen: list[str] = []
    for result in results:
        emoticon = getattr(getattr(result, "reaction", None), "emoticon", None)
        if emoticon and getattr(result, "chosen_order", None) is not None:
            chosen.append(str(emoticon))
    return tuple(chosen)
