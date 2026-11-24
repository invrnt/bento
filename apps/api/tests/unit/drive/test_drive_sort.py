from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bento.domain.assets import Asset, AssetKind, AssetMetadata, AssetMode, ProcessingState
from bento.domain.drive import DriveItem, DriveItemType, DriveSort, Folder, SortOrder, sort_drive_items

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _folder(item_id: str, name: str, minutes: int, count: int) -> DriveItem:
    at = T0 + timedelta(minutes=minutes)
    folder = Folder(id=item_id, name=name, parent_id=None, created_at=at, updated_at=at)
    return DriveItem(type=DriveItemType.FOLDER, id=item_id, name=name, updated_at=at, folder=folder, item_count=count)


def _file(item_id: str, name: str, minutes: int, size: int, mime: str, kind: AssetKind) -> DriveItem:
    at = T0 + timedelta(minutes=minutes)
    asset = Asset(
        id=item_id,
        kind=kind,
        mode=AssetMode.DRIVE,
        folder_id=None,
        filename=name,
        metadata=AssetMetadata(original_filename=name, mime_type=mime, size_bytes=size, sha256="a" * 64),
        processing_state=ProcessingState.INDEXED,
        favorite=False,
        created_at=at,
        updated_at=at,
    )
    return DriveItem(type=DriveItemType.ASSET, id=item_id, name=name, updated_at=at, asset=asset)


ITEMS = [
    _file("a1", "b.pdf", 5, 300, "application/pdf", AssetKind.PDF),
    _folder("f1", "Zeta", 1, 4),
    _file("a2", "A.jpg", 2, 100, "image/jpeg", AssetKind.IMAGE),
    _folder("f2", "alfa", 9, 1),
]


def _ids(items: list[DriveItem]) -> list[str]:
    return [item.id for item in items]


def test_default_listing_stays_newest_first_and_mixed() -> None:
    assert _ids(sort_drive_items(ITEMS, None)) == ["f2", "a1", "a2", "f1"]


def test_name_sort_is_case_insensitive_with_folders_first() -> None:
    assert _ids(sort_drive_items(ITEMS, DriveSort.NAME)) == ["f2", "f1", "a2", "a1"]
    assert _ids(sort_drive_items(ITEMS, DriveSort.NAME, SortOrder.DESC)) == ["f1", "f2", "a1", "a2"]


def test_modified_defaults_to_descending() -> None:
    assert _ids(sort_drive_items(ITEMS, DriveSort.MODIFIED)) == ["f2", "f1", "a1", "a2"]
    assert _ids(sort_drive_items(ITEMS, DriveSort.MODIFIED, SortOrder.ASC)) == ["f1", "f2", "a2", "a1"]


def test_size_sorts_files_by_bytes_and_folders_by_item_count() -> None:
    assert _ids(sort_drive_items(ITEMS, DriveSort.SIZE)) == ["f2", "f1", "a2", "a1"]
    assert _ids(sort_drive_items(ITEMS, DriveSort.SIZE, SortOrder.DESC)) == ["f1", "f2", "a1", "a2"]


def test_kind_groups_files_by_kind() -> None:
    assert _ids(sort_drive_items(ITEMS, DriveSort.KIND)) == ["f2", "f1", "a2", "a1"]  # image < pdf
