"""Persistence of content imports, so their progress outlives the process that ran them."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from bento.domain.imports import ContentImport, ImportItemState


class ContentImportStorePort(Protocol):
    async def create(self, job: ContentImport, *, owner: str, at: datetime) -> None: ...

    async def save_item(self, import_id: str, item: ImportItemState) -> None: ...

    async def finish(self, import_id: str, *, at: datetime) -> None: ...

    async def get(self, import_id: str) -> ContentImport | None: ...

    async def unfinished(self, *, other_than_owner: str) -> list[ContentImport]:
        """Imports another (earlier) process started and never finished."""
        ...

    async def replace_items(self, job: ContentImport, *, finished_at: datetime) -> None:
        """Stores every item of `job` and marks it finished."""
        ...

    async def dismiss(self, import_id: str, *, at: datetime) -> bool: ...

    async def prune(self, *, keep: int) -> None:
        """Drops the oldest finished imports beyond `keep`."""
        ...
