"""`VaultTransportPort` over Telethon: vault channels, header, Sync channel messages, and the Inbox.

Text is always sent with `parse_mode=None`: headers and pairing messages are JSON whose base64url values contain
`__`, which Markdown would otherwise eat.
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from pathlib import Path
from typing import Any

from telethon import errors, events, functions, types, utils

from bento.adapters.telegram_mtproto.media import message_media, own_reactions
from bento.adapters.telegram_mtproto.session import MtprotoSession
from bento.domain.errors import DomainError, StorageUnavailableError, TelegramFloodWaitError, ValidationFailedError
from bento.domain.storage import StorageBackend
from bento.domain.sync import SyncMessageKind, SyncMessageRef
from bento.domain.telegram import InboxItem
from bento.domain.vault import (
    CHANNEL_TITLES,
    CHAT_FOLDER_TITLE,
    VAULT_TITLE_PREFIX,
    VaultChannelCandidate,
    VaultChannelRole,
    VaultLayout,
    channel_about,
    discover_vault_layouts,
    parse_channel_marker,
)

LOGGER = logging.getLogger("bento.telegram.transport")

MAX_TEXT_CHARS = 4096
MUTE_FOREVER = 2**31 - 1
ARCHIVE_FOLDER_ID = 1
FIRST_CUSTOM_FILTER_ID = 2
MAX_FILTER_ID = 255
FILE_REFERENCE_RETRIES = 2


class MtprotoVaultTransport:
    def __init__(self, session: MtprotoSession) -> None:
        self._session = session
        self._activity = asyncio.Event()
        self._watched: tuple[Any, frozenset[int]] | None = None

    async def find_vaults(self) -> tuple[VaultLayout, ...]:
        return await self._session.call(self._find_vaults)

    async def create_vault(self, vault_id: str) -> VaultLayout:
        if parse_channel_marker(channel_about(VaultChannelRole.SYNC, vault_id)) != (VaultChannelRole.SYNC, vault_id):
            raise ValidationFailedError("Vault ids look like vlt_<id>", {"vault_id": vault_id})
        return await self._session.call(lambda client: self._create_vault(client, vault_id))

    async def read_header_text(self, layout: VaultLayout) -> str | None:
        async def read(client: Any) -> str | None:
            channel = await self._session.input_peer(client, layout.sync_channel_id)
            full = await client(functions.channels.GetFullChannelRequest(channel=channel))
            pinned = getattr(full.full_chat, "pinned_msg_id", None)
            if not pinned:
                return None
            message = await client.get_messages(channel, ids=pinned)
            if message is None or message.media is not None or getattr(message, "action", None) is not None:
                return None
            return message.message or None

        return await self._session.call(read)

    async def publish_header_text(self, layout: VaultLayout, text: str) -> int:
        _check_text(text)

        async def publish(client: Any) -> int:
            channel = await self._session.input_peer(client, layout.sync_channel_id)
            full = await client(functions.channels.GetFullChannelRequest(channel=channel))
            previous = getattr(full.full_chat, "pinned_msg_id", None)
            message = await client.send_message(channel, text, parse_mode=None, link_preview=False, silent=True)
            service = await client.pin_message(channel, message.id, notify=False)
            cleanup = [service.id] if service is not None and getattr(service, "id", None) else []
            if cleanup:
                await _best_effort(client.delete_messages(channel, cleanup))
            if previous and previous != message.id:
                await _best_effort(client.unpin_message(channel, previous))
            return int(message.id)

        return await self._session.call(publish)

    async def post_sync_document(self, layout: VaultLayout, kind: SyncMessageKind, payload: bytes) -> SyncMessageRef:
        if not kind.suffix:
            raise ValidationFailedError("This Sync message kind is posted as text", {"kind": kind.value})
        filename = f"{uuid.uuid4()}{kind.suffix}"

        async def post(client: Any) -> SyncMessageRef:
            channel = await self._session.input_peer(client, layout.sync_channel_id)
            upload = io.BytesIO(payload)
            upload.name = filename
            message = await client.send_file(
                channel,
                upload,
                force_document=True,
                attributes=[types.DocumentAttributeFilename(file_name=filename)],
                mime_type="application/octet-stream",
                silent=True,
            )
            return SyncMessageRef(
                message_id=int(message.id),
                kind=kind,
                filename=filename,
                size_bytes=len(payload),
                created_at=message.date,
            )

        return await self._session.call(post)

    async def post_sync_text(self, layout: VaultLayout, kind: SyncMessageKind, text: str) -> SyncMessageRef:
        _check_text(text)

        async def post(client: Any) -> SyncMessageRef:
            channel = await self._session.input_peer(client, layout.sync_channel_id)
            message = await client.send_message(channel, text, parse_mode=None, link_preview=False, silent=True)
            return SyncMessageRef(
                message_id=int(message.id),
                kind=kind,
                filename="",
                size_bytes=len(text.encode("utf-8")),
                created_at=message.date,
                text=text,
            )

        return await self._session.call(post)

    async def list_sync_messages(
        self, layout: VaultLayout, *, after_message_id: int, limit: int = 100
    ) -> tuple[SyncMessageRef, ...]:
        async def scan(client: Any) -> tuple[SyncMessageRef, ...]:
            channel = await self._session.input_peer(client, layout.sync_channel_id)
            refs: list[SyncMessageRef] = []
            async for message in client.iter_messages(channel, min_id=after_message_id, reverse=True):
                ref = _sync_ref(message)
                if ref is None:
                    continue
                refs.append(ref)
                if len(refs) >= limit:
                    break
            return tuple(refs)

        return await self._session.call(scan)

    async def download_sync_document(self, layout: VaultLayout, message_id: int, *, max_bytes: int | None = None) -> bytes:
        async def download(client: Any) -> bytes:
            channel = await self._session.input_peer(client, layout.sync_channel_id)
            data = await download_message(client, channel, message_id, bytes, max_bytes=max_bytes)
            if max_bytes is not None and len(data) > max_bytes:
                raise ValidationFailedError("Sync document exceeds the size limit", {"max_bytes": max_bytes})
            return bytes(data)

        return await self._session.call(download)

    async def delete_sync_messages(self, layout: VaultLayout, message_ids: tuple[int, ...]) -> None:
        await self._delete(layout.sync_channel_id, message_ids)

    async def wait_for_activity(self, layout: VaultLayout, timeout_seconds: float) -> bool:
        """New-message updates for the Sync and Inbox channels wake the caller; otherwise the timeout elapses."""
        client = await self._session.authorized_client()
        chats = frozenset({layout.sync_channel_id, layout.inbox_channel_id})
        if self._watched is None or self._watched[0] is not client or self._watched[1] != chats:
            if self._watched is not None:
                self._watched[0].remove_event_handler(self._on_message)
            client.add_event_handler(self._on_message, events.NewMessage(chats=list(chats)))
            self._watched = (client, chats)
        try:
            await asyncio.wait_for(self._activity.wait(), timeout=max(0.0, timeout_seconds))
        except (TimeoutError, asyncio.TimeoutError):
            return False
        self._activity.clear()
        return True

    async def list_inbox(self, layout: VaultLayout, *, after_message_id: int, limit: int = 50) -> tuple[InboxItem, ...]:
        async def scan(client: Any) -> tuple[InboxItem, ...]:
            channel = await self._session.input_peer(client, layout.inbox_channel_id)
            items: list[InboxItem] = []
            async for message in client.iter_messages(channel, min_id=after_message_id, reverse=True):
                media = message_media(message)
                if media is None:
                    continue
                items.append(
                    InboxItem(
                        message_id=int(message.id),
                        kind=media.kind,
                        filename=media.filename,
                        mime_type=media.mime_type,
                        size_bytes=media.size_bytes,
                        date=message.date,
                        reactions=own_reactions(message),
                    )
                )
                if len(items) >= limit:
                    break
            return tuple(items)

        return await self._session.call(scan)

    async def download_inbox_item(self, layout: VaultLayout, message_id: int, destination: Path) -> Path:
        async def download(client: Any) -> Path:
            channel = await self._session.input_peer(client, layout.inbox_channel_id)
            await download_message(client, channel, message_id, Path(destination))
            return Path(destination)

        return await self._session.call(download)

    async def react_inbox_item(self, layout: VaultLayout, message_id: int, emoji: str) -> None:
        async def react(client: Any) -> bool:
            channel = await self._session.input_peer(client, layout.inbox_channel_id)
            try:
                await client(
                    functions.messages.SendReactionRequest(
                        peer=channel, msg_id=message_id, reaction=[types.ReactionEmoji(emoticon=emoji)]
                    )
                )
            except (errors.ReactionInvalidError, errors.ReactionEmptyError, errors.ReactionsTooManyError):
                return False
            return True

        if not await self._session.call(react):
            raise ValidationFailedError("This reaction is not allowed in the Inbox", {"reason": "reaction_invalid"})

    async def delete_inbox_items(self, layout: VaultLayout, message_ids: tuple[int, ...]) -> None:
        await self._delete(layout.inbox_channel_id, message_ids)

    # Internals

    async def _on_message(self, event: Any) -> None:
        del event
        self._activity.set()

    async def _delete(self, channel_id: int, message_ids: tuple[int, ...]) -> None:
        if not message_ids:
            return

        async def delete(client: Any) -> None:
            channel = await self._session.input_peer(client, channel_id)
            await client.delete_messages(channel, list(message_ids))

        await self._session.call(delete)

    async def _bento_channels(self, client: Any) -> list[tuple[VaultChannelCandidate, Any]]:
        """Creator-owned broadcast channels titled `Bento…`, with their full `about` text."""
        found: list[tuple[VaultChannelCandidate, Any]] = []
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if not isinstance(entity, types.Channel) or not entity.broadcast or not entity.creator:
                continue
            if not (entity.title or "").startswith(VAULT_TITLE_PREFIX):
                continue
            full = await client(functions.channels.GetFullChannelRequest(channel=entity))
            peer_id = utils.get_peer_id(entity)
            self._session.remember_peer(peer_id, utils.get_input_peer(entity))
            candidate = VaultChannelCandidate(
                channel_id=peer_id, title=entity.title, about=full.full_chat.about or "", creator=True
            )
            found.append((candidate, entity))
        return found

    async def _find_vaults(self, client: Any) -> tuple[VaultLayout, ...]:
        return discover_vault_layouts(candidate for candidate, _ in await self._bento_channels(client))

    async def _create_vault(self, client: Any, vault_id: str) -> VaultLayout:
        existing: dict[VaultChannelRole, Any] = {}
        for candidate, entity in await self._bento_channels(client):
            parsed = parse_channel_marker(candidate.about)
            if parsed is not None and parsed[1] == vault_id:
                existing.setdefault(parsed[0], entity)
        for role in VaultChannelRole:
            if role in existing:
                continue
            result = await client(
                functions.channels.CreateChannelRequest(
                    title=CHANNEL_TITLES[role.value], about=channel_about(role, vault_id), broadcast=True
                )
            )
            channel = next(chat for chat in result.chats if isinstance(chat, types.Channel))
            existing[role] = channel
        peers = {role: utils.get_input_peer(entity) for role, entity in existing.items()}
        ids = {role: utils.get_peer_id(entity) for role, entity in existing.items()}
        for role, peer in peers.items():
            self._session.remember_peer(ids[role], peer)
            await _cosmetic(
                client(
                    functions.account.UpdateNotifySettingsRequest(
                        peer=types.InputNotifyPeer(peer=peer),
                        settings=types.InputPeerNotifySettings(show_previews=False, silent=True, mute_until=MUTE_FOREVER),
                    )
                ),
                "mute",
            )
        await _cosmetic(
            client(
                functions.folders.EditPeerFoldersRequest(
                    folder_peers=[
                        types.InputFolderPeer(
                            peer=peer, folder_id=0 if role == VaultChannelRole.INBOX else ARCHIVE_FOLDER_ID
                        )
                        for role, peer in peers.items()
                    ]
                )
            ),
            "archive",
        )
        await _cosmetic(self._add_to_folder(client, list(peers.values())), "folder")
        return VaultLayout(
            vault_id=vault_id,
            files_channel_id=ids[VaultChannelRole.FILES],
            sync_channel_id=ids[VaultChannelRole.SYNC],
            inbox_channel_id=ids[VaultChannelRole.INBOX],
        )

    async def _add_to_folder(self, client: Any, peers: list[Any]) -> None:
        """Put the vault channels in a chat folder titled `Bento` (created when missing)."""
        result = await client(functions.messages.GetDialogFiltersRequest())
        filters = list(getattr(result, "filters", result) or [])
        folder = next(
            (item for item in filters if isinstance(item, types.DialogFilter) and _filter_title(item) == CHAT_FOLDER_TITLE),
            None,
        )
        if folder is not None:
            known = {utils.get_peer_id(peer) for peer in folder.include_peers}
            include = list(folder.include_peers) + [peer for peer in peers if utils.get_peer_id(peer) not in known]
            if len(include) == len(folder.include_peers):
                return
            filter_id = folder.id
        else:
            used = {getattr(item, "id", None) for item in filters}
            filter_id = next((value for value in range(FIRST_CUSTOM_FILTER_ID, MAX_FILTER_ID + 1) if value not in used), None)
            if filter_id is None:
                return
            include = peers
        await client(
            functions.messages.UpdateDialogFilterRequest(
                id=filter_id,
                filter=types.DialogFilter(
                    id=filter_id,
                    title=types.TextWithEntities(text=CHAT_FOLDER_TITLE, entities=[]),
                    pinned_peers=list(folder.pinned_peers) if folder is not None else [],
                    include_peers=include,
                    exclude_peers=list(folder.exclude_peers) if folder is not None else [],
                ),
            )
        )


async def download_message(client: Any, peer: Any, message_id: int, file: Any, *, max_bytes: int | None = None) -> Any:
    """`download_media` of one message, re-fetching it when its file reference expired.

    With `max_bytes`, a document the message reports as larger is refused before anything is downloaded.
    """
    for attempt in range(FILE_REFERENCE_RETRIES + 1):
        message = await client.get_messages(peer, ids=message_id)
        if message is None or message.media is None:
            raise StorageUnavailableError(StorageBackend.TELEGRAM.value)
        if max_bytes is not None:
            size = getattr(getattr(message, "file", None), "size", None)
            if not isinstance(size, int) or size > max_bytes:
                raise ValidationFailedError("Sync document exceeds the size limit", {"max_bytes": max_bytes})
        try:
            result = await client.download_media(message, file=str(file) if isinstance(file, Path) else file)
        except (errors.FileReferenceExpiredError, errors.FileReferenceInvalidError):
            if attempt == FILE_REFERENCE_RETRIES:
                raise
            continue
        if result is None:
            raise StorageUnavailableError(StorageBackend.TELEGRAM.value)
        return result
    raise StorageUnavailableError(StorageBackend.TELEGRAM.value)


def _sync_ref(message: Any) -> SyncMessageRef | None:
    if getattr(message, "action", None) is not None:
        return None
    if getattr(message, "document", None) is not None:
        filename = getattr(message.file, "name", None) or ""
        kind = SyncMessageKind.from_filename(filename)
        if kind is None:
            return None
        return SyncMessageRef(
            message_id=int(message.id),
            kind=kind,
            filename=filename,
            size_bytes=int(getattr(message.file, "size", 0) or 0),
            created_at=message.date,
        )
    text = getattr(message, "message", None)
    if not text or getattr(message, "media", None) is not None:
        return None
    kind = SyncMessageKind.from_text(text)
    if kind is None:
        return None
    return SyncMessageRef(
        message_id=int(message.id),
        kind=kind,
        filename="",
        size_bytes=len(text.encode("utf-8")),
        created_at=message.date,
        text=text,
    )


def _filter_title(item: Any) -> str:
    title = getattr(item, "title", "")
    return str(getattr(title, "text", title) or "")


def _check_text(text: str) -> None:
    if len(text) > MAX_TEXT_CHARS:
        raise ValidationFailedError("Telegram message is too long", {"length": len(text)})


async def _cosmetic(operation: Any, what: str) -> None:
    """Mute/archive/folder are conveniences: a refusal never blocks vault creation (flood waits still surface)."""
    try:
        await operation
    except TelegramFloodWaitError:
        raise
    except errors.FloodError:
        raise
    except (errors.RPCError, DomainError) as exc:
        LOGGER.info("Vault channel %s step skipped: %s", what, type(exc).__name__)


async def _best_effort(operation: Any) -> None:
    try:
        await operation
    except errors.FloodError:
        raise
    except errors.RPCError as exc:
        LOGGER.info("Header housekeeping skipped: %s", type(exc).__name__)
