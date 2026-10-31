from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from bento.adapters.fake_telegram import store
from bento.adapters.fake_telegram.cloud import DocumentUpload, missing_remote
from bento.adapters.fake_telegram.session import FakeTelegramSession
from bento.domain.errors import ValidationFailedError
from bento.domain.telegram import RemotePart, TelegramMediaKind
from bento.domain.vault import VaultLayout


class FakeRemotePartStore:
    def __init__(self, session: FakeTelegramSession) -> None:
        self._session = session
        self._cloud = session.cloud

    async def upload_part(self, layout: VaultLayout, source: Path, *, filename: str) -> RemotePart:
        upload = DocumentUpload(Path(source), filename, "application/octet-stream", TelegramMediaKind.DOCUMENT)
        message = await self._session.call(self._cloud.post_message, layout.files_channel_id, document=upload)
        size = message.media.size_bytes if message.media is not None else 0
        return RemotePart(channel_id=layout.files_channel_id, message_id=message.id, size_bytes=size)

    async def download_part(self, part: RemotePart, destination: Path) -> Path:
        path = await self._session.call(self._cloud.document_path, part.channel_id, part.message_id)
        await self._session.run(store.copy_file, path, Path(destination))
        return Path(destination)

    async def read_part_range(self, part: RemotePart, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0:
            raise ValidationFailedError("Range offset and length cannot be negative")
        path = await self._session.call(self._cloud.document_path, part.channel_id, part.message_id)
        return await self._session.run(_read_range, path, offset, length)

    async def delete_parts(self, parts: tuple[RemotePart, ...]) -> None:
        await self._session.require()
        by_channel: dict[int, list[int]] = defaultdict(list)
        for part in parts:
            by_channel[part.channel_id].append(part.message_id)
        for channel_id, message_ids in by_channel.items():
            await self._session.run(self._cloud.delete_messages, channel_id, message_ids)


def _read_range(path: Path, offset: int, length: int) -> bytes:
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            return handle.read(length)
    except FileNotFoundError as exc:
        raise missing_remote() from exc
