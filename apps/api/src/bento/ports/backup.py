from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from bento.domain.backup import BackupFile, BackupPolicy, BackupSource, BackupSuggestion


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
