from __future__ import annotations

from datetime import datetime
from typing import Protocol

from bento.domain.assets import Asset
from bento.domain.drive import DriveItem, DriveSort, Folder, SortOrder
from bento.domain.photos import Album, TimelineGroup


class AssetRepositoryPort(Protocol):
    async def next_id(self) -> str: ...

    async def get(self, asset_id: str) -> Asset | None: ...

    async def get_by_sha256(self, sha256: str) -> Asset | None: ...

    async def add(self, asset: Asset) -> None: ...

    async def save(self, asset: Asset) -> None: ...

    async def list_photos_timeline(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[tuple[TimelineGroup, ...], str | None]: ...


class FolderRepositoryPort(Protocol):
    async def next_id(self) -> str: ...

    async def get(self, folder_id: str) -> Folder | None: ...

    async def add(self, folder: Folder) -> None: ...

    async def save(self, folder: Folder) -> None: ...

    async def descendant_ids(self, folder_id: str) -> set[str]: ...

    async def list_items(
        self,
        *,
        folder_id: str | None,
        cursor: str | None = None,
        limit: int = 50,
        sort: DriveSort | None = None,
        order: SortOrder | None = None,
    ) -> tuple[tuple[DriveItem, ...], str | None]: ...


class AlbumRepositoryPort(Protocol):
    async def next_id(self) -> str: ...

    async def get(self, album_id: str) -> Album | None: ...

    async def add(self, album: Album) -> None: ...

    async def save(self, album: Album) -> None: ...

    async def list(self, *, cursor: str | None = None, limit: int = 50) -> tuple[tuple[Album, ...], str | None]: ...


class ClockPort(Protocol):
    def now(self) -> datetime: ...
