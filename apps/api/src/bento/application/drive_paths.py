"""Address the Drive by path (`api/cli-endpoints.md`): resolve, mkdir -p, bounded tree, id -> path, sha256 lookup."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from bento.application.drive import CreateFolderCommand, DriveUseCases
from bento.domain.assets import Asset
from bento.domain.drive import Folder
from bento.domain.drive_paths import (
    ROOT_PATH,
    DriveIdRef,
    DriveNodeKind,
    DrivePath,
    DriveRef,
    PathAmbiguousError,
    PathCandidate,
    PathNotFoundError,
    format_drive_path,
    name_matches,
    sort_key,
)
from bento.domain.errors import ValidationFailedError
from bento.ports.drive_paths import AssetTreeQueryPort, FolderTreeQueryPort

MAX_BATCH_IDS = 500
MAX_TREE_DEPTH = 20
DEFAULT_TREE_DEPTH = 3
MAX_TREE_NODES = 10_000
DEFAULT_TREE_NODES = 2_000
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class ResolvedDriveItem:
    kind: DriveNodeKind
    path: str
    folder: Folder | None = None
    asset: Asset | None = None
    breadcrumbs: tuple[Folder, ...] = ()
    """Folders from the root down to the item's folder (the folder itself for a folder)."""


@dataclass(frozen=True, slots=True)
class EnsureFolderResult:
    folder: Folder | None
    path: str
    created: tuple[str, ...]


@dataclass(slots=True)
class DriveTreeNode:
    kind: DriveNodeKind
    name: str
    path: str
    folder: Folder | None = None
    asset: Asset | None = None
    children: list[DriveTreeNode] | None = None
    """None when not expanded (depth or node limit); see `has_more`."""
    has_more: bool = False

    @property
    def id(self) -> str | None:
        if self.folder is not None:
            return self.folder.id
        return self.asset.id if self.asset is not None else None


@dataclass(frozen=True, slots=True)
class DriveTreeResult:
    root: DriveTreeNode
    truncated: bool
    nodes: int


@dataclass(frozen=True, slots=True)
class DrivePathsResult:
    paths: dict[str, str]
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LookupMatch:
    asset: Asset
    path: str


