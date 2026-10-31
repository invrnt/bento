from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select

from bento.application.drive import CreateFolderCommand
from bento.application.ingestion import UploadedAssetFile
from bento.domain.errors import TelegramFloodWaitError
from bento.domain.jobs import JobType
from bento.domain.storage import BlobKind
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AssetModel, BlobRefModel, CacheEntryModel, FolderModel, JobModel
from tests.integration.storage_pipeline.support import (
    JobRunner,
    RemoteSwitch,
    migrated_data_dir,
    pipeline_for,
    run,
    vault_remote_store,
)


async def _uploaded(components, tmp_path: Path, name: str, content: bytes, folder_id: str | None = None):
    source = tmp_path / "in" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(content)
    result = await components.ingestion.upload_file(
        UploadedAssetFile(source_path=source, original_filename=name, folder_id=folder_id)
    )
    await JobRunner(components).run_all()
    return result.asset, await components.blob_refs.latest_for_asset(result.asset.id, BlobKind.ORIGINAL)


def _count(components, model) -> int:  # type: ignore[no-untyped-def]
    with session_scope(components.session_factory) as session:
        return int(session.scalar(select(func.count()).select_from(model)))


def test_trash_lists_restores_and_purges_with_remote_deletion(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = await vault_remote_store(tmp_path)
        components = pipeline_for(migrated_data_dir(tmp_path), RemoteSwitch(store))
        trash = components.trash
        album = await components.drive.create_folder(CreateFolderCommand(name="Viajes"))
        nested = await components.drive.create_folder(CreateFolderCommand(name="2024", parent_id=album.id))
        loose, loose_ref = await _uploaded(components, tmp_path, "nota.txt", b"nota")
        inside, inside_ref = await _uploaded(components, tmp_path, "mapa.pdf", b"%PDF mapa", nested.id)
        local_copy = components.cache.lookup_sync(inside_ref.id)
        assert local_copy is not None

        deleted = await components.files.delete_asset(loose.id)
        await components.drive.delete_folder(album.id)
        entries, cursor = await trash.list()
        assert cursor is None
        assert [(entry.item.id, entry.item.type.value) for entry in entries] == [(album.id, "folder"), (loose.id, "asset")]
        folder_entry, asset_entry = entries
        assert folder_entry.item.size_bytes == len(b"%PDF mapa")
        assert asset_entry.item.purge_at - asset_entry.item.deleted_at == timedelta(days=30)
        assert asset_entry.item.deleted_at == deleted.deleted_at

        assert await trash.restore((loose.id, "unknown")) == 1
        assert (await components.assets.get(loose.id)) is not None
        assert [entry.item.id for entry in (await trash.list())[0]] == [album.id]

        result = await trash.purge((album.id,))
        assert result.purged == 1 and result.deferred == ()
        assert inside_ref.id in store.deleted
        assert all(not store.remote_exists(part) for part in inside_ref.parts)
        assert not local_copy.exists()
        with session_scope(components.session_factory) as session:
            assert session.get(AssetModel, inside.id) is None
            assert session.get(BlobRefModel, inside_ref.id) is None
            assert session.get(CacheEntryModel, inside_ref.id) is None
            assert session.get(FolderModel, album.id) is None and session.get(FolderModel, nested.id) is None
        assert (await trash.list())[0] == ()
        assert all(store.remote_exists(part) for part in loose_ref.parts)

    run(scenario())


def test_purge_is_deferred_while_the_vault_is_unavailable(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = await vault_remote_store(tmp_path)
        switch = RemoteSwitch(store)
        components = pipeline_for(migrated_data_dir(tmp_path), switch)
        asset, ref = await _uploaded(components, tmp_path, "a.txt", b"alpha")
        await components.files.delete_asset(asset.id)

        switch.store = None
        result = await components.trash.purge((asset.id,))
        assert (result.purged, result.deferred) == (0, (asset.id,))
        assert [entry.item.id for entry in (await components.trash.list())[0]] == [asset.id]
        with session_scope(components.session_factory) as session:
            [job] = session.scalars(select(JobModel).where(JobModel.type == JobType.TRASH_PURGE.value)).all()
            assert job.payload_json == {"ids": [asset.id]}

        switch.store = store
        store.delete_failures.append(TelegramFloodWaitError(30))
        await JobRunner(components).run_all()
        assert _count(components, AssetModel) == 1  # flood wait → retried later with backoff

        with session_scope(components.session_factory) as session:
            session.get(JobModel, job.id).run_after = None
        await JobRunner(components).run_all()
        assert _count(components, AssetModel) == 0
        assert all(not store.remote_exists(part) for part in ref.parts)

    run(scenario())


def test_retention_purges_only_expired_items_and_empty_purges_everything(tmp_path: Path) -> None:
    async def scenario() -> None:
        components = pipeline_for(migrated_data_dir(tmp_path), RemoteSwitch(None), storage_backend="local")
        old, old_ref = await _uploaded(components, tmp_path, "old.txt", b"old")
        recent, _ = await _uploaded(components, tmp_path, "recent.txt", b"recent")
        keep, _ = await _uploaded(components, tmp_path, "keep.txt", b"keep")
        old_path = components.local_resolver.resolve(old_ref)
        deleted = await components.files.delete_asset(old.id)
        await components.assets.save(replace(deleted, deleted_at=deleted.deleted_at - timedelta(days=31)))
        await components.files.delete_asset(recent.id)

        result = await components.trash.purge_expired()

        assert result.purged == 1
        assert not old_path.exists()
        assert [entry.item.id for entry in (await components.trash.list())[0]] == [recent.id]
        assert (await components.trash.empty()).purged == 1
        assert (await components.trash.list())[0] == ()
        assert await components.assets.get(keep.id) is not None

    run(scenario())


def test_purging_keeps_local_files_shared_with_another_asset(tmp_path: Path) -> None:
    async def scenario() -> None:
        components = pipeline_for(migrated_data_dir(tmp_path), RemoteSwitch(None), storage_backend="local")
        first, first_ref = await _uploaded(components, tmp_path, "a.txt", b"same bytes")
        await components.files.delete_asset(first.id)
        second, second_ref = await _uploaded(components, tmp_path, "b.txt", b"same bytes")
        assert second.id != first.id and second_ref.object_key == first_ref.object_key

        await components.trash.purge((first.id,))

        assert components.local_resolver.resolve(second_ref).read_bytes() == b"same bytes"

    run(scenario())


def test_restoring_an_item_whose_folder_is_still_trashed_moves_it_to_the_root(tmp_path: Path) -> None:
    async def scenario() -> None:
        components = pipeline_for(migrated_data_dir(tmp_path), RemoteSwitch(None), storage_backend="local")
        folder = await components.drive.create_folder(CreateFolderCommand(name="Docs"))
        child = await components.drive.create_folder(CreateFolderCommand(name="Sub", parent_id=folder.id))
        asset, _ = await _uploaded(components, tmp_path, "a.txt", b"a", child.id)
        await components.files.delete_asset(asset.id)
        await components.drive.delete_folder(child.id)
        await components.drive.delete_folder(folder.id)

        assert await components.trash.restore((asset.id, child.id)) == 2
        restored_child = await components.drive._folders.get(child.id)  # noqa: SLF001
        assert restored_child.parent_id is None
        assert (await components.assets.get(asset.id)).folder_id == child.id

    run(scenario())
