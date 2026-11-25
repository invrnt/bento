"""`DrivePathUseCases` against in-memory fakes (no SQLite)."""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from bento.application.drive import DriveUseCases
from bento.application.drive_paths import DrivePathUseCases, DriveTreeNode
from bento.domain.assets import Asset, AssetKind, AssetMetadata, AssetMode, ProcessingState
from bento.domain.drive import Folder
from bento.domain.drive_paths import DriveIdRef, PathAmbiguousError, PathNotFoundError, parse_drive_path
from bento.domain.errors import ValidationFailedError

T0 = datetime(2026, 1, 1, tzinfo=UTC)


class FakeFolders:
    def __init__(self) -> None:
        self.rows: dict[str, Folder] = {}
        self.list_children_calls = 0
        self._ids = itertools.count(1)

    async def next_id(self) -> str:
        return f"folder_new{next(self._ids):03d}"

    async def get(self, folder_id: str) -> Folder | None:
        folder = self.rows.get(folder_id)
        return folder if folder is not None and not folder.is_deleted else None

    async def add(self, folder: Folder) -> None:
        self.rows[folder.id] = folder

    async def save(self, folder: Folder) -> None:
        self.rows[folder.id] = folder

    async def get_many(self, folder_ids: Sequence[str]) -> dict[str, Folder]:
        return {fid: f for fid in folder_ids if (f := self.rows.get(fid)) is not None and not f.is_deleted}

    async def list_children(self, parent_ids: Sequence[str | None]) -> tuple[Folder, ...]:
        self.list_children_calls += 1
        wanted = set(parent_ids)
        return tuple(f for f in self.rows.values() if f.parent_id in wanted and not f.is_deleted)

    async def ids_with_children(self, folder_ids: Sequence[str], *, include_assets: bool) -> set[str]:
        raise AssertionError("bound by FakeAssets")


class FakeAssets:
    def __init__(self) -> None:
        self.rows: dict[str, Asset] = {}

    async def get(self, asset_id: str) -> Asset | None:
        asset = self.rows.get(asset_id)
        return asset if asset is not None and not asset.is_deleted else None

    async def get_many(self, asset_ids: Sequence[str]) -> dict[str, Asset]:
        return {aid: a for aid in asset_ids if (a := self.rows.get(aid)) is not None and not a.is_deleted}

    async def get_many_by_sha256(self, sha256s: Sequence[str]) -> dict[str, Asset]:
        found: dict[str, Asset] = {}
        for asset in sorted(self._live(), key=lambda a: (a.created_at, a.id), reverse=True):
            if asset.metadata.sha256 in sha256s:
                found.setdefault(asset.metadata.sha256, asset)
        return found

    async def list_in_folders(self, folder_ids: Sequence[str | None], *, limit: int | None = None) -> tuple[Asset, ...]:
        wanted = set(folder_ids)
        rows = sorted(
            (a for a in self._live() if a.folder_id in wanted),
            key=lambda a: (a.folder_id is not None, a.folder_id or "", a.filename, a.id),
        )
        return tuple(rows if limit is None else rows[:limit])

    def _live(self) -> list[Asset]:
        return [a for a in self.rows.values() if not a.is_deleted]


class Manifest:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def append(self, **event: Any) -> None:
        self.events.append(event)


class Clock:
    def __init__(self) -> None:
        self.current = T0 + timedelta(days=1)

    def now(self) -> datetime:
        self.current += timedelta(seconds=1)
        return self.current


