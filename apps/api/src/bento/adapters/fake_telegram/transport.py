from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from bento.adapters.fake_telegram import store
from bento.adapters.fake_telegram.cloud import DocumentUpload, FakeChat, FakeMessage, missing_remote
from bento.adapters.fake_telegram.session import FakeTelegramSession
from bento.domain.errors import ValidationFailedError
from bento.domain.sync import SyncMessageKind, SyncMessageRef
from bento.domain.telegram import InboxItem, TelegramChatKind, TelegramMediaKind
from bento.domain.vault import (
    CHANNEL_TITLES,
    CHAT_FOLDER_TITLE,
    VaultChannelCandidate,
    VaultChannelRole,
    VaultLayout,
    channel_about,
    channel_marker,
    discover_vault_layouts,
    parse_channel_marker,
)


class FakeVaultTransport:
    def __init__(self, session: FakeTelegramSession) -> None:
        self._session = session
        self._cloud = session.cloud
        # Highest message id this instance has observed per channel; `wait_for_activity` fires past it.
        self._seen: dict[int, int] = {}

    async def find_vaults(self) -> tuple[VaultLayout, ...]:
        dialogs = await self._session.call(self._cloud.dialogs)
        return discover_vault_layouts(_candidates(dialogs))

    async def create_vault(self, vault_id: str) -> VaultLayout:
        if parse_channel_marker(channel_marker(VaultChannelRole.SYNC, vault_id)) != (VaultChannelRole.SYNC, vault_id):
            raise ValidationFailedError("Vault ids look like vlt_<id>", {"vault_id": vault_id})
        return await self._session.call(self._create_vault, vault_id)

    async def read_header_text(self, layout: VaultLayout) -> str | None:
        chat, messages = await self._session.call(self._cloud.read_chat, layout.sync_channel_id)
        pinned = next((item for item in messages if item.id == chat.pinned_message_id), None)
        if pinned is None or pinned.media is not None:
            return None
        return pinned.text

    async def publish_header_text(self, layout: VaultLayout, text: str) -> int:
        message = await self._session.call(self._cloud.post_message, layout.sync_channel_id, text=text, pin=True)
        return message.id

    async def post_sync_document(self, layout: VaultLayout, kind: SyncMessageKind, payload: bytes) -> SyncMessageRef:
        if not kind.suffix:
            raise ValidationFailedError("This Sync message kind is posted as text", {"kind": kind.value})
        upload = DocumentUpload(
            payload, f"{uuid.uuid4()}{kind.suffix}", "application/octet-stream", TelegramMediaKind.DOCUMENT
        )
        message = await self._session.call(self._cloud.post_message, layout.sync_channel_id, document=upload)
        return _sync_ref(message, kind)

    async def post_sync_text(self, layout: VaultLayout, kind: SyncMessageKind, text: str) -> SyncMessageRef:
        message = await self._session.call(self._cloud.post_message, layout.sync_channel_id, text=text)
        return _sync_ref(message, kind)

    async def list_sync_messages(
        self, layout: VaultLayout, *, after_message_id: int, limit: int = 100
    ) -> tuple[SyncMessageRef, ...]:
        chat, messages = await self._session.call(self._cloud.read_chat, layout.sync_channel_id)
        refs: list[SyncMessageRef] = []
        for message in messages:
            if message.id <= after_message_id:
                continue
            kind = _sync_kind(message)
            if kind is not None:
                refs.append(_sync_ref(message, kind))
            if len(refs) >= limit:
                break
        self._observe(chat, refs[-1].message_id if len(refs) >= limit else None)
        return tuple(refs)

    async def download_sync_document(self, layout: VaultLayout, message_id: int) -> bytes:
        path = await self._session.call(self._cloud.document_path, layout.sync_channel_id, message_id)
        return await self._session.run(_read_bytes, path)

    async def delete_sync_messages(self, layout: VaultLayout, message_ids: tuple[int, ...]) -> None:
        await self._session.call(self._cloud.delete_messages, layout.sync_channel_id, message_ids)

    async def wait_for_activity(self, layout: VaultLayout, timeout_seconds: float) -> bool:
        await self._session.require()
        channels = (layout.sync_channel_id, layout.inbox_channel_id)
        baseline: dict[int, int] = {}
        signatures: dict[int, tuple[int, int, int] | None] = {}
        for channel_id in channels:
            signatures[channel_id] = store.stat_signature(self._cloud.chat_log_path(channel_id))
            current = await self._session.run(self._cloud.last_message_id, channel_id)
            baseline[channel_id] = self._seen.get(channel_id, current)
            if current > baseline[channel_id]:
                return await self._fire(channels)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, timeout_seconds)
        while (remaining := deadline - loop.time()) > 0:
            await asyncio.sleep(min(self._session.options.poll_interval_seconds, remaining))
            for channel_id in channels:
                signature = store.stat_signature(self._cloud.chat_log_path(channel_id))
                if signature == signatures[channel_id]:
                    continue
                signatures[channel_id] = signature
                if await self._session.run(self._cloud.last_message_id, channel_id) > baseline[channel_id]:
                    return await self._fire(channels)
        return False

    async def list_inbox(self, layout: VaultLayout, *, after_message_id: int, limit: int = 50) -> tuple[InboxItem, ...]:
        chat, messages = await self._session.call(self._cloud.read_chat, layout.inbox_channel_id)
        items = [
            InboxItem(
                message_id=message.id,
                kind=message.media.kind,
                filename=message.media.filename,
                mime_type=message.media.mime_type,
                size_bytes=message.media.size_bytes,
                date=message.date,
                reactions=message.reactions,
            )
            for message in messages
            if message.id > after_message_id and message.media is not None
        ][:limit]
        self._observe(chat, items[-1].message_id if len(items) >= limit else None)
        return tuple(items)

    async def download_inbox_item(self, layout: VaultLayout, message_id: int, destination: Path) -> Path:
        path = await self._session.call(self._cloud.document_path, layout.inbox_channel_id, message_id)
        await self._session.run(store.copy_file, path, Path(destination))
        return Path(destination)

    async def react_inbox_item(self, layout: VaultLayout, message_id: int, emoji: str) -> None:
        await self._session.call(self._cloud.set_reaction, layout.inbox_channel_id, message_id, emoji)

    async def delete_inbox_items(self, layout: VaultLayout, message_ids: tuple[int, ...]) -> None:
        await self._session.call(self._cloud.delete_messages, layout.inbox_channel_id, message_ids)

    def _create_vault(self, vault_id: str) -> VaultLayout:
        with self._cloud.locked():
            existing: dict[VaultChannelRole, int] = {}
            for chat in self._cloud.dialogs():
                parsed = parse_channel_marker(chat.about) if chat.kind == TelegramChatKind.CHANNEL and chat.creator else None
                if parsed is not None and parsed[1] == vault_id:
                    existing.setdefault(parsed[0], chat.id)
            for role in VaultChannelRole:
                if role not in existing:
                    existing[role] = self._cloud.create_channel(CHANNEL_TITLES[role.value], channel_about(role, vault_id)).id
                self._cloud.update_chat(existing[role], muted=True, archived=role != VaultChannelRole.INBOX)
            self._cloud.add_to_folder(CHAT_FOLDER_TITLE, existing.values())
            return VaultLayout(
                vault_id=vault_id,
                files_channel_id=existing[VaultChannelRole.FILES],
                sync_channel_id=existing[VaultChannelRole.SYNC],
                inbox_channel_id=existing[VaultChannelRole.INBOX],
            )

    def _observe(self, chat: FakeChat, truncated_at: int | None) -> None:
        seen = chat.last_message_id if truncated_at is None else truncated_at
        self._seen[chat.id] = max(self._seen.get(chat.id, 0), seen)

    async def _fire(self, channels: tuple[int, ...]) -> bool:
        # Report each arrival once even if the caller never lists that channel.
        for channel_id in channels:
            current = await self._session.run(self._cloud.last_message_id, channel_id)
            self._seen[channel_id] = max(self._seen.get(channel_id, 0), current)
        return True


def _candidates(dialogs: tuple[FakeChat, ...]) -> list[VaultChannelCandidate]:
    return [
        VaultChannelCandidate(channel_id=chat.id, title=chat.title, about=chat.about, creator=chat.creator)
        for chat in dialogs
        if chat.kind == TelegramChatKind.CHANNEL
    ]


def _sync_kind(message: FakeMessage) -> SyncMessageKind | None:
    if message.media is not None:
        return SyncMessageKind.from_filename(message.media.filename)
    return SyncMessageKind.from_text(message.text or "")


def _sync_ref(message: FakeMessage, kind: SyncMessageKind) -> SyncMessageRef:
    if message.media is not None:
        return SyncMessageRef(
            message_id=message.id,
            kind=kind,
            filename=message.media.filename,
            size_bytes=message.media.size_bytes,
            created_at=message.date,
        )
    text = message.text or ""
    return SyncMessageRef(
        message_id=message.id,
        kind=kind,
        filename="",
        size_bytes=len(text.encode("utf-8")),
        created_at=message.date,
        text=text,
    )


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise missing_remote() from exc
