from __future__ import annotations

import asyncio

import pytest

from bento.adapters.repositories import SQLiteAlbumRepository, SQLiteAssetRepository, SQLiteFolderRepository
from bento.domain.drive import Folder
from bento.domain.errors import InvalidFolderMoveError
from bento.domain.photos import Album

from tests.integration.db.support import NOW, migrated_session_factory, make_asset


def test_asset_repository_crud_and_logical_delete(tmp_path) -> None:
    async def scenario() -> None:
        assets = SQLiteAssetRepository(migrated_session_factory(tmp_path))
        asset = make_asset()

        await assets.add(asset)
        assert await assets.get(asset.id) == asset
        assert await assets.get_by_sha256(asset.metadata.sha256) == asset

        renamed = asset.rename("renamed.pdf", NOW)
        await assets.save(renamed)
        persisted = await assets.get(asset.id)
        assert persisted is not None
        assert persisted.filename == "renamed.pdf"

        await assets.save(renamed.mark_deleted(NOW))
        assert await assets.get(asset.id) is None
        assert await assets.get_by_sha256(asset.metadata.sha256) is None

    asyncio.run(scenario())


def test_folder_repository_persists_tree_for_cycle_checks(tmp_path) -> None:
    async def scenario() -> None:
        folders = SQLiteFolderRepository(migrated_session_factory(tmp_path))
        root = Folder(id="folder_root", name="Root", parent_id=None, created_at=NOW, updated_at=NOW)
        child = Folder(id="folder_child", name="Child", parent_id=root.id, created_at=NOW, updated_at=NOW)
        grandchild = Folder(
            id="folder_grandchild",
            name="Grandchild",
            parent_id=child.id,
            created_at=NOW,
            updated_at=NOW,
        )

        await folders.add(root)
        await folders.add(child)
        await folders.add(grandchild)

        assert await folders.descendant_ids(root.id) == {child.id, grandchild.id}
        with pytest.raises(InvalidFolderMoveError):
            root.move_to(grandchild.id, await folders.descendant_ids(root.id), NOW)

        await folders.save(child.mark_deleted(NOW))
        assert await folders.get(child.id) is None
        assert await folders.descendant_ids(root.id) == set()

    asyncio.run(scenario())


def test_folder_list_items_combines_live_folders_and_assets(tmp_path) -> None:
    async def scenario() -> None:
        factory = migrated_session_factory(tmp_path)
        folders = SQLiteFolderRepository(factory)
        assets = SQLiteAssetRepository(factory)
        folder = Folder(id="folder_root", name="Root", parent_id=None, created_at=NOW, updated_at=NOW)
        asset = make_asset(folder_id=folder.id)

        await folders.add(folder)
        await assets.add(asset)

        items, next_cursor = await folders.list_items(folder_id=folder.id)
        assert next_cursor is None
        assert [item.id for item in items] == [asset.id]

        await assets.save(asset.mark_deleted(NOW))
        items, _ = await folders.list_items(folder_id=folder.id)
        assert items == ()

    asyncio.run(scenario())


def test_album_repository_crud_and_membership(tmp_path) -> None:
    async def scenario() -> None:
        factory = migrated_session_factory(tmp_path)
        assets = SQLiteAssetRepository(factory)
        albums = SQLiteAlbumRepository(factory)
        asset = make_asset()
        album = Album(
            id="album_1",
            title="Trips",
            asset_ids=frozenset(),
            created_at=NOW,
            updated_at=NOW,
        )

        await assets.add(asset)
        await albums.add(album)
        updated = album.add_asset(asset.id, NOW)
        await albums.save(updated)

        assert await albums.get(album.id) == updated
        listed, next_cursor = await albums.list()
        assert next_cursor is None
        assert listed == (updated,)

        await albums.save(updated.mark_deleted(NOW))
        assert await albums.get(album.id) is None

    asyncio.run(scenario())


def test_album_repository_adds_an_album_created_with_items(tmp_path) -> None:
    """The album row must reach SQLite before its `album_assets` rows (foreign keys are on)."""

    async def scenario() -> None:
        factory = migrated_session_factory(tmp_path)
        assets = SQLiteAssetRepository(factory)
        albums = SQLiteAlbumRepository(factory)
        first = make_asset("asset_1", sha256="a" * 64)
        second = make_asset("asset_2", sha256="b" * 64)
        await assets.add(first)
        await assets.add(second)
        album = Album(
            id="album_new",
            title="Viaje",
            asset_ids=frozenset({first.id, second.id}),
            created_at=NOW,
            updated_at=NOW,
        )

        await albums.add(album)
        assert await albums.get(album.id) == album

        unsaved = Album(id="album_saved", title="Solo save", asset_ids=frozenset({first.id}), created_at=NOW, updated_at=NOW)
        await albums.save(unsaved)
        assert await albums.get(unsaved.id) == unsaved

    asyncio.run(scenario())