class World:
    def __init__(self) -> None:
        self.folders = FakeFolders()
        self.assets = FakeAssets()
        self.manifest = Manifest()
        drive = DriveUseCases(assets=self.assets, folders=self.folders, manifest=self.manifest, clock=Clock())  # type: ignore[arg-type]

        async def ids_with_children(folder_ids: Sequence[str], *, include_assets: bool) -> set[str]:
            ids = set(folder_ids)
            found = {f.parent_id for f in self.folders.rows.values() if f.parent_id in ids and not f.is_deleted}
            if include_assets:
                found |= {a.folder_id for a in self.assets._live() if a.folder_id in ids}
            return {item for item in found if item is not None}

        self.folders.ids_with_children = ids_with_children  # type: ignore[method-assign]
        self.paths = DrivePathUseCases(folders=self.folders, assets=self.assets, drive=drive)

    def folder(self, folder_id: str, name: str, parent: str | None = None, *, minutes: int = 0) -> Folder:
        at = T0 + timedelta(minutes=minutes)
        folder = Folder(id=folder_id, name=name, parent_id=parent, created_at=at, updated_at=at)
        self.folders.rows[folder_id] = folder
        return folder

    def asset(self, asset_id: str, name: str, folder: str | None = None, *, sha: str = "a" * 64, minutes: int = 0) -> Asset:
        at = T0 + timedelta(minutes=minutes)
        asset = Asset(
            id=asset_id,
            kind=AssetKind.DOCUMENT,
            mode=AssetMode.DRIVE,
            folder_id=folder,
            filename=name,
            metadata=AssetMetadata(original_filename=name, mime_type="text/plain", size_bytes=7, sha256=sha),
            processing_state=ProcessingState.INDEXED,
            favorite=False,
            created_at=at,
            updated_at=at,
        )
        self.assets.rows[asset_id] = asset
        return asset


def run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture
def world() -> World:
    w = World()
    w.folder("folder_a", "Docs")
    w.folder("folder_b", "2026", "folder_a")
    w.asset("asset_1", "nota.txt", "folder_b", sha="1" * 64)
    w.asset("asset_root", "raiz.txt", None, sha="2" * 64)
    return w


def test_resolve_root_folder_and_asset(world: World) -> None:
    root = run(world.paths.resolve(parse_drive_path("/")))
    assert root.kind == "root" and root.path == "/" and root.folder is None and root.breadcrumbs == ()

    folder = run(world.paths.resolve(parse_drive_path("/Docs/2026/")))
    assert folder.kind == "folder" and folder.folder.id == "folder_b"
    assert [f.id for f in folder.breadcrumbs] == ["folder_a", "folder_b"]

    asset = run(world.paths.resolve(parse_drive_path("Docs/2026/nota.txt")))
    assert asset.kind == "asset" and asset.asset.id == "asset_1" and asset.path == "/Docs/2026/nota.txt"
    assert [f.id for f in asset.breadcrumbs] == ["folder_a", "folder_b"]


def test_resolve_by_id(world: World) -> None:
    asset = run(world.paths.resolve(DriveIdRef("asset_1")))
    assert asset.path == "/Docs/2026/nota.txt" and [f.name for f in asset.breadcrumbs] == ["Docs", "2026"]
    folder = run(world.paths.resolve(DriveIdRef("folder_b")))
    assert folder.kind == "folder" and folder.path == "/Docs/2026"
    root_asset = run(world.paths.resolve(DriveIdRef("asset_root")))
    assert root_asset.path == "/raiz.txt" and root_asset.breadcrumbs == ()
    with pytest.raises(PathNotFoundError) as caught:
        run(world.paths.resolve(DriveIdRef("nope")))
    assert caught.value.details == {"path": "id:nope", "missing_from": 0}


def test_not_found_reports_first_missing_segment(world: World) -> None:
    with pytest.raises(PathNotFoundError) as caught:
        run(world.paths.resolve(parse_drive_path("/Docs/2027/x")))
    assert caught.value.details == {"path": "/Docs/2027/x", "missing_from": 1}
    with pytest.raises(PathNotFoundError):  # trailing slash: only folders match
        run(world.paths.resolve(parse_drive_path("/Docs/2026/nota.txt/")))


def test_trashed_items_never_match(world: World) -> None:
    world.folders.rows["folder_b"] = world.folders.rows["folder_b"].mark_deleted(T0)
    with pytest.raises(PathNotFoundError):
        run(world.paths.resolve(parse_drive_path("/Docs/2026")))
    with pytest.raises(PathNotFoundError):  # asset whose folder is trashed is not addressable
        run(world.paths.resolve(DriveIdRef("asset_1")))
    world.assets.rows["asset_root"] = world.assets.rows["asset_root"].mark_deleted(T0)
    with pytest.raises(PathNotFoundError):
        run(world.paths.resolve(parse_drive_path("/raiz.txt")))


