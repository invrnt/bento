from __future__ import annotations

from datetime import datetime
from typing import Protocol

from bento.domain.trash import TrashItem


class TrashRepositoryPort(Protocol):
    async def list(self, *, cursor: str | None = None, limit: int = 50) -> tuple[tuple[TrashItem, ...], str | None]: ...

    async def restore(self, ids: tuple[str, ...]) -> int: ...

    async def expired(self, *, now: datetime, limit: int = 100) -> tuple[TrashItem, ...]: ...

    async def purge(self, ids: tuple[str, ...]) -> int:
        """Removes catalog rows after their blobs were deleted remotely and locally."""
        ...
