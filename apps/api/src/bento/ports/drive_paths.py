"""Batch read queries used to address the Drive by path (CLI support). Every method ignores trashed rows."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from bento.domain.assets import Asset
from bento.domain.drive import Folder


class FolderTreeQueryPort(Protocol):
    async def get_many(self, folder_ids: Sequence[str]) -> dict[str, Folder]: ...

    async def list_children(self, parent_ids: Sequence[str | None]) -> tuple[Folder, ...]:
        """Folders whose parent is one of `parent_ids` (`None` = the Drive root)."""
        ...

    async def ids_with_children(self, folder_ids: Sequence[str], *, include_assets: bool) -> set[str]:
        """The subset of `folder_ids` that contain at least one folder (or asset, when `include_assets`)."""
        ...


class AssetTreeQueryPort(Protocol):
    async def get_many(self, asset_ids: Sequence[str]) -> dict[str, Asset]: ...

    async def get_many_by_sha256(self, sha256s: Sequence[str]) -> dict[str, Asset]:
        """The newest asset per hash, matching `AssetRepositoryPort.get_by_sha256`."""
        ...

    async def list_in_folders(self, folder_ids: Sequence[str | None], *, limit: int | None = None) -> tuple[Asset, ...]:
        """Assets directly inside `folder_ids` (`None` = the Drive root), at most `limit` rows, ordered by
        folder id (root first), then filename and id, so a capped result is complete for every folder id below
        the last row's."""
        ...