def test_ambiguity(world: World) -> None:
    world.folder("folder_dup", "Docs", minutes=5)
    with pytest.raises(PathAmbiguousError) as caught:
        run(world.paths.resolve(parse_drive_path("/Docs/2026")))
    details = caught.value.details
    assert details["path"] == "/Docs/2026"
    assert [c["id"] for c in details["candidates"]] == ["folder_a", "folder_dup"]
    assert {c["path"] for c in details["candidates"]} == {"/Docs"}


def test_folder_and_asset_with_same_name(world: World) -> None:
    world.asset("asset_same", "2026", "folder_a")
    with pytest.raises(PathAmbiguousError) as caught:
        run(world.paths.resolve(parse_drive_path("/Docs/2026")))
    assert {c["kind"] for c in caught.value.details["candidates"]} == {"folder", "asset"}
    folder = run(world.paths.resolve(parse_drive_path("/Docs/2026/")))
    assert folder.folder.id == "folder_b"
    # Only the last segment can be an asset.
    assert run(world.paths.resolve(parse_drive_path("/Docs/2026/nota.txt"))).asset.id == "asset_1"


def test_nfc_comparison(world: World) -> None:
    world.folder("folder_nfd", "Café")
    assert run(world.paths.resolve(parse_drive_path("/Café"))).folder.id == "folder_nfd"


def test_ensure_creates_reuses_oldest_and_is_idempotent(world: World) -> None:
    world.folder("folder_dup", "Docs", minutes=-5)  # older duplicate wins
    result = run(world.paths.ensure_folder(parse_drive_path("/Docs/Nuevos/Hondo")))
    assert result.path == "/Docs/Nuevos/Hondo"
    assert len(result.created) == 2
    created = [world.folders.rows[fid] for fid in result.created]
    assert created[0].parent_id == "folder_dup" and created[0].name == "Nuevos"
    assert created[1].parent_id == created[0].id and result.folder == created[1]
    assert [e["entity_id"] for e in world.manifest.events] == list(result.created)  # same capture as the UI path

    again = run(world.paths.ensure_folder(parse_drive_path("/Docs/Nuevos/Hondo/")))
    assert again.created == () and again.folder.id == result.folder.id

    # The oldest "Docs" wins even though only the newer one contains "2026".
    other_branch = run(world.paths.ensure_folder(parse_drive_path("/Docs/2026")))
    assert len(other_branch.created) == 1 and other_branch.folder.parent_id == "folder_dup"

    root = run(world.paths.ensure_folder(parse_drive_path("/")))
    assert root.folder is None and root.path == "/" and root.created == ()


def test_ensure_concurrent_calls_do_not_duplicate(world: World) -> None:
    async def both() -> None:
        await asyncio.gather(*(world.paths.ensure_folder(parse_drive_path("/X/Y")) for _ in range(4)))

    run(both())
    assert sorted(f.name for f in world.folders.rows.values() if f.name in {"X", "Y"}) == ["X", "Y"]


def test_ensure_by_id(world: World) -> None:
    assert run(world.paths.ensure_folder(DriveIdRef("folder_b"))).path == "/Docs/2026"
    with pytest.raises(ValidationFailedError):
        run(world.paths.ensure_folder(DriveIdRef("asset_1")))


def _shape(node: DriveTreeNode) -> Any:
    if node.children is None:
        return (node.name, "more") if node.has_more else node.name
    return (node.name, [_shape(child) for child in node.children], node.has_more)


def test_tree_depth_ordering_and_has_more(world: World) -> None:
    world.folder("folder_c", "alpha", None)
    world.asset("asset_z", "Zeta.txt", None)
    world.asset("asset_b", "beta.txt", None)
    world.folder("folder_d", "deep", "folder_b")
    result = run(world.paths.tree(parse_drive_path("/"), depth=2))
    assert not result.truncated
    assert _shape(result.root) == (
        "/",
        [("alpha", [], False), ("Docs", [("2026", "more")], False), ("beta.txt"), ("raiz.txt"), ("Zeta.txt")],
        False,
    )
    assert result.nodes == 7
    full = run(world.paths.tree(parse_drive_path("/Docs"), depth=5))
    assert _shape(full.root) == ("Docs", [("2026", [("deep", [], False), "nota.txt"], False)], False)
    assert full.root.children[0].children[1].path == "/Docs/2026/nota.txt"

    folders_only = run(world.paths.tree(parse_drive_path("/"), depth=1, include_assets=False))
    assert _shape(folders_only.root) == ("/", [("alpha", [], False), ("Docs", "more")], False)


