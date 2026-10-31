"""A scripted stand-in for `telethon.TelegramClient`: records requests, keeps chats in memory, injects failures."""

from __future__ import annotations

import io
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from telethon import errors, functions, types, utils

from bento.adapters.telegram_mtproto.session import MtprotoSession
from bento.adapters.security import InMemoryKeyStore

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
ME = types.User(id=777000001, is_self=True, first_name="Ana", last_name="Demo", username="ana", phone="573001234512", access_hash=7)


@dataclass
class FakeFile:
    name: str | None
    size: int
    mime_type: str
    ext: str = ""


@dataclass
class FakeMessage:
    id: int
    date: datetime
    message: str = ""
    data: bytes | None = None
    filename: str | None = None
    mime_type: str = "application/octet-stream"
    photo: Any = None
    video: Any = None
    audio: Any = None
    voice: Any = None
    gif: Any = None
    sticker: Any = None
    action: Any = None
    reactions: Any = None

    @property
    def document(self) -> Any:
        if self.data is None or self.photo is not None:
            return None
        return FakeDocument(self)

    @property
    def media(self) -> Any:
        return None if self.data is None else (self.photo or self.document)

    @property
    def file(self) -> FakeFile | None:
        if self.data is None:
            return None
        ext = Path(self.filename or "").suffix or (".jpg" if self.photo is not None else "")
        return FakeFile(name=self.filename, size=len(self.data), mime_type=self.mime_type, ext=ext)


@dataclass
class FakeDocument:
    message: FakeMessage


@dataclass
class FakeDialog:
    id: int
    entity: Any
    input_entity: Any
    name: str


class FakeQRLogin:
    def __init__(self, client: FakeTelethonClient) -> None:
        self._client = client
        self.token = b"qr-token-1"
        self.expires = client.now() + timedelta(seconds=30)
        self.recreated = 0

    @property
    def url(self) -> str:
        return "tg://login?token=" + self.token.decode()

    async def recreate(self) -> None:
        self.recreated += 1
        self.token = f"qr-token-{self.recreated + 1}".encode()
        self.expires = self._client.now() + timedelta(seconds=30)

    async def wait(self, timeout: float | None = None) -> Any:
        outcome = await self._client.qr_outcome.get()
        if isinstance(outcome, BaseException):
            raise outcome
        self._client.authorize()
        return ME


class FakeDownload:
    def __init__(self, client: FakeTelethonClient, document: FakeDocument, offset: int, request_size: int) -> None:
        self._client = client
        self._data = document.message.data or b""
        self._position = offset
        self._size = request_size
        self.closed = False

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self

    async def __anext__(self) -> bytes:
        if self._client.expire_downloads_after is not None:
            if self._client.expire_downloads_after == 0:
                self._client.expire_downloads_after = None
                raise errors.FileReferenceExpiredError(request=None)
            self._client.expire_downloads_after -= 1
        if self._position >= len(self._data):
            raise StopAsyncIteration
        chunk = self._data[self._position : self._position + self._size]
        self._position += len(chunk)
        self._client.downloaded_bytes += len(chunk)
        return chunk

    async def close(self) -> None:
        self.closed = True


@dataclass
class FakeChannel:
    entity: types.Channel
    about: str
    messages: list[FakeMessage] = field(default_factory=list)
    pinned: int | None = None
    next_id: int = 1


