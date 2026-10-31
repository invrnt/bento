"""Filesystem-backed simulation of one Telegram account shared by every Bento instance pointing at the directory.

Layout: `cloud.json` (account, authorizations, login tokens, chat folders, id counters) and
`chats/<chat_id>/chat.json` (metadata plus the message log) with documents in `chats/<chat_id>/docs/<message_id>.bin`.
Every mutation holds the exclusive `.lock`; every file is replaced atomically, so readers never lock.
"""

from __future__ import annotations

import base64
import mimetypes
import secrets
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bento.adapters.fake_telegram import media, store
from bento.adapters.fake_telegram.options import FakeTelegramOptions
from bento.domain.account import TelegramAccount
from bento.domain.errors import StorageUnavailableError, TelegramAccountError, ValidationFailedError
from bento.domain.storage import StorageBackend
from bento.domain.telegram import TelegramChatKind, TelegramMediaKind

FAKE_USER = TelegramAccount(
    user_id=777000001,
    display_name="Ana Demo",
    username="anademo",
    phone_masked="+57 ••• ••• 01",
    premium=False,
)
PHONE_AUTHORIZATION_ID = "auth_phone"
MAX_TEXT_CHARS = 4096
MAX_CAPTION_CHARS = 1024
MAX_DOCUMENT_BYTES = 2000 * 1024 * 1024
_CHANNEL_ID_BASE = 1_001_000_000_000
_LOGIN_TOKEN_GRACE = timedelta(minutes=5)
_SEED_DATE = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class FakeMedia:
    kind: TelegramMediaKind
    filename: str
    mime_type: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class FakeMessage:
    id: int
    date: datetime
    text: str | None = None
    media: FakeMedia | None = None
    reactions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FakeChat:
    id: int
    kind: TelegramChatKind
    title: str
    about: str = ""
    creator: bool = False
    pinned_message_id: int | None = None
    muted: bool = False
    archived: bool = False
    last_message_id: int = 0
    last_message_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FakeAuthorization:
    id: str
    hash: int
    device_model: str
    platform: str
    app_name: str
    created_at: datetime
    last_active_at: datetime


@dataclass(frozen=True, slots=True)
class FakeLoginToken:
    token: bytes
    created_at: datetime
    expires_at: datetime
    approved_authorization_id: str | None = None

    @property
    def url(self) -> str:
        return f"tg://login?token={encode_token(self.token)}"


@dataclass(frozen=True, slots=True)
class DocumentUpload:
    """Bytes or a file to attach; staged outside the lock before the message is created."""

    source: bytes | Path
    filename: str
    mime_type: str | None = None
    kind: TelegramMediaKind | None = None


def encode_token(token: bytes) -> str:
    return base64.urlsafe_b64encode(token).rstrip(b"=").decode("ascii")


def media_kind_for(mime_type: str) -> TelegramMediaKind:
    family = mime_type.split("/", 1)[0]
    return {
        "image": TelegramMediaKind.PHOTO,
        "video": TelegramMediaKind.VIDEO,
        "audio": TelegramMediaKind.AUDIO,
    }.get(family, TelegramMediaKind.DOCUMENT)


def missing_remote() -> StorageUnavailableError:
    return StorageUnavailableError(StorageBackend.TELEGRAM.value)


