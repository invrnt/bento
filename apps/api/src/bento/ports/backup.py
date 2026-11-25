from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import BinaryIO, Protocol

from bento.domain.backup import (
    BackupFile,
    BackupPolicy,
    BackupSource,
    BackupSuggestion,
    MediaAccess,
    MediaBucket,
    MediaItem,
)


class BackupSourceRepositoryPort(Protocol):
    async def list(self) -> tuple[BackupSource, ...]: ...

    async def get(self, source_id: str) -> BackupSource | None: ...

    async def save(self, source: BackupSource) -> None: ...

    async def delete(self, source_id: str) -> None: ...


class BackupFileRepositoryPort(Protocol):
    async def get(self, source_id: str, relative_path: str) -> BackupFile | None: ...

    async def save(self, file: BackupFile) -> None: ...

    async def pending(self, *, limit: int = 50) -> tuple[BackupFile, ...]: ...

    async def counts(self, source_id: str) -> dict[str, int]:
        """Counts by `BackupFileState` value plus `bytes_pending`."""
        ...


class BackupPolicyRepositoryPort(Protocol):
    async def get(self) -> BackupPolicy: ...

    async def save(self, policy: BackupPolicy) -> None: ...


class FolderWatcherPort(Protocol):
    def watch(self, source_id: str, path: str, on_change: Callable[[str, str], None]) -> None:
        """Calls `on_change(source_id, absolute_path)` from a background thread; debounced by the caller."""
        ...

    def unwatch(self, source_id: str) -> None: ...

    def stop(self) -> None: ...


class BackupSuggestionsPort(Protocol):
    def suggestions(self) -> tuple[BackupSuggestion, ...]: ...


class MediaLibraryPort(Protocol):
    """The phone's media library (Android MediaStore) as a backup source (`api/android-endpoints.md` §3)."""

    def access(self) -> MediaAccess: ...

    def buckets(self) -> tuple[MediaBucket, ...]: ...

    def scan(self, bucket_id: str) -> Iterator[MediaItem]:
        """Every visible item of the bucket (pending and trashed items excluded), paged by the adapter."""
        ...

    def existing(self, media_ids: tuple[str, ...]) -> frozenset[str]:
        """The subset of `media_ids` still present."""
        ...

    def open(self, item: MediaItem, *, require_original: bool) -> BinaryIO:
        """A readable binary file over the item's content (adopted fd; closing it closes the fd)."""
        ...
