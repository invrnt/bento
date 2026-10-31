from __future__ import annotations

from pathlib import Path
from typing import Protocol

from bento.domain.account import AcceptedLogin, AccountStatus, TelegramAuthorization
from bento.domain.sync import SyncMessageKind, SyncMessageRef
from bento.domain.telegram import InboxItem, RemotePart, TelegramChat, TelegramMediaItem
from bento.domain.vault import VaultLayout


class TelegramAccountPort(Protocol):
    """This device's Telegram session. Implementations persist the session through `KeyStorePort`."""

    async def status(self) -> AccountStatus: ...

    async def start_qr_login(self) -> AccountStatus: ...

    async def poll_login(self) -> AccountStatus:
        """Advance a pending login; regenerates an expired QR token."""
        ...

    async def start_phone_login(self, phone: str) -> AccountStatus: ...

    async def submit_code(self, code: str) -> AccountStatus: ...

    async def submit_password(self, password: str) -> AccountStatus: ...

    async def accept_login_token(self, token: bytes) -> AcceptedLogin:
        """Authorize another device's pending QR login with this session (`auth.acceptLoginToken`)."""
        ...

    async def list_authorizations(self) -> tuple[TelegramAuthorization, ...]: ...

    async def terminate_authorization(self, authorization_hash: int) -> None: ...

    async def log_out(self) -> None: ...

    async def avatar_jpeg(self) -> bytes | None: ...


class VaultTransportPort(Protocol):
    """Vault channels: discovery, header, Sync channel messages, and the Inbox."""

    async def find_vaults(self) -> tuple[VaultLayout, ...]: ...

    async def create_vault(self, vault_id: str) -> VaultLayout:
        """Create the three channels, chat folder, mute/archive settings. Idempotent per `vault_id`."""
        ...

    async def read_header_text(self, layout: VaultLayout) -> str | None:
        """Text of the currently pinned Sync message, if any."""
        ...

    async def publish_header_text(self, layout: VaultLayout, text: str) -> int:
        """Post and pin a new header (unpinning the previous one). Returns its message id."""
        ...

    async def post_sync_document(self, layout: VaultLayout, kind: SyncMessageKind, payload: bytes) -> SyncMessageRef: ...

    async def post_sync_text(self, layout: VaultLayout, kind: SyncMessageKind, text: str) -> SyncMessageRef:
        """Plaintext Sync messages are only used for fallback pairing requests/offers."""
        ...

    async def list_sync_messages(
        self, layout: VaultLayout, *, after_message_id: int, limit: int = 100
    ) -> tuple[SyncMessageRef, ...]:
        """Ascending by message id; metadata only (documents are fetched with `download_sync_document`)."""
        ...

    async def download_sync_document(self, layout: VaultLayout, message_id: int, *, max_bytes: int | None = None) -> bytes:
        """The document of one Sync message. With `max_bytes`, a larger document raises `ValidationFailedError`
        before it is downloaded (the size is read again from the message, which may have been edited)."""
        ...

    async def delete_sync_messages(self, layout: VaultLayout, message_ids: tuple[int, ...]) -> None: ...

    async def wait_for_activity(self, layout: VaultLayout, timeout_seconds: float) -> bool:
        """Block until a new Sync or Inbox message arrives or the timeout elapses. True when activity arrived."""
        ...

    async def list_inbox(self, layout: VaultLayout, *, after_message_id: int, limit: int = 50) -> tuple[InboxItem, ...]: ...

    async def download_inbox_item(self, layout: VaultLayout, message_id: int, destination: Path) -> Path: ...

    async def react_inbox_item(self, layout: VaultLayout, message_id: int, emoji: str) -> None: ...

    async def delete_inbox_items(self, layout: VaultLayout, message_ids: tuple[int, ...]) -> None: ...


class RemotePartStorePort(Protocol):
    """Raw ciphertext part storage in the vault Files channel. Callers encrypt before upload."""

    async def upload_part(self, layout: VaultLayout, source: Path, *, filename: str) -> RemotePart: ...

    async def download_part(self, part: RemotePart, destination: Path) -> Path: ...

    async def read_part_range(self, part: RemotePart, offset: int, length: int) -> bytes: ...

    async def delete_parts(self, parts: tuple[RemotePart, ...]) -> None: ...


class TelegramChatsPort(Protocol):
    async def list_chats(self, *, query: str | None = None, limit: int = 30) -> tuple[TelegramChat, ...]: ...

    async def send_file(self, chat_id: int, source: Path, *, filename: str, caption: str | None = None) -> None: ...

    async def list_media(
        self, chat_id: int, *, before_message_id: int | None = None, limit: int = 60, kind: str = "all"
    ) -> tuple[TelegramMediaItem, ...]: ...

    async def download_media(self, chat_id: int, message_id: int, destination: Path) -> Path: ...
