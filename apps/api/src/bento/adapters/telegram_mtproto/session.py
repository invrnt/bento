"""One Telethon client per process on this device's Telegram session.

The session lives in the key store as a `StringSession` string (`telegram.session`); each process builds its own
in-memory client from it and rebuilds the client whenever the stored string changes (another process signed in
or out), so API and worker never share Telethon state.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol, TypeVar

from bento.adapters.telegram_mtproto.errors import map_telethon_error, not_authorized
from bento.domain.account import TelegramAccount
from bento.domain.errors import DomainError, StorageUnavailableError
from bento.domain.storage import StorageBackend
from bento.ports.key_store import TELEGRAM_SESSION, KeyStorePort

T = TypeVar("T")


class CallPolicy(Protocol):
    """Retries/flood-wait handling around one Telegram request (see `infrastructure/mtproto/flood.py`)."""

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T: ...


class TransferLimiter(Protocol):
    """Parallel transfer slots plus the upload bandwidth budget (see `infrastructure/mtproto/transfer.py`)."""

    def upload_slot(self) -> Any: ...

    def download_slot(self) -> Any: ...

    async def consume_upload(self, size_bytes: int) -> None: ...


class ClientFactory(Protocol):
    async def __call__(self, session_string: str) -> Any:
        """A new, not yet connected `TelegramClient` on an in-memory copy of `session_string`."""
        ...


class DirectPolicy:
    """No retries: for tests and one-shot tools."""

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        return await operation()


class UnlimitedTransfers:
    @asynccontextmanager
    async def upload_slot(self) -> AsyncIterator[None]:
        yield

    @asynccontextmanager
    async def download_slot(self) -> AsyncIterator[None]:
        yield

    async def consume_upload(self, size_bytes: int) -> None:
        del size_bytes


class MtprotoSession:
    def __init__(
        self,
        *,
        factory: ClientFactory,
        key_store: KeyStorePort,
        policy: CallPolicy | None = None,
        transfers: TransferLimiter | None = None,
    ) -> None:
        self._factory = factory
        self._key_store = key_store
        self.policy: CallPolicy = policy or DirectPolicy()
        self.transfers: TransferLimiter = transfers or UnlimitedTransfers()
        self._lock = asyncio.Lock()
        self._client: Any = None
        self._session_string: str | None = None
        self._authorized: bool | None = None
        self._me: TelegramAccount | None = None
        self._peers: dict[int, Any] = {}
        self._dialogs_lock = asyncio.Lock()

    async def client(self) -> Any:
        """The connected client for the currently stored session (signed in or not)."""
        raw = await self._key_store.get(TELEGRAM_SESSION)
        stored = raw.decode("ascii", "replace") if raw is not None else ""
        async with self._lock:
            if self._client is not None and stored != self._session_string:
                await self._disconnect_locked()
            if self._client is None:
                self._client = await self._factory(stored)
                self._session_string = stored
                self._authorized = None
                self._me = None
                self._peers.clear()
            client = self._client
        if not client.is_connected():
            await self._guard(client.connect)
        return client

    async def authorized_client(self) -> Any:
        client = await self.client()
        if self._authorized is None:
            self._authorized = bool(await self._guard(client.is_user_authorized))
        if not self._authorized:
            raise not_authorized()
        return client

    async def call(self, operation: Callable[[Any], Awaitable[T]], *, authorized: bool = True) -> T:
        """Run `operation(client)` under the call policy, translating Telethon errors."""
        client = await (self.authorized_client() if authorized else self.client())
        return await self._guard(lambda: operation(client))

    async def account(self) -> TelegramAccount | None:
        """The signed-in account (cached until the session changes), or `None`."""
        client = await self.client()
        if self._authorized is False:
            return None
        if self._me is not None:
            return self._me
        user = await self._guard(client.get_me)
        if user is None:
            self._authorized = False
            return None
        self._authorized = True
        self._me = account_from_user(user)
        return self._me

    async def save_session(self, client: Any) -> None:
        """Persist the session of a client that just signed in."""
        value = client.session.save()
        await self._key_store.put(TELEGRAM_SESSION, value.encode("ascii"))
        async with self._lock:
            if client is self._client:
                self._session_string = value
                self._authorized = True
                self._me = None

    async def forget(self) -> None:
        """Drop the stored session and the client (after logging out)."""
        await self._key_store.delete(TELEGRAM_SESSION)
        await self.reload()

    async def reload(self) -> None:
        """Disconnect; the next call reconnects with whatever session is stored then (`account_reload`)."""
        async with self._lock:
            await self._disconnect_locked()

    def mark_unauthorized(self) -> None:
        self._authorized = False
        self._me = None

    async def input_peer(self, client: Any, peer_id: int) -> Any:
        """Input peer for a marked id; walks the dialogs once when the access hash is not known yet."""
        cached = self._peers.get(peer_id)
        if cached is not None:
            return cached
        try:
            peer = await client.get_input_entity(peer_id)
        except ValueError:
            peer = None
        if peer is None:
            async with self._dialogs_lock:
                if peer_id not in self._peers:
                    async for dialog in client.iter_dialogs():
                        self._peers.setdefault(int(dialog.id), dialog.input_entity)
                        if int(dialog.id) == peer_id:
                            break
            peer = self._peers.get(peer_id)
        if peer is None:
            raise StorageUnavailableError(StorageBackend.TELEGRAM.value)
        self._peers[peer_id] = peer
        return peer

    def remember_peer(self, peer_id: int, peer: Any) -> None:
        self._peers[peer_id] = peer

    async def _guard(self, operation: Callable[[], Awaitable[T]]) -> T:
        try:
            return await self.policy.run(operation)
        except DomainError as exc:
            if exc.code == "telegram_not_authorized":
                self.mark_unauthorized()
            raise
        except Exception as exc:
            mapped = map_telethon_error(exc)
            if mapped is None:
                raise
            if mapped.code == "telegram_not_authorized":
                self.mark_unauthorized()
            raise mapped from exc

    async def _disconnect_locked(self) -> None:
        client, self._client = self._client, None
        self._session_string = None
        self._authorized = None
        self._me = None
        self._peers.clear()
        if client is None:
            return
        try:
            result = client.disconnect()
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 - a dead connection is already disconnected
            pass


def account_from_user(user: Any) -> TelegramAccount:
    names = [getattr(user, "first_name", None), getattr(user, "last_name", None)]
    display = " ".join(part for part in names if part) or getattr(user, "username", None) or "Telegram"
    return TelegramAccount(
        user_id=int(user.id),
        display_name=display,
        username=getattr(user, "username", None),
        phone_masked=mask_phone(getattr(user, "phone", None)),
        premium=bool(getattr(user, "premium", False)),
    )


def mask_phone(phone: str | None) -> str | None:
    """`+57 ••• ••• 12`: enough to recognize the account, never the full number."""
    digits = "".join(character for character in phone or "" if character.isdigit())
    if len(digits) < 4:
        return None
    return f"+{digits[:2]} ••• ••• {digits[-2:]}"