class FakeTelethonClient:
    def __init__(self, session_string: str = "") -> None:
        self.session = FakeSession(self, session_string)
        self.requests: list[Any] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.channels: dict[int, FakeChannel] = {}
        self.dialogs: list[FakeDialog] = [FakeDialog(ME.id, ME, utils.get_input_peer(ME), "Ana Demo")]
        self.filters: list[Any] = []
        self.handlers: list[tuple[Any, Any]] = []
        self.authorized = bool(session_string)
        self.connected = False
        self.failures: list[BaseException] = []
        self.qr_outcome: Any = None
        self.expire_downloads_after: int | None = None
        self.downloaded_bytes = 0
        self.allowed_reactions: set[str] | None = None
        self.sign_in_results: list[Any] = []
        self.accept_result: Any = types.Authorization(
            hash=99, device_model="Bento (abc123)", platform="Linux", system_version="Linux 6", api_id=1, app_name="Bento",
            app_version="0.1.0", date_created=NOW, date_active=NOW, ip="", country="", region="",
        )
        self._channel_seq = 1_000_000_000

    # Connection and auth

    def now(self) -> datetime:
        return NOW

    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self._fail("connect")
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def is_user_authorized(self) -> bool:
        return self.authorized

    def authorize(self) -> None:
        self.authorized = True

    async def get_me(self) -> Any:
        self._fail("get_me")
        return ME if self.authorized else None

    async def qr_login(self) -> FakeQRLogin:
        import asyncio

        self.qr_outcome = self.qr_outcome or asyncio.Queue()
        self.calls.append(("qr_login", {}))
        return FakeQRLogin(self)

    async def send_code_request(self, phone: str) -> Any:
        self._fail("send_code_request")
        self.calls.append(("send_code_request", {"phone": phone}))
        return types.auth.SentCode(type=types.auth.SentCodeTypeApp(length=5), phone_code_hash="code-hash")

    async def sign_in(self, phone: str | None = None, code: str | None = None, *, password: str | None = None, phone_code_hash: str | None = None) -> Any:
        self.calls.append(("sign_in", {"phone": phone, "code": code, "phone_code_hash": phone_code_hash, "password": password is not None}))
        result = self.sign_in_results.pop(0) if self.sign_in_results else ME
        if isinstance(result, BaseException):
            raise result
        self.authorize()
        return result

    async def log_out(self) -> bool:
        self.calls.append(("log_out", {}))
        self.authorized = False
        return True

    async def download_profile_photo(self, entity: Any, file: Any = None) -> Any:
        return b"\xff\xd8avatar" if self.authorized else None

    # Raw requests

    async def __call__(self, request: Any) -> Any:
        self.requests.append(request)
        self._fail(type(request).__name__)
        if isinstance(request, functions.channels.CreateChannelRequest):
            self._channel_seq += 1
            entity = types.Channel(
                id=self._channel_seq, title=request.title, photo=types.ChatPhotoEmpty(), date=NOW,
                creator=True, broadcast=bool(request.broadcast), access_hash=self._channel_seq,
            )
            self.add_channel(entity, request.about)
            return types.Updates(updates=[], users=[], chats=[entity], date=NOW, seq=0)
        if isinstance(request, functions.channels.GetFullChannelRequest):
            channel = self.channel(utils.get_peer_id(request.channel))
            return _Full(_FullChat(about=channel.about, pinned_msg_id=channel.pinned))
        if isinstance(request, functions.messages.GetDialogFiltersRequest):
            return types.messages.DialogFilters(filters=list(self.filters))
        if isinstance(request, functions.messages.UpdateDialogFilterRequest):
            self.filters = [item for item in self.filters if getattr(item, "id", None) != request.id] + [request.filter]
            return True
        if isinstance(request, functions.messages.SendReactionRequest):
            emoji = request.reaction[0].emoticon
            if self.allowed_reactions is not None and emoji not in self.allowed_reactions:
                raise errors.ReactionInvalidError(request=request)
            message = self.message(utils.get_peer_id(request.peer), request.msg_id)
            message.reactions = types.MessageReactions(
                results=[types.ReactionCount(reaction=types.ReactionEmoji(emoticon=emoji), count=1, chosen_order=1)]
            )
            return True
        if isinstance(request, functions.auth.AcceptLoginTokenRequest):
            if isinstance(self.accept_result, BaseException):
                raise self.accept_result
            return self.accept_result
        if isinstance(request, functions.account.GetAuthorizationsRequest):
            current = types.Authorization(
                hash=0, device_model="Bento (def456)", platform="Linux", system_version="Linux 6", api_id=1, app_name="Bento",
                app_version="0.1.0", date_created=NOW, date_active=NOW, ip="", country="", region="", current=True,
            )
            return types.account.Authorizations(authorization_ttl_days=180, authorizations=[self.accept_result, current])
        if isinstance(request, functions.account.GetPasswordRequest):
            return _Password(hint="perro")
        return True

    # Messages

    async def send_message(self, entity: Any, text: str, **kwargs: Any) -> FakeMessage:
        self._fail("send_message")
        self.calls.append(("send_message", {"text": text, **kwargs}))
        return self.post(utils.get_peer_id(entity), message=text)

    async def send_file(self, entity: Any, file: Any, **kwargs: Any) -> Any:
        self._fail("send_file")
        peer_id = utils.get_peer_id(entity)
        self.calls.append(("send_file", {"file": file, **kwargs}))
        callback = kwargs.get("progress_callback")
        if isinstance(file, list):
            sent = []
            for path in file:
                data = Path(path).read_bytes()
                sent.append(self.post(peer_id, data=data, filename=Path(path).name))
                if callback is not None:
                    await callback(len(sent), len(file))
            return sent
        if isinstance(file, io.BytesIO):
            data, name = file.getvalue(), getattr(file, "name", None)
        else:
            data, name = Path(file).read_bytes(), Path(file).name
        for attribute in kwargs.get("attributes") or ():
            if isinstance(attribute, types.DocumentAttributeFilename):
                name = attribute.file_name
        if callback is not None:
            await callback(len(data) // 2, len(data))
            await callback(len(data), len(data))
        return self.post(peer_id, data=data, filename=name, mime_type=kwargs.get("mime_type") or "application/octet-stream", message=kwargs.get("caption") or "")

    async def pin_message(self, entity: Any, message: int, notify: bool = False) -> Any:
        channel = self.channel(utils.get_peer_id(entity))
        channel.pinned = message
        self.calls.append(("pin_message", {"id": message, "notify": notify}))
        return self.post(utils.get_peer_id(entity), action=types.MessageActionPinMessage())

    async def unpin_message(self, entity: Any, message: int) -> None:
        self.calls.append(("unpin_message", {"id": message}))

    async def get_messages(self, entity: Any, ids: int) -> FakeMessage | None:
        self._fail("get_messages")
        self.calls.append(("get_messages", {"ids": ids}))
        try:
            return self.message(utils.get_peer_id(entity), ids)
        except KeyError:
            return None

    async def delete_messages(self, entity: Any, ids: list[int]) -> None:
        self.calls.append(("delete_messages", {"ids": list(ids)}))
        channel = self.channel(utils.get_peer_id(entity))
        channel.messages = [item for item in channel.messages if item.id not in set(ids)]

    async def iter_messages(self, entity: Any, *, min_id: int = 0, reverse: bool = False, offset_id: int = 0, filter: Any = None, limit: Any = None) -> AsyncIterator[FakeMessage]:
        self.calls.append(("iter_messages", {"min_id": min_id, "reverse": reverse, "offset_id": offset_id, "filter": filter, "limit": limit}))
        messages = sorted(self.channel(utils.get_peer_id(entity)).messages, key=lambda item: item.id, reverse=not reverse)
        yielded = 0
        for message in messages:
            if message.id <= min_id or (offset_id and not reverse and message.id >= offset_id):
                continue
            if filter is not None and not _matches(message, filter):
                continue
            if limit is not None and yielded >= limit:
                return
            yielded += 1
            yield message

    async def iter_dialogs(self, limit: Any = None) -> AsyncIterator[FakeDialog]:
        self.calls.append(("iter_dialogs", {}))
        for dialog in self.dialogs:
            yield dialog

    def iter_download(self, file: Any, *, offset: int = 0, request_size: int = 512 * 1024, file_size: Any = None) -> FakeDownload:
        self.calls.append(("iter_download", {"offset": offset, "request_size": request_size}))
        return FakeDownload(self, file, offset, request_size)

    async def download_media(self, message: FakeMessage, file: Any = None) -> Any:
        self.calls.append(("download_media", {"id": message.id}))
        if self.expire_downloads_after == 0:
            self.expire_downloads_after = None
            raise errors.FileReferenceExpiredError(request=None)
        if file is bytes:
            return message.data
        Path(file).write_bytes(message.data or b"")
        return str(file)

    async def get_input_entity(self, peer: Any) -> Any:
        for dialog in self.dialogs:
            if dialog.id == peer:
                return dialog.input_entity
        raise ValueError("unknown entity")

    def add_event_handler(self, callback: Any, event: Any) -> None:
        self.handlers.append((callback, event))

    def remove_event_handler(self, callback: Any) -> None:
        self.handlers = [item for item in self.handlers if item[0] is not callback]

    # Test helpers

    def add_channel(self, entity: types.Channel, about: str) -> FakeChannel:
        peer_id = utils.get_peer_id(entity)
        channel = FakeChannel(entity=entity, about=about)
        self.channels[peer_id] = channel
        self.dialogs.append(FakeDialog(peer_id, entity, utils.get_input_peer(entity), entity.title))
        return channel

    def channel(self, peer_id: int) -> FakeChannel:
        return self.channels[peer_id]

    def message(self, peer_id: int, message_id: int) -> FakeMessage:
        for message in self.channel(peer_id).messages:
            if message.id == message_id:
                return message
        raise KeyError(message_id)

    def post(self, peer_id: int, **fields: Any) -> FakeMessage:
        channel = self.channels.get(peer_id)
        if channel is None:
            entity = types.Channel(id=abs(peer_id) % 10**12, title="chat", photo=types.ChatPhotoEmpty(), date=NOW, access_hash=1)
            channel = self.channels[peer_id] = FakeChannel(entity=entity, about="")
        message = FakeMessage(id=channel.next_id, date=NOW + timedelta(seconds=channel.next_id), **fields)
        channel.next_id += 1
        channel.messages.append(message)
        return message

    def requests_of(self, kind: type) -> list[Any]:
        return [request for request in self.requests if isinstance(request, kind)]

    def calls_of(self, name: str) -> list[dict[str, Any]]:
        return [kwargs for call, kwargs in self.calls if call == name]

    def _fail(self, operation: str) -> None:
        if self.failures:
            failure = self.failures[0]
            target = getattr(failure, "_bento_operation", None)
            if target is None or target == operation:
                self.failures.pop(0)
                raise failure


class FakeSession:
    def __init__(self, client: FakeTelethonClient, value: str) -> None:
        self._client = client
        self._value = value

    def save(self) -> str:
        return self._value or ("1fake-session-after-login" if self._client.authorized else "")


@dataclass
class _FullChat:
    about: str
    pinned_msg_id: int | None


@dataclass
class _Full:
    full_chat: _FullChat


@dataclass
class _Password:
    hint: str


def fail_on(operation: str, error: BaseException) -> BaseException:
    error._bento_operation = operation  # type: ignore[attr-defined]
    return error


def _matches(message: FakeMessage, server_filter: Any) -> bool:
    if isinstance(server_filter, types.InputMessagesFilterPhotos):
        return message.photo is not None
    if isinstance(server_filter, types.InputMessagesFilterVideo):
        return message.video is not None
    if isinstance(server_filter, types.InputMessagesFilterMusic):
        return message.audio is not None
    if isinstance(server_filter, types.InputMessagesFilterDocument):
        return message.document is not None
    return True


def make_session(client: FakeTelethonClient, *, key_store: InMemoryKeyStore | None = None, **kwargs: Any) -> tuple[MtprotoSession, InMemoryKeyStore]:
    """A session whose factory always hands out `client` (with the stored session string)."""
    store = key_store or InMemoryKeyStore()
    built: list[str] = []

    async def factory(session_string: str) -> FakeTelethonClient:
        built.append(session_string)
        client.session = FakeSession(client, session_string)
        client.authorized = client.authorized or bool(session_string)
        return client

    session = MtprotoSession(factory=factory, key_store=store, **kwargs)
    session.built = built  # type: ignore[attr-defined]
    return session, store


def bento_channel(client: FakeTelethonClient, title: str, about: str, *, creator: bool = True) -> FakeChannel:
    client._channel_seq += 1
    entity = types.Channel(
        id=client._channel_seq, title=title, photo=types.ChatPhotoEmpty(), date=NOW, creator=creator, broadcast=True,
        access_hash=client._channel_seq,
    )
    return client.add_channel(entity, about)