def test_tree_truncation(world: World) -> None:
    for index in range(6):
        world.asset(f"asset_t{index}", f"t{index}.txt", None)
    result = run(world.paths.tree(parse_drive_path("/"), depth=3, max_nodes=4))
    assert result.truncated and result.nodes == 4
    assert result.root.has_more
    assert [c.name for c in result.root.children] == ["Docs", "raiz.txt", "t0.txt"]
    only_root = run(world.paths.tree(parse_drive_path("/"), max_nodes=1))
    assert only_root.truncated and only_root.nodes == 1 and only_root.root.has_more and only_root.root.children is None


def test_tree_of_asset_and_limits(world: World) -> None:
    leaf = run(world.paths.tree(DriveIdRef("asset_1")))
    assert leaf.nodes == 1 and leaf.root.kind == "asset" and leaf.root.children is None
    for kwargs in ({"depth": 0}, {"depth": 21}, {"max_nodes": 0}, {"max_nodes": 10_001}):
        with pytest.raises(ValidationFailedError):
            run(world.paths.tree(parse_drive_path("/"), **kwargs))


def test_tree_queries_are_per_level_not_per_folder(world: World) -> None:
    for index in range(30):
        world.folder(f"folder_w{index}", f"w{index}", "folder_a")
    world.folders.list_children_calls = 0
    run(world.paths.tree(parse_drive_path("/"), depth=3))
    assert world.folders.list_children_calls <= 4


def test_paths_for_ids(world: World) -> None:
    world.folder("folder_trash", "Old")
    world.folders.rows["folder_trash"] = world.folders.rows["folder_trash"].mark_deleted(T0)
    world.folder("folder_slash", "a/b", "folder_a")
    result = run(world.paths.paths_for_ids(["asset_1", "folder_b", "asset_root", "folder_trash", "nope", "folder_slash"]))
    assert result.paths == {
        "asset_1": "/Docs/2026/nota.txt",
        "folder_b": "/Docs/2026",
        "asset_root": "/raiz.txt",
        "folder_slash": "/Docs/a\\/b",
    }
    assert result.missing == ("folder_trash", "nope")
    with pytest.raises(ValidationFailedError):
        run(world.paths.paths_for_ids(["x"] * 501))


def test_lookup_sha256(world: World) -> None:
    world.asset("asset_newer", "copia.txt", None, sha="1" * 64, minutes=10)
    matches = run(world.paths.lookup_sha256(["1" * 64, "2" * 64, "f" * 64]))
    assert set(matches) == {"1" * 64, "2" * 64}
    assert matches["1" * 64].asset.id == "asset_newer" and matches["1" * 64].path == "/copia.txt"
    assert matches["2" * 64].path == "/raiz.txt"
    for bad in (["A" * 64], ["1" * 63], ["g" * 64]):
        with pytest.raises(ValidationFailedError):
            run(world.paths.lookup_sha256(bad))
    with pytest.raises(ValidationFailedError):
        run(world.paths.lookup_sha256(["1" * 64] * 501))


def test_assets_in_trashed_folder_are_not_looked_up(world: World) -> None:
    world.folders.rows["folder_a"] = replace(world.folders.rows["folder_a"], deleted_at=T0)
    assert run(world.paths.lookup_sha256(["1" * 64])) == {}


def test_tree_capped_asset_query_marks_incomplete_folders() -> None:
    w = World()
    w.folder("folder_p1", "p1")
    w.folder("folder_p2", "p2")
    for index in range(3):
        w.asset(f"asset_p1_{index}", f"f{index}.txt", "folder_p1")
        w.asset(f"asset_p2_{index}", f"f{index}.txt", "folder_p2")
    result = run(w.paths.tree(parse_drive_path("/"), depth=2, max_nodes=6))
    p1, p2 = result.root.children
    assert result.truncated and result.nodes == 6
    assert [c.name for c in p1.children] == ["f0.txt", "f1.txt", "f2.txt"] and not p1.has_more
    assert p2.children == [] and p2.has_more
