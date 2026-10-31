from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bento.domain.assets import AssetMetadata
from bento.domain.security import EncryptionMetadata
from bento.domain.storage import BlobKind, BlobRef


class BlobStorePort(Protocol):
    async def probe(self) -> bool: ...

    async def store(
        self,
        source_ref: str,
        *,
        asset_id: str | None,
        kind: BlobKind,
        metadata: AssetMetadata,
        encryption: EncryptionMetadata | None = None,
    ) -> BlobRef: ...

    async def get(self, blob_id: str) -> BlobRef | None: ...

    async def download(self, blob_ref: BlobRef, destination_path: Path | str) -> Path: ...

    async def delete(self, blob_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class RemoteBlobUpload:
    source_ref: str
    asset_id: str | None
    kind: BlobKind
    metadata: AssetMetadata


class RemoteBlobStorePort(BlobStorePort, Protocol):
    """Blob stores whose refs are self-describing (Telegram parts). Deletion and range reads take the ref itself."""

    async def store_many(self, uploads: Sequence[RemoteBlobUpload]) -> tuple[BlobRef, ...]:
        """Like `store` for each upload (same order), sending small blobs together in albums of up to 10."""
        ...

    async def delete_ref(self, blob_ref: BlobRef) -> None: ...

    async def read_range(self, blob_ref: BlobRef, start: int, length: int) -> bytes:
        """Decrypted plaintext bytes [start, start+length)."""
        ...