class FakeTelegramCloud:
    def __init__(self, root: Path | str, *, clock: Callable[[], float] = time.time) -> None:
        self.root = Path(root)
        self._clock = clock
        self._lock = store.FileLock(self.root / ".lock")
        self._local = threading.local()
        self._ready = False

    # Infrastructure

    def now(self) -> datetime:
        return datetime.fromtimestamp(self._clock(), UTC)

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Exclusive across processes and threads; re-entrant within a thread."""
        self.ensure_ready()
        with self._lock.hold():
            yield

    def ensure_ready(self) -> None:
        if self._ready or getattr(self._local, "seeding", False):
            return
        with self._lock.hold():
            if store.read_json(self._cloud_path) is None:
                self._local.seeding = True
                try:
                    self._seed()
                finally:
                    self._local.seeding = False
        self._ready = True

    def chat_log_path(self, chat_id: int) -> Path:
        return self._chat_dir(chat_id) / "chat.json"

    def document_path(self, chat_id: int, message_id: int) -> Path:
        message = self.message(chat_id, message_id)
        if message is None or message.media is None:
            raise missing_remote()
        path = self._document_file(chat_id, message_id)
        if not path.is_file():
            raise missing_remote()
        return path

    # Account

    @property
    def user(self) -> TelegramAccount:
        return FAKE_USER

    def authorizations(self) -> tuple[FakeAuthorization, ...]:
        state = self._read_cloud()
        return tuple(_authorization_from_json(item) for item in state["authorizations"])

    def authorization(self, authorization_id: str) -> FakeAuthorization | None:
        return next((item for item in self.authorizations() if item.id == authorization_id), None)

    def create_authorization(self, options: FakeTelegramOptions) -> FakeAuthorization:
        with self.locked():
            state = self._read_cloud()
            record = self._new_authorization(state, options)
            self._write_cloud(state)
            return _authorization_from_json(record)

    def remove_authorization(
        self, *, authorization_id: str | None = None, authorization_hash: int | None = None
    ) -> FakeAuthorization | None:
        with self.locked():
            state = self._read_cloud()
            for index, item in enumerate(state["authorizations"]):
                if item["id"] == authorization_id or (authorization_hash and item["hash"] == authorization_hash):
                    removed = state["authorizations"].pop(index)
                    self._write_cloud(state)
                    return _authorization_from_json(removed)
            return None

    def touch_authorization(self, authorization_id: str) -> None:
        with self.locked():
            state = self._read_cloud()
            for item in state["authorizations"]:
                if item["id"] == authorization_id:
                    item["last_active_at"] = self.now().isoformat()
                    self._write_cloud(state)
                    return

    def issue_login_token(self, options: FakeTelegramOptions) -> FakeLoginToken:
        with self.locked():
            state = self._read_cloud()
            now = self.now()
            tokens = state["login_tokens"]
            for key in [key for key, item in tokens.items() if _parse(item["expires_at"]) + _LOGIN_TOKEN_GRACE < now]:
                del tokens[key]
            token = secrets.token_bytes(32)
            tokens[encode_token(token)] = {
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=options.qr_ttl_seconds)).isoformat(),
                "approved_authorization_id": None,
                "device_model": options.device_model,
                "platform": options.platform,
                "app_name": options.app_name,
            }
            self._write_cloud(state)
            return _login_token_from_json(token, tokens[encode_token(token)])

    def login_token(self, token: bytes) -> FakeLoginToken | None:
        record = self._read_cloud()["login_tokens"].get(encode_token(token))
        return _login_token_from_json(token, record) if record is not None else None

    def approve_login_token(self, token: bytes, approver_id: str) -> FakeAuthorization:
        """`auth.acceptLoginToken`: creates the new authorization for the waiting instance."""
        with self.locked():
            state = self._read_cloud()
            record = state["login_tokens"].get(encode_token(token))
            if not any(item["id"] == approver_id for item in state["authorizations"]):
                raise TelegramAccountError("telegram_not_authorized", "This device is not signed in to Telegram")
            if record is None:
                raise _login_token_error("invalid")
            if record["approved_authorization_id"] is not None:
                raise _login_token_error("already_accepted")
            if _parse(record["expires_at"]) <= self.now():
                raise _login_token_error("expired")
            authorization = self._new_authorization(
                state,
                FakeTelegramOptions(
                    device_model=record["device_model"], platform=record["platform"], app_name=record["app_name"]
                ),
            )
            record["approved_authorization_id"] = authorization["id"]
            self._write_cloud(state)
            return _authorization_from_json(authorization)

    def approve_pending_logins(self) -> int:
        """What the user's phone does when scanning every QR currently shown (dev route)."""
        with self.locked():
            now = self.now()
            pending = [
                token
                for token, record in self._read_cloud()["login_tokens"].items()
                if record["approved_authorization_id"] is None and _parse(record["expires_at"]) > now
            ]
            for token in pending:
                self.approve_login_token(_decode_token(token), PHONE_AUTHORIZATION_ID)
            return len(pending)

    def claim_login_token(self, token: bytes) -> str | None:
        """Consume an approved token and return the authorization it created."""
        with self.locked():
            state = self._read_cloud()
            key = encode_token(token)
            record = state["login_tokens"].get(key)
            if record is None or record["approved_authorization_id"] is None:
                return None
            del state["login_tokens"][key]
            self._write_cloud(state)
            return str(record["approved_authorization_id"])

    def discard_login_token(self, token: bytes) -> None:
        with self.locked():
            state = self._read_cloud()
            if state["login_tokens"].pop(encode_token(token), None) is not None:
                self._write_cloud(state)

    # Chats and channels

    def dialogs(self) -> tuple[FakeChat, ...]:
        self.ensure_ready()
        chats_dir = self.root / "chats"
        result: list[FakeChat] = []
        for directory in sorted(chats_dir.iterdir()) if chats_dir.is_dir() else ():
            payload = store.read_json(directory / "chat.json")
            if payload is not None:
                result.append(_chat_from_json(payload))
        return tuple(result)

    def chat(self, chat_id: int) -> FakeChat:
        return self.read_chat(chat_id)[0]

    def read_chat(self, chat_id: int) -> tuple[FakeChat, tuple[FakeMessage, ...]]:
        """One consistent snapshot of a chat and its messages in ascending id order."""
        self.ensure_ready()
        payload = store.read_json(self.chat_log_path(chat_id))
        if payload is None:
            raise missing_remote()
        return _chat_from_json(payload), tuple(_message_from_json(item) for item in payload["messages"])

    def message(self, chat_id: int, message_id: int) -> FakeMessage | None:
        return next((item for item in self.read_chat(chat_id)[1] if item.id == message_id), None)

    def last_message_id(self, chat_id: int) -> int:
        return self.chat(chat_id).last_message_id

    def create_channel(self, title: str, about: str = "", *, creator: bool = True) -> FakeChat:
        with self.locked():
            state = self._read_cloud()
            sequence = int(state["next_channel_seq"])
            state["next_channel_seq"] = sequence + 1
            chat_id = -(_CHANNEL_ID_BASE + sequence)
            self._write_chat(_new_chat(chat_id, TelegramChatKind.CHANNEL, title, about=about, creator=creator))
            self._write_cloud(state)
            return self.chat(chat_id)

    def update_chat(self, chat_id: int, *, muted: bool | None = None, archived: bool | None = None) -> FakeChat:
        with self.locked():
            payload = self._read_chat_payload(chat_id)
            if muted is not None:
                payload["muted"] = muted
            if archived is not None:
                payload["archived"] = archived
            self._write_chat(payload)
            return _chat_from_json(payload)

    def add_to_folder(self, title: str, chat_ids: Iterable[int]) -> None:
        with self.locked():
            state = self._read_cloud()
            members = state["folders"].setdefault(title, [])
            members.extend(chat_id for chat_id in chat_ids if chat_id not in members)
            self._write_cloud(state)

    def folders(self) -> dict[str, tuple[int, ...]]:
        return {title: tuple(ids) for title, ids in self._read_cloud()["folders"].items()}

    def post_message(
        self,
        chat_id: int,
        *,
        text: str | None = None,
        document: DocumentUpload | None = None,
        pin: bool = False,
        date: datetime | None = None,
    ) -> FakeMessage:
        if text is not None and len(text) > (MAX_CAPTION_CHARS if document else MAX_TEXT_CHARS):
            raise ValidationFailedError("Telegram message is too long", {"length": len(text)})
        if text is None and document is None:
            raise ValidationFailedError("Telegram messages need text or a document")
        staged = self._stage(document) if document is not None else None
        try:
            with self.locked():
                payload = self._read_chat_payload(chat_id)
                message_id = int(payload["next_message_id"])
                payload["next_message_id"] = message_id + 1
                record: dict[str, Any] = {
                    "id": message_id,
                    "date": (date or self.now()).isoformat(),
                    "text": text,
                    "media": None,
                    "reactions": [],
                }
                if document is not None and staged is not None:
                    mime_type = document.mime_type or _guess_mime(document.filename)
                    record["media"] = {
                        "kind": (document.kind or media_kind_for(mime_type)).value,
                        "filename": document.filename,
                        "mime_type": mime_type,
                        "size_bytes": staged.stat().st_size,
                    }
                    store.replace(staged, self._document_file(chat_id, message_id))
                payload["messages"].append(record)
                if pin:
                    payload["pinned_message_id"] = message_id
                self._write_chat(payload)
                return _message_from_json(record)
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)

    def delete_messages(self, chat_id: int, message_ids: Iterable[int]) -> int:
        targets = set(message_ids)
        with self.locked():
            payload = self._read_chat_payload(chat_id)
            kept = [item for item in payload["messages"] if item["id"] not in targets]
            removed = [item["id"] for item in payload["messages"] if item["id"] in targets]
            if not removed:
                return 0
            payload["messages"] = kept
            if payload.get("pinned_message_id") in targets:
                payload["pinned_message_id"] = None
            self._write_chat(payload)
        for message_id in removed:
            self._document_file(chat_id, message_id).unlink(missing_ok=True)
        return len(removed)

    def set_reaction(self, chat_id: int, message_id: int, emoji: str) -> None:
        with self.locked():
            payload = self._read_chat_payload(chat_id)
            for item in payload["messages"]:
                if item["id"] == message_id:
                    item["reactions"] = [emoji]
                    self._write_chat(payload)
                    return
        raise missing_remote()

    # Internals

    @property
    def _cloud_path(self) -> Path:
        return self.root / "cloud.json"

    def _chat_dir(self, chat_id: int) -> Path:
        return self.root / "chats" / str(chat_id)

    def _document_file(self, chat_id: int, message_id: int) -> Path:
        return self._chat_dir(chat_id) / "docs" / f"{message_id}.bin"

    def _read_cloud(self) -> dict[str, Any]:
        self.ensure_ready()
        state = store.read_json(self._cloud_path)
        if state is None:
            raise missing_remote()
        return state

    def _write_cloud(self, state: dict[str, Any]) -> None:
        store.write_json(self._cloud_path, state)

    def _read_chat_payload(self, chat_id: int) -> dict[str, Any]:
        payload = store.read_json(self.chat_log_path(chat_id))
        if payload is None:
            raise missing_remote()
        return payload

    def _write_chat(self, payload: dict[str, Any]) -> None:
        store.write_json(self.chat_log_path(int(payload["id"])), payload)

    def _stage(self, document: DocumentUpload) -> Path:
        staged = store.temp_path(self.root / "staging", ".upload")
        if isinstance(document.source, bytes):
            staged.write_bytes(document.source)
        else:
            store.copy_file(document.source, staged)
        if staged.stat().st_size > MAX_DOCUMENT_BYTES:
            staged.unlink(missing_ok=True)
            raise ValidationFailedError("Telegram documents are limited to 2000 MiB")
        return staged

    def _new_authorization(self, state: dict[str, Any], options: FakeTelegramOptions) -> dict[str, Any]:
        now = self.now().isoformat()
        record = {
            "id": f"auth_{secrets.token_hex(12)}",
            "hash": secrets.randbits(62) + 1,
            "device_model": options.device_model,
            "platform": options.platform,
            "app_name": options.app_name,
            "created_at": now,
            "last_active_at": now,
        }
        state["authorizations"].append(record)
        return record

    def _seed(self) -> None:
        """Seeded chats first, `cloud.json` last: its presence marks a complete directory."""
        palette = [(244, 162, 97), (231, 111, 81), (42, 157, 143), (38, 70, 83), (233, 196, 106)]
        seeds: list[tuple[int, TelegramChatKind, str, list[tuple[str | None, DocumentUpload | None]]]] = [
            (
                FAKE_USER.user_id,
                TelegramChatKind.SAVED,
                "Saved Messages",
                [
                    ("Lista de compras: pan, café, fruta", None),
                    (None, DocumentUpload(media.pdf_bytes("Recibo de cafe - 12.500 COP"), "recibo-cafe.pdf")),
                    (None, DocumentUpload(media.jpeg_bytes(96, 64, palette), "atardecer.jpg")),
                ],
            ),
            (
                777000002,
                TelegramChatKind.USER,
                "Carlos Ruiz",
                [
                    ("¡Mira las fotos del viaje!", None),
                    (None, DocumentUpload(media.png_bytes(80, 48, palette[::-1]), "playa.png")),
                    ("El video del paseo", DocumentUpload(media.mp4_bytes(), "paseo.mp4")),
                ],
            ),
            (
                -400000001,
                TelegramChatKind.GROUP,
                "Familia",
                [
                    (None, DocumentUpload(media.jpeg_bytes(64, 64, palette[1:]), "cumpleanos.jpg")),
                    (None, DocumentUpload("Turnos de la semana\n".encode(), "notas.txt")),
                ],
            ),
        ]
        for day, (chat_id, kind, title, messages) in enumerate(seeds):
            self._write_chat(_new_chat(chat_id, kind, title))
            for hour, (text, document) in enumerate(messages):
                when = _SEED_DATE + timedelta(days=day, hours=hour)
                self.post_message(chat_id, text=text, document=document, date=when)
        store.write_json(
            self._cloud_path,
            {
                "version": 1,
                "user_id": FAKE_USER.user_id,
                "authorizations": [
                    {
                        "id": PHONE_AUTHORIZATION_ID,
                        "hash": 5_550_000_000_000_001,
                        "device_model": "Pixel 8",
                        "platform": "Android 15",
                        "app_name": "Telegram Android 11.4",
                        "created_at": (_SEED_DATE - timedelta(days=400)).isoformat(),
                        "last_active_at": _SEED_DATE.isoformat(),
                    }
                ],
                "login_tokens": {},
                "folders": {},
                "next_channel_seq": 1,
            },
        )

