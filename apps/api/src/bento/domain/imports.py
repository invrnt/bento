"""Imports of content handed over by the host as file descriptors (`api/android-endpoints.md` §4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

IMPORT_INTERRUPTED = "import_interrupted"
"""Error code of items whose import was cut short by a process restart: their fds died with the process."""
CONTENT_UNREADABLE = "content_unreadable"
ALBUM_UNAVAILABLE = "album_unavailable"


class ImportItemStatus(StrEnum):
    PENDING = "pending"
    IMPORTING = "importing"
    DONE = "done"
    DUPLICATE = "duplicate"
    FAILED = "failed"


UNFINISHED_ITEM_STATUSES = frozenset({ImportItemStatus.PENDING.value, ImportItemStatus.IMPORTING.value})


@dataclass(slots=True)
class ImportItemState:
    client_index: int
    status: str = ImportItemStatus.PENDING.value
    asset_id: str | None = None
    error: str | None = None


@dataclass(slots=True)
class ContentImport:
    id: str
    items: list[ImportItemState]
    folder_id: str | None = None
    album_id: str | None = None
    done: bool = False
    dismissed: bool = field(default=False)

    @property
    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in self.items:
            result[item.status] = result.get(item.status, 0) + 1
        return result

    @property
    def failed(self) -> int:
        return sum(1 for item in self.items if item.status == ImportItemStatus.FAILED.value)

    def interrupt(self) -> int:
        """Fails every unfinished item with `import_interrupted`; returns how many."""
        interrupted = 0
        for item in self.items:
            if item.status in UNFINISHED_ITEM_STATUSES:
                item.status, item.error = ImportItemStatus.FAILED.value, IMPORT_INTERRUPTED
                interrupted += 1
        self.done = True
        return interrupted
