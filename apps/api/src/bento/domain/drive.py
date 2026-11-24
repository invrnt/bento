from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from bento.domain.assets import Asset
from bento.domain.errors import InvalidFolderMoveError, ValidationFailedError


class DriveItemType(StrEnum):
    ASSET = "asset"
    FOLDER = "folder"


@dataclass(frozen=True, slots=True)
class Folder:
    id: str
    name: str
    parent_id: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValidationFailedError("Folder id is required")
        if not self.name.strip():
            raise ValidationFailedError("Folder name is required")

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def assert_can_move_to(self, parent_id: str | None, descendant_ids: set[str]) -> None:
        if parent_id == self.id or (parent_id is not None and parent_id in descendant_ids):
            raise InvalidFolderMoveError(self.id, parent_id)

    def move_to(self, parent_id: str | None, descendant_ids: set[str], at: datetime) -> Folder:
        self.assert_can_move_to(parent_id, descendant_ids)
        return replace(self, parent_id=parent_id, updated_at=at)

    def rename(self, name: str, at: datetime) -> Folder:
        if not name.strip():
            raise ValidationFailedError("Folder name is required")
        return replace(self, name=name, updated_at=at)

    def mark_deleted(self, at: datetime) -> Folder:
        return replace(self, deleted_at=at, updated_at=at)


@dataclass(frozen=True, slots=True)
class DriveItem:
    type: DriveItemType
    id: str
    name: str
    updated_at: datetime
    asset: Asset | None = None
    folder: Folder | None = None
    item_count: int | None = None
    """Folders only: live direct children (subfolders and files)."""


class DriveSort(StrEnum):
    NAME = "name"
    MODIFIED = "modified"
    SIZE = "size"
    KIND = "kind"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


def sort_drive_items(
    items: list[DriveItem] | tuple[DriveItem, ...], sort: DriveSort | None, order: SortOrder | None = None
) -> list[DriveItem]:
    """Without `sort`: newest first, folders and files mixed (the historical listing).

    With `sort`, folders always come first (like file managers) and both groups follow the key and `order`
    (default `asc`, `desc` for `modified`). Folders sort by item count for `size` and by name for `kind`;
    ties break on the name and then the id, so pages are stable."""
    if sort is None:
        return sorted(items, key=lambda item: (item.updated_at, item.type.value, item.id), reverse=True)
    descending = (order or (SortOrder.DESC if sort == DriveSort.MODIFIED else SortOrder.ASC)) == SortOrder.DESC
    folders = [item for item in items if item.type == DriveItemType.FOLDER]
    files = [item for item in items if item.type != DriveItemType.FOLDER]
    return _sorted_group(folders, sort, descending) + _sorted_group(files, sort, descending)


def _sorted_group(items: list[DriveItem], sort: DriveSort, descending: bool) -> list[DriveItem]:
    def name_key(item: DriveItem) -> tuple[str, str]:
        return (item.name.casefold(), item.id)

    # Stable sorts: the tie-breaker first, then the primary key.
    ordered = sorted(items, key=name_key)
    if sort == DriveSort.NAME:
        return sorted(ordered, key=name_key, reverse=descending)
    if sort == DriveSort.MODIFIED:
        return sorted(ordered, key=lambda item: item.updated_at, reverse=descending)
    if sort == DriveSort.SIZE:
        return sorted(ordered, key=_size_key, reverse=descending)
    return sorted(ordered, key=_kind_key, reverse=descending)


def _size_key(item: DriveItem) -> int:
    if item.asset is not None:
        return item.asset.metadata.size_bytes
    return item.item_count or 0


def _kind_key(item: DriveItem) -> tuple[str, str]:
    if item.asset is None:
        return ("", "")
    return (item.asset.kind.value, item.asset.metadata.mime_type)