def _new_chat(chat_id: int, kind: TelegramChatKind, title: str, *, about: str = "", creator: bool = False) -> dict[str, Any]:
    return {
        "id": chat_id,
        "kind": kind.value,
        "title": title,
        "about": about,
        "creator": creator,
        "pinned_message_id": None,
        "muted": False,
        "archived": False,
        "next_message_id": 1,
        "messages": [],
    }


def _chat_from_json(payload: dict[str, Any]) -> FakeChat:
    messages = payload["messages"]
    return FakeChat(
        id=int(payload["id"]),
        kind=TelegramChatKind(payload["kind"]),
        title=str(payload["title"]),
        about=str(payload.get("about") or ""),
        creator=bool(payload.get("creator")),
        pinned_message_id=payload.get("pinned_message_id"),
        muted=bool(payload.get("muted")),
        archived=bool(payload.get("archived")),
        last_message_id=int(payload["next_message_id"]) - 1,
        last_message_at=_parse(messages[-1]["date"]) if messages else None,
    )


def _message_from_json(payload: dict[str, Any]) -> FakeMessage:
    attached = payload.get("media")
    return FakeMessage(
        id=int(payload["id"]),
        date=_parse(payload["date"]),
        text=payload.get("text"),
        media=None
        if attached is None
        else FakeMedia(
            kind=TelegramMediaKind(attached["kind"]),
            filename=str(attached["filename"]),
            mime_type=str(attached["mime_type"]),
            size_bytes=int(attached["size_bytes"]),
        ),
        reactions=tuple(payload.get("reactions") or ()),
    )


def _authorization_from_json(payload: dict[str, Any]) -> FakeAuthorization:
    return FakeAuthorization(
        id=str(payload["id"]),
        hash=int(payload["hash"]),
        device_model=str(payload["device_model"]),
        platform=str(payload["platform"]),
        app_name=str(payload["app_name"]),
        created_at=_parse(payload["created_at"]),
        last_active_at=_parse(payload["last_active_at"]),
    )


def _login_token_from_json(token: bytes, payload: dict[str, Any]) -> FakeLoginToken:
    return FakeLoginToken(
        token=token,
        created_at=_parse(payload["created_at"]),
        expires_at=_parse(payload["expires_at"]),
        approved_authorization_id=payload.get("approved_authorization_id"),
    )


def _login_token_error(reason: str) -> TelegramAccountError:
    return TelegramAccountError("telegram_login_expired", "The Telegram login token is no longer valid", {"reason": reason})


def _decode_token(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _guess_mime(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
