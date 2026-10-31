"""`RemotePartStorePort` over Telethon: ciphertext parts as documents in the vault Files channel.

Uploads honor the parallel transfer slots and the bandwidth budget (token bucket fed by Telethon's progress
callback). Downloads stream with `iter_download` and resume at the same offset after a file reference refresh.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from telethon import errors, types

from bento.adapters.telegram_mtproto.session import MtprotoSession
from bento.domain.errors import IntegrityError, StorageUnavailableError, ValidationFailedError
from bento.domain.storage import StorageBackend
from bento.domain.telegram import RemotePart
from bento.domain.vault import VaultLayout

REQUEST_SIZE = 512 * 1024
ALBUM_SIZE = 10
FILE_REFERENCE_RETRIES = 3


class MtprotoRemotePartStore:
    def __init__(self, session: MtprotoSession) -> None:
        self._session = session

    async def upload_part(self, layout: VaultLayout, source: Path, *, filename: str) -> RemotePart:
        async with self._session.transfers.upload_slot():

            async def upload(client: Any) -> Any:
                channel = await self._session.input_peer(client, layout.files_channel_id)
                return await client.send_file(
                    channel,
                    str(source),
                    force_document=True,
                    attributes=[types.DocumentAttributeFilename(file_name=filename)],
                    mime_type="application/octet-stream",
                    silent=True,
                    progress_callback=self._progress(),
                )

            message = await self._session.call(upload)
        return _part(layout.files_channel_id, message)

    async def upload_parts(self, layout: VaultLayout, items: Sequence[tuple[Path, str]]) -> tuple[RemotePart, ...]:
        """One album request per 10 documents; each document is named after its `filename`."""
        if not items:
            return ()
        staging = Path(tempfile.mkdtemp(prefix="album-"))
        try:
            paths = [await asyncio.to_thread(_named, staging, index, Path(path), name) for index, (path, name) in enumerate(items)]
            parts: list[RemotePart] = []
            for offset in range(0, len(paths), ALBUM_SIZE):
                chunk = [str(path) for path in paths[offset : offset + ALBUM_SIZE]]
                async with self._session.transfers.upload_slot():

                    async def upload(client: Any, files: list[str] = chunk) -> Any:
                        channel = await self._session.input_peer(client, layout.files_channel_id)
                        return await client.send_file(
                            channel, files, force_document=True, silent=True, progress_callback=self._progress()
                        )

                    messages = await self._session.call(upload)
                if not isinstance(messages, list) or len(messages) != len(chunk):
                    raise StorageUnavailableError(StorageBackend.TELEGRAM.value)
                parts.extend(_part(layout.files_channel_id, message) for message in messages)
            return tuple(parts)
        finally:
            await asyncio.to_thread(shutil.rmtree, staging, True)

    async def download_part(self, part: RemotePart, destination: Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with self._session.transfers.download_slot():
            with destination.open("wb") as handle:

                async def write(chunk: bytes) -> bool:
                    handle.write(chunk)
                    return True

                written = await self._stream(part, 0, write)
        if written != part.size_bytes:
            destination.unlink(missing_ok=True)
            raise IntegrityError("blob_part")
        return destination

    async def read_part_range(self, part: RemotePart, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0:
            raise ValidationFailedError("Range offset and length cannot be negative")
        if length == 0 or offset >= part.size_bytes:
            return b""
        aligned = offset - offset % REQUEST_SIZE
        needed = offset - aligned + length
        buffer = bytearray()

        async def collect(chunk: bytes) -> bool:
            buffer.extend(chunk)
            return len(buffer) < needed

        async with self._session.transfers.download_slot():
            await self._stream(part, aligned, collect)
        return bytes(buffer[offset - aligned : offset - aligned + length])

    async def delete_parts(self, parts: tuple[RemotePart, ...]) -> None:
        by_channel: dict[int, list[int]] = defaultdict(list)
        for part in parts:
            by_channel[part.channel_id].append(part.message_id)
        for channel_id, message_ids in by_channel.items():

            async def delete(client: Any, channel_id: int = channel_id, ids: list[int] = message_ids) -> None:
                channel = await self._session.input_peer(client, channel_id)
                await client.delete_messages(channel, ids)

            await self._session.call(delete)

    async def _stream(self, part: RemotePart, offset: int, sink: Any) -> int:
        """Feed chunks from `offset` to `sink` until it returns False; returns the bytes delivered.

        The position survives retries (flood waits) and file reference refreshes, so no byte is delivered twice.
        """
        position = offset
        for _ in range(FILE_REFERENCE_RETRIES + 1):

            async def fetch(client: Any) -> Any:
                channel = await self._session.input_peer(client, part.channel_id)
                return await client.get_messages(channel, ids=part.message_id)

            message = await self._session.call(fetch)
            document = getattr(message, "document", None) if message is not None else None
            if document is None:
                raise StorageUnavailableError(StorageBackend.TELEGRAM.value)

            async def pump(client: Any, source: Any = document) -> bool:
                nonlocal position
                stream = client.iter_download(source, offset=position, request_size=REQUEST_SIZE, file_size=part.size_bytes)
                try:
                    async for chunk in stream:
                        position += len(chunk)
                        if not await sink(bytes(chunk)):
                            break
                except (errors.FileReferenceExpiredError, errors.FileReferenceInvalidError):
                    return False
                finally:
                    close = getattr(stream, "close", None)
                    if close is not None:
                        await close()
                return True

            if await self._session.call(pump):
                return position - offset
        raise StorageUnavailableError(StorageBackend.TELEGRAM.value)

    def _progress(self) -> Any:
        sent = 0

        async def progress(current: float, total: float) -> None:
            nonlocal sent
            del total
            delta = int(current) - sent
            if delta > 0:
                sent = int(current)
                await self._session.transfers.consume_upload(delta)

        return progress


def _part(channel_id: int, message: Any) -> RemotePart:
    size = getattr(getattr(message, "file", None), "size", None)
    if size is None:
        raise StorageUnavailableError(StorageBackend.TELEGRAM.value)
    return RemotePart(channel_id=channel_id, message_id=int(message.id), size_bytes=int(size))


def _named(staging: Path, index: int, source: Path, filename: str) -> Path:
    """`source` reachable under `filename` (albums take document names from paths)."""
    if source.name == filename:
        return source
    directory = staging / str(index)
    directory.mkdir()
    target = directory / Path(filename).name
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)
    return target
