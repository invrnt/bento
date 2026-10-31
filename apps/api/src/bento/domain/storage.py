from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from bento.domain.errors import ValidationFailedError
from bento.domain.security import EncryptionMetadata, EncryptionMode
from bento.domain.telegram import RemotePart


class StorageBackend(StrEnum):
    LOCAL = "local"
    TELEGRAM = "telegram"
    # Configured runtime only: blobs stored through the simulator keep `TELEGRAM` refs.
    FAKE = "fake"


class BlobKind(StrEnum):
    ORIGINAL = "original"
    THUMBNAIL = "thumbnail"
    PREVIEW = "preview"
    JOURNAL = "journal"


@dataclass(frozen=True, slots=True)
class BlobPart:
    """A slice of a remote ciphertext stream stored as one Telegram document."""

    index: int
    channel_id: str
    message_id: str
    size_bytes: int

    def __post_init__(self) -> None:
        if self.index < 0 or self.size_bytes < 0:
            raise ValidationFailedError("Blob part index and size cannot be negative")

    @classmethod
    def from_remote(cls, index: int, part: RemotePart) -> BlobPart:
        return cls(index=index, channel_id=str(part.channel_id), message_id=str(part.message_id), size_bytes=part.size_bytes)

    def remote(self) -> RemotePart:
        return RemotePart(channel_id=int(self.channel_id), message_id=int(self.message_id), size_bytes=self.size_bytes)


@dataclass(frozen=True, slots=True)
class BlobRef:
    id: str
    asset_id: str | None
    backend: StorageBackend
    kind: BlobKind
    object_key: str
    size_bytes: int
    sha256: str | None = None
    chat_id: str | None = None
    message_id: str | None = None
    file_id: str | None = None
    file_unique_id: str | None = None
    encryption: EncryptionMetadata = EncryptionMetadata(mode=EncryptionMode.NONE)
    parts: tuple[BlobPart, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValidationFailedError("Blob id is required")
        if not self.object_key.strip():
            raise ValidationFailedError("Blob object key is required")
        if self.size_bytes < 0:
            raise ValidationFailedError("Blob size cannot be negative", {"size_bytes": self.size_bytes})
        if [part.index for part in self.parts] != list(range(len(self.parts))):
            raise ValidationFailedError("Blob parts must be contiguous and ordered")