class DrivePathUseCases:
    def __init__(self, *, folders: FolderTreeQueryPort, assets: AssetTreeQueryPort, drive: DriveUseCases) -> None:
        self._folders = folders
        self._assets = assets
        self._drive = drive
        # Serializes `ensure` in this process so concurrent mkdir -p calls never create sibling duplicates.
        self._ensure_lock = asyncio.Lock()

    async def resolve(self, ref: DriveRef) -> ResolvedDriveItem:
        if isinstance(ref, DriveIdRef):
            return await self._resolve_id(ref.id)
        return await self._resolve_path(ref)

    async def ensure_folder(self, ref: DriveRef) -> EnsureFolderResult:
        if isinstance(ref, DriveIdRef):
            resolved = await self._resolve_id(ref.id)
            if resolved.kind == DriveNodeKind.ASSET:
                raise ValidationFailedError("Path is not a folder", {"reason": "not_a_folder", "path": resolved.path})
            return EnsureFolderResult(folder=resolved.folder, path=resolved.path, created=())
        async with self._ensure_lock:
            parent: Folder | None = None
            created: list[str] = []
            for segment in ref.segments:
                existing = [] if created else await self._matching_folders(parent, segment)
                if existing:
                    parent = min(existing, key=lambda folder: (folder.created_at, folder.id))
                    continue
                parent = await self._drive.create_folder(
                    CreateFolderCommand(name=segment, parent_id=parent.id if parent is not None else None)
                )
                created.append(parent.id)
        return EnsureFolderResult(folder=parent, path=ref.canonical, created=tuple(created))

    async def tree(
        self,
        ref: DriveRef,
        *,
        depth: int = DEFAULT_TREE_DEPTH,
        include_assets: bool = True,
        max_nodes: int = DEFAULT_TREE_NODES,
    ) -> DriveTreeResult:
        if not 1 <= depth <= MAX_TREE_DEPTH:
            raise ValidationFailedError("Invalid tree depth", {"reason": "depth", "max": MAX_TREE_DEPTH})
        if not 1 <= max_nodes <= MAX_TREE_NODES:
            raise ValidationFailedError("Invalid tree node limit", {"reason": "max_nodes", "max": MAX_TREE_NODES})
        resolved = await self.resolve(ref)
        if resolved.asset is not None:
            return DriveTreeResult(root=_asset_node(resolved.asset, resolved.path), truncated=False, nodes=1)
        root = DriveTreeNode(
            kind=resolved.kind,
            name=resolved.folder.name if resolved.folder is not None else ROOT_PATH,
            path=resolved.path,
            folder=resolved.folder,
        )
        nodes = 1
        truncated = False
        out_of_budget = False
        level = [root]
        for _ in range(depth):
            if not level:
                break
            if nodes >= max_nodes:
                out_of_budget = True
                break
            parent_ids = [node.id for node in level]
            child_folders = await self._folders.list_children(parent_ids)
            remaining = max_nodes - nodes
            child_assets = (
                await self._assets.list_in_folders(parent_ids, limit=remaining + 1) if include_assets else ()
            )
            # A capped asset query is complete only for folder ids sorting below its last row's.
            capped = len(child_assets) > remaining
            last_folder_id = child_assets[-1].folder_id if capped else None
            folders_by_parent = _group(child_folders, lambda folder: folder.parent_id)
            assets_by_parent = _group(child_assets, lambda asset: asset.folder_id)
            next_level: list[DriveTreeNode] = []
            for node in level:
                node.children = []
                kids: list[DriveTreeNode] = [
                    _folder_node(folder, _child_path(node.path, folder.name))
                    for folder in sorted(folders_by_parent.get(node.id, ()), key=lambda f: sort_key(f.name, f.id))
                ]
                kids.extend(
                    _asset_node(asset, _child_path(node.path, asset.filename))
                    for asset in sorted(assets_by_parent.get(node.id, ()), key=lambda a: sort_key(a.filename, a.id))
                )
                for kid in kids:
                    if nodes >= max_nodes:
                        node.has_more = True
                        truncated = True
                        break
                    node.children.append(kid)
                    nodes += 1
                    if kid.kind == DriveNodeKind.FOLDER:
                        next_level.append(kid)
                if capped and not _sorts_below(node.id, last_folder_id):
                    node.has_more = True
                    truncated = True
            level = next_level
        if level:
            with_children: set[str | None] = set(
                await self._folders.ids_with_children(
                    [node.id for node in level if node.id is not None], include_assets=include_assets
                )
            )
            if any(node.id is None for node in level) and await self._root_has_children(include_assets):
                with_children.add(None)
            for node in level:
                if node.id in with_children:
                    node.has_more = True
                    truncated = truncated or out_of_budget
                else:
                    node.children = []
        return DriveTreeResult(root=root, truncated=truncated, nodes=nodes)

    async def paths_for_ids(self, ids: Sequence[str]) -> DrivePathsResult:
        _check_batch(ids, "ids")
        unique = list(dict.fromkeys(ids))
        folders = await self._folders.get_many(unique)
        assets = await self._assets.get_many([item_id for item_id in unique if item_id not in folders])
        chains = await self._folder_chains(
            [folder.id for folder in folders.values()] + [asset.folder_id for asset in assets.values() if asset.folder_id]
        )
        paths: dict[str, str] = {}
        missing: list[str] = []
        for item_id in unique:
            if item_id in folders:
                chain = chains.get(item_id)
                path = format_drive_path(folder.name for folder in chain) if chain is not None else None
            elif item_id in assets:
                path = _asset_path(assets[item_id], chains)
            else:
                path = None
            if path is None:
                missing.append(item_id)
            else:
                paths[item_id] = path
        return DrivePathsResult(paths=paths, missing=tuple(missing))

    async def lookup_sha256(self, sha256s: Sequence[str]) -> dict[str, LookupMatch]:
        _check_batch(sha256s, "sha256")
        invalid = [value for value in sha256s if not _SHA256.fullmatch(value)]
        if invalid:
            raise ValidationFailedError("Invalid sha256", {"reason": "invalid_sha256", "count": len(invalid)})
        assets = await self._assets.get_many_by_sha256(list(dict.fromkeys(sha256s)))
        chains = await self._folder_chains([asset.folder_id for asset in assets.values() if asset.folder_id])
        matches: dict[str, LookupMatch] = {}
        for sha256, asset in assets.items():
            path = _asset_path(asset, chains)
            if path is not None:  # an asset inside a trashed folder is not addressable in the Drive
                matches[sha256] = LookupMatch(asset=asset, path=path)
        return matches

    async def _resolve_path(self, path: DrivePath) -> ResolvedDriveItem:
        parent: Folder | None = None
        chain: list[Folder] = []
        last_index = len(path.segments) - 1
        for index, segment in enumerate(path.segments):
            folders = await self._matching_folders(parent, segment)
            assets: list[Asset] = []
            if index == last_index and not path.must_be_folder:
                parent_id = parent.id if parent is not None else None
                assets = [
                    asset for asset in await self._assets.list_in_folders([parent_id]) if name_matches(asset.filename, segment)
                ]
            if not folders and not assets:
                raise PathNotFoundError(path.canonical, index)
            if len(folders) + len(assets) > 1:
                prefix = path.prefix(index + 1)
                raise PathAmbiguousError(
                    path.canonical,
                    [PathCandidate(f.id, DriveNodeKind.FOLDER, prefix, f.created_at) for f in folders]
                    + [PathCandidate(a.id, DriveNodeKind.ASSET, prefix, a.created_at) for a in assets],
                )
            if assets:
                return ResolvedDriveItem(
                    kind=DriveNodeKind.ASSET, path=path.canonical, asset=assets[0], breadcrumbs=tuple(chain)
                )
            parent = folders[0]
            chain.append(parent)
        if parent is None:
            return ResolvedDriveItem(kind=DriveNodeKind.ROOT, path=ROOT_PATH)
        return ResolvedDriveItem(kind=DriveNodeKind.FOLDER, path=path.canonical, folder=parent, breadcrumbs=tuple(chain))

    async def _resolve_id(self, item_id: str) -> ResolvedDriveItem:
        reference = f"id:{item_id}"
        folders = await self._folders.get_many([item_id])
        if item_id in folders:
            chain = (await self._folder_chains([item_id])).get(item_id)
            if chain is None:
                raise PathNotFoundError(reference, 0)
            return ResolvedDriveItem(
                kind=DriveNodeKind.FOLDER,
                path=format_drive_path(folder.name for folder in chain),
                folder=folders[item_id],
                breadcrumbs=chain,
            )
        asset = (await self._assets.get_many([item_id])).get(item_id)
        if asset is None:
            raise PathNotFoundError(reference, 0)
        chains = await self._folder_chains([asset.folder_id] if asset.folder_id else [])
        path = _asset_path(asset, chains)
        if path is None:
            raise PathNotFoundError(reference, 0)
        return ResolvedDriveItem(
            kind=DriveNodeKind.ASSET,
            path=path,
            asset=asset,
            breadcrumbs=(chains.get(asset.folder_id) or ()) if asset.folder_id else (),
        )

    async def _root_has_children(self, include_assets: bool) -> bool:
        if await self._folders.list_children([None]):
            return True
        return include_assets and bool(await self._assets.list_in_folders([None], limit=1))

    async def _matching_folders(self, parent: Folder | None, segment: str) -> list[Folder]:
        children = await self._folders.list_children([parent.id if parent is not None else None])
        return [folder for folder in children if name_matches(folder.name, segment)]

    async def _folder_chains(self, folder_ids: Iterable[str]) -> dict[str, tuple[Folder, ...] | None]:
        """Root-to-folder chains, one batch query per tree level. None when an ancestor is trashed or missing."""
        known: dict[str, Folder] = {}
        unavailable: set[str] = set()
        frontier = set(folder_ids)
        while frontier:
            found = await self._folders.get_many(sorted(frontier))
            known.update(found)
            unavailable.update(frontier - found.keys())
            frontier = {
                folder.parent_id
                for folder in found.values()
                if folder.parent_id is not None and folder.parent_id not in known and folder.parent_id not in unavailable
            }
        chains: dict[str, tuple[Folder, ...] | None] = {}
        for folder_id in folder_ids:
            chain: list[Folder] = []
            seen: set[str] = set()
            current: str | None = folder_id
            while current is not None and current in known and current not in seen:
                seen.add(current)
                chain.append(known[current])
                current = known[current].parent_id
            chains[folder_id] = tuple(reversed(chain)) if current is None else None
        return chains


