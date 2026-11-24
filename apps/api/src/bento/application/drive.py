from __future__ import annotations

from dataclasses import dataclass

from bento.domain.assets import Asset
from bento.domain.drive import DriveItem, DriveSort, Folder, SortOrder
from bento.domain.errors import AssetNotFoundError, FolderNotFoundError
from bento.domain.manifest import ManifestEntityType, ManifestEventType
from bento.ports.manifest import ManifestJournalPort
from bento.ports.repositories import AssetRepositoryPort, ClockPort, FolderRepositoryPort


@dataclass(frozen=True, slots=True)
class CreateFolderCommand:
    name: str
    parent_id: str | None = None


@dataclass(frozen=True, slots=True)
class RenameFolderCommand:
    folder_id: str
    name: str


@dataclass(frozen=True, slots=True)
class MoveFolderCommand:
    folder_id: str
    parent_id: str | None


@dataclass(frozen=True, slots=True)
class UpdateAssetCommand:
    asset_id: str
    filename: str


@dataclass(frozen=True, slots=True)
class MoveAssetCommand:
    asset_id: str
    folder_id: str | None


@dataclass(frozen=True, slots=True)
class ListDriveItemsQuery:
    folder_id: str | None = None
    cursor: str | None = None
    limit: int = 50
    sort: DriveSort | None = None
    order: SortOrder | None = None


@dataclass(frozen=True, slots=True)
class ListDriveItemsResult:
    items: tuple[DriveItem, ...]
    next_cursor: str | None


class DriveUseCases:
    def __init__(
        self,
        *,
        assets: AssetRepositoryPort,
        folders: FolderRepositoryPort,
        manifest: ManifestJournalPort,
        clock: ClockPort,
    ) -> None:
        self._assets = assets
        self._folders = folders
        self._manifest = manifest
        self._clock = clock

    async def create_folder(self, command: CreateFolderCommand) -> Folder:
        if command.parent_id is not None and await self._folders.get(command.parent_id) is None:
            raise FolderNotFoundError(command.parent_id)
        now = self._clock.now()
        folder = Folder(
            id=await self._folders.next_id(),
            name=command.name,
            parent_id=command.parent_id,
            created_at=now,
            updated_at=now,
        )
        await self._folders.add(folder)
        await self._manifest.append(
            type=ManifestEventType.FOLDER_CREATED,
            entity_type=ManifestEntityType.FOLDER,
            entity_id=folder.id,
            payload={"name": folder.name, "parent_id": folder.parent_id},
        )
        return folder

    async def list_items(self, query: ListDriveItemsQuery) -> ListDriveItemsResult:
        if query.folder_id is not None and await self._folders.get(query.folder_id) is None:
            raise FolderNotFoundError(query.folder_id)
        items, next_cursor = await self._folders.list_items(
            folder_id=query.folder_id,
            cursor=query.cursor,
            limit=query.limit,
            sort=query.sort,
            order=query.order,
        )
        return ListDriveItemsResult(items=items, next_cursor=next_cursor)

    async def rename_folder(self, command: RenameFolderCommand) -> Folder:
        folder = await self._require_folder(command.folder_id)
        updated = folder.rename(command.name, self._clock.now())
        await self._folders.save(updated)
        return updated

    async def move_folder(self, command: MoveFolderCommand) -> Folder:
        folder = await self._require_folder(command.folder_id)
        if command.parent_id is not None and await self._folders.get(command.parent_id) is None:
            raise FolderNotFoundError(command.parent_id)
        updated = folder.move_to(
            command.parent_id,
            await self._folders.descendant_ids(folder.id),
            self._clock.now(),
        )
        await self._folders.save(updated)
        await self._manifest.append(
            type=ManifestEventType.FOLDER_MOVED,
            entity_type=ManifestEntityType.FOLDER,
            entity_id=updated.id,
            payload={"parent_id": updated.parent_id},
        )
        return updated

    async def rename_asset(self, command: UpdateAssetCommand) -> Asset:
        asset = await self._require_asset(command.asset_id)
        updated = asset.rename(command.filename, self._clock.now())
        await self._assets.save(updated)
        await self._manifest.append(
            type=ManifestEventType.ASSET_UPDATED,
            entity_type=ManifestEntityType.ASSET,
            entity_id=updated.id,
            payload={"filename": updated.filename},
        )
        return updated

    async def move_asset(self, command: MoveAssetCommand) -> Asset:
        asset = await self._require_asset(command.asset_id)
        if command.folder_id is not None and await self._folders.get(command.folder_id) is None:
            raise FolderNotFoundError(command.folder_id)
        updated = asset.move_to(command.folder_id, self._clock.now())
        await self._assets.save(updated)
        await self._manifest.append(
            type=ManifestEventType.ASSET_UPDATED,
            entity_type=ManifestEntityType.ASSET,
            entity_id=updated.id,
            payload={"folder_id": updated.folder_id},
        )
        return updated

    async def delete_asset(self, asset_id: str) -> Asset:
        asset = await self._require_asset(asset_id)
        updated = asset.mark_deleted(self._clock.now())
        await self._assets.save(updated)
        await self._manifest.append(
            type=ManifestEventType.ASSET_DELETED,
            entity_type=ManifestEntityType.ASSET,
            entity_id=updated.id,
            payload={},
        )
        return updated

    async def delete_folder(self, folder_id: str) -> Folder:
        folder = await self._require_folder(folder_id)
        updated = folder.mark_deleted(self._clock.now())
        await self._folders.save(updated)
        return updated

    async def _require_asset(self, asset_id: str) -> Asset:
        asset = await self._assets.get(asset_id)
        if asset is None:
            raise AssetNotFoundError(asset_id)
        return asset

    async def _require_folder(self, folder_id: str) -> Folder:
        folder = await self._folders.get(folder_id)
        if folder is None:
            raise FolderNotFoundError(folder_id)
        return folder