def _asset_path(asset: Asset, chains: dict[str, tuple[Folder, ...] | None]) -> str | None:
    if asset.folder_id is None:
        return format_drive_path([asset.filename])
    chain = chains.get(asset.folder_id)
    if chain is None:
        return None
    return format_drive_path([*(folder.name for folder in chain), asset.filename])


def _child_path(parent_path: str, name: str) -> str:
    child = format_drive_path([name])
    return child if parent_path == ROOT_PATH else parent_path + child


def _folder_node(folder: Folder, path: str) -> DriveTreeNode:
    return DriveTreeNode(kind=DriveNodeKind.FOLDER, name=folder.name, path=path, folder=folder)


def _asset_node(asset: Asset, path: str) -> DriveTreeNode:
    return DriveTreeNode(kind=DriveNodeKind.ASSET, name=asset.filename, path=path, asset=asset, children=None)


def _group[T](items: Iterable[T], key: Callable[[T], str | None]) -> dict[str | None, list[T]]:
    grouped: dict[str | None, list[T]] = {}
    for item in items:
        grouped.setdefault(key(item), []).append(item)
    return grouped


def _sorts_below(folder_id: str | None, last: str | None) -> bool:
    """Whether `folder_id` sorts strictly before `last` in the repository order (root first)."""
    if last is None:
        return False
    return folder_id is None or folder_id < last


def _check_batch(values: Sequence[str], field_name: str) -> None:
    if len(values) > MAX_BATCH_IDS:
        raise ValidationFailedError(
            f"Too many {field_name}", {"reason": "too_many", "field": field_name, "max": MAX_BATCH_IDS}
        )
    if any(not value for value in values):
        raise ValidationFailedError(f"Empty value in {field_name}", {"reason": "empty_value", "field": field_name})
