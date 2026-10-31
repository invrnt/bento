"""Two devices of one account converge through the encrypted Sync channel of the fake cloud."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bento.application.drive import (
    CreateFolderCommand,
    MoveAssetCommand,
    MoveFolderCommand,
    RenameFolderCommand,
    UpdateAssetCommand,
)
from bento.application.photos import AddAlbumAssetCommand, CreateAlbumCommand
from bento.domain.sync import SyncMessageKind
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AssetModel, FolderModel, SyncPurgedModel
from tests.integration.sync.support import (
    SyncClock,
    SyncDevice,
    create_vault,
    join_vault,
    make_cloud_device,
    synced_state,
)


@pytest.fixture
def pair(tmp_path: Path) -> tuple[SyncDevice, SyncDevice]:
    clock = SyncClock()
    cloud = tmp_path / "cloud"
    first = make_cloud_device(tmp_path, cloud, "laptop", clock)
    second = make_cloud_device(tmp_path, cloud, "desktop", clock)

    async def setup() -> None:
        await create_vault(first)
        await join_vault(second, first)
        await first.sync()
        await second.sync()

    asyncio.run(setup())
    return first, second


async def exchange(*devices: SyncDevice) -> None:
    for device in devices:
        await device.push()
    for device in devices:
        await device.pull()


async def sync_messages(device: SyncDevice, kind: SyncMessageKind) -> list[int]:
    context = await device.context()
    refs = await device.runtime.transport.list_sync_messages(context.layout, after_message_id=0, limit=1000)
    return [ref.message_id for ref in refs if ref.kind == kind]


def test_create_rename_move_favorite_album_converge_both_directions(pair: tuple[SyncDevice, SyncDevice]) -> None:
    first, second = pair

    async def scenario() -> None:
        docs = await first.drive.create_folder(CreateFolderCommand(name="Documentos"))
        trips = await first.drive.create_folder(CreateFolderCommand(name="Viajes"))
        await first.add_asset("asset_beach", filename="playa.jpg", folder_id=trips.id)
        album = await first.photos.create_album(CreateAlbumCommand(title="Verano"))
        await first.photos.add_asset_to_album(AddAlbumAssetCommand(album_id=album.id, asset_id="asset_beach"))
        await exchange(first, second)
        assert synced_state(first.factory) == synced_state(second.factory)
        assert synced_state(second.factory)["album_items"] == [(album.id, "asset_beach")]

        first.clock.advance()
        await second.drive.rename_folder(RenameFolderCommand(folder_id=docs.id, name="Papeles"))
        await second.drive.move_folder(MoveFolderCommand(folder_id=docs.id, parent_id=trips.id))
        await second.photos.toggle_favorite("asset_beach")
        await second.drive.rename_asset(UpdateAssetCommand(asset_id="asset_beach", filename="playa-2026.jpg"))
        await second.drive.move_asset(MoveAssetCommand(asset_id="asset_beach", folder_id=None))
        await second.add_asset("asset_cat", filename="gato.jpg")
        await second.photos.add_asset_to_album(AddAlbumAssetCommand(album_id=album.id, asset_id="asset_cat"))
        await second.photos.remove_asset_from_album(AddAlbumAssetCommand(album_id=album.id, asset_id="asset_beach"))
        await exchange(second, first)

        state = synced_state(first.factory)
        assert state == synced_state(second.factory)
        assert state["folders"][docs.id][:2] == ("Papeles", trips.id)
        beach = state["assets"]["asset_beach"]
        assert (beach[2], beach[3], beach[10]) == (None, "playa-2026.jpg", True)
        assert state["album_items"] == [(album.id, "asset_cat")]

    asyncio.run(scenario())


def test_interleaved_concurrent_edits_merge_per_field_with_the_newest_clock_winning(
    pair: tuple[SyncDevice, SyncDevice],
) -> None:
    first, second = pair

    async def scenario() -> None:
        await first.add_asset("asset_x", filename="x.jpg")
        folder = await first.drive.create_folder(CreateFolderCommand(name="Inicio"))
        await exchange(first, second)

        first.clock.advance()
        await first.drive.rename_asset(UpdateAssetCommand(asset_id="asset_x", filename="from-laptop.jpg"))
        await first.drive.rename_folder(RenameFolderCommand(folder_id=folder.id, name="Laptop"))
        first.clock.advance()
        await second.drive.rename_asset(UpdateAssetCommand(asset_id="asset_x", filename="from-desktop.jpg"))
        await second.photos.toggle_favorite("asset_x")
        first.clock.advance()
        await first.drive.move_asset(MoveAssetCommand(asset_id="asset_x", folder_id=folder.id))
        await exchange(first, second)
        await exchange(second, first)

        state = synced_state(first.factory)
        assert state == synced_state(second.factory)
        asset = state["assets"]["asset_x"]
        assert (asset[2], asset[3], asset[10]) == (folder.id, "from-desktop.jpg", True)
        assert state["folders"][folder.id][0] == "Laptop"

    asyncio.run(scenario())


def test_delete_versus_rename_restore_after_delete_and_terminal_purge(pair: tuple[SyncDevice, SyncDevice]) -> None:
    first, second = pair

    async def scenario() -> None:
        await first.add_asset("asset_doc", filename="doc.jpg")
        await first.add_asset("asset_old", filename="old.jpg")
        await exchange(first, second)

        first.clock.advance()
        await first.drive.delete_asset("asset_doc")
        first.clock.advance()
        await second.drive.rename_asset(UpdateAssetCommand(asset_id="asset_doc", filename="renamed.jpg"))
        await exchange(first, second)
        await exchange(second, first)
        state = synced_state(first.factory)
        assert state == synced_state(second.factory)
        assert state["assets"]["asset_doc"][3] == "renamed.jpg"
        assert state["assets"]["asset_doc"][12] is not None

        first.clock.advance()
        restored = await_restore(second, "asset_doc")
        await restored
        await exchange(second, first)
        assert synced_state(first.factory)["assets"]["asset_doc"][12] is None
        assert synced_state(first.factory) == synced_state(second.factory)

        first.clock.advance()
        first.purge(AssetModel, "asset_old")
        first.clock.advance()
        await second.drive.rename_asset(UpdateAssetCommand(asset_id="asset_old", filename="late-edit.jpg"))
        await exchange(first, second)
        await exchange(second, first)
        for device in (first, second):
            state = synced_state(device.factory)
            assert "asset_old" not in state["assets"]
            assert "asset_old" not in state["blobs"] and "blob_asset_old" in state["blobs"]
            with session_scope(device.factory) as session:
                assert session.get(SyncPurgedModel, ("asset", "asset_old")) is not None
        assert synced_state(first.factory) == synced_state(second.factory)

    asyncio.run(scenario())


async def await_restore(device: SyncDevice, asset_id: str) -> None:
    with session_scope(device.factory) as session:
        row = session.get(AssetModel, asset_id)
        assert row is not None
        row.deleted_at = None


def test_concurrent_folder_moves_that_form_a_cycle_converge_without_a_cycle(pair: tuple[SyncDevice, SyncDevice]) -> None:
    first, second = pair

    async def scenario() -> None:
        left = await first.drive.create_folder(CreateFolderCommand(name="A"))
        right = await first.drive.create_folder(CreateFolderCommand(name="B"))
        await exchange(first, second)

        first.clock.advance()
        await first.drive.move_folder(MoveFolderCommand(folder_id=left.id, parent_id=right.id))
        first.clock.advance()
        await second.drive.move_folder(MoveFolderCommand(folder_id=right.id, parent_id=left.id))
        await exchange(first, second)
        await exchange(second, first)

        state = synced_state(first.factory)
        assert state == synced_state(second.factory)
        parents = {folder_id: values[1] for folder_id, values in state["folders"].items()}
        # The later move (B under A) is the one that closes the loop, so B goes back to the root everywhere.
        assert parents == {left.id: right.id, right.id: None}

    asyncio.run(scenario())


def test_large_outbox_is_split_into_several_batches(pair: tuple[SyncDevice, SyncDevice]) -> None:
    first, second = pair

    async def scenario() -> None:
        before = len(await sync_messages(first, SyncMessageKind.BATCH))
        with session_scope(first.factory) as session:
            now = first.clock.now()
            for index in range(600):
                session.add(FolderModel(id=f"folder_{index:04d}", name=f"Carpeta {index}", created_at=now, updated_at=now))
        published = await first.push()
        assert published == 600
        batches = await sync_messages(first, SyncMessageKind.BATCH)
        assert len(batches) - before == 3
        await second.pull()
        assert len(synced_state(second.factory)["folders"]) == 600
        assert synced_state(first.factory) == synced_state(second.factory)

    asyncio.run(scenario())


def test_crash_between_post_and_outbox_delete_resends_ops_that_peers_ignore(
    pair: tuple[SyncDevice, SyncDevice], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = pair

    async def scenario() -> None:
        await first.drive.create_folder(CreateFolderCommand(name="Una vez"))
        outbox = first.adapters.outbox
        original_remove = outbox.remove

        async def crash(seqs: tuple[int, ...]) -> None:
            del seqs
            raise RuntimeError("process killed")

        monkeypatch.setattr(outbox, "remove", crash)
        with pytest.raises(RuntimeError):
            await first.push()
        monkeypatch.setattr(outbox, "remove", original_remove)
        assert (await outbox.backlog()).count == 1

        await first.push()
        assert (await outbox.backlog()).count == 0
        await second.pull()
        assert len(await sync_messages(first, SyncMessageKind.BATCH)) >= 2
        state = synced_state(second.factory)
        assert [values[0] for values in state["folders"].values()] == ["Una vez"]
        assert state == synced_state(first.factory)

    asyncio.run(scenario())


def test_hold_rule_publishes_assets_only_with_their_remote_original(pair: tuple[SyncDevice, SyncDevice]) -> None:
    first, second = pair

    async def scenario() -> None:
        await first.add_asset("asset_pending", filename="pendiente.jpg", remote=False)
        await first.store_local_original("asset_pending")
        album = await first.photos.create_album(CreateAlbumCommand(title="Álbum"))
        await first.photos.add_asset_to_album(AddAlbumAssetCommand(album_id=album.id, asset_id="asset_pending"))
        await exchange(first, second)
        state = synced_state(second.factory)
        assert "asset_pending" not in state["assets"]
        assert state["album_items"] == [] and album.id in state["albums"]
        assert (await first.adapters.outbox.backlog()).count == 2  # asset upsert + album item, both held

        first.clock.advance()
        await first.store_remote_original("asset_pending")  # local ref replaced by the remote one
        await exchange(first, second)
        state = synced_state(second.factory)
        assert "asset_pending" in state["assets"] and "blob_asset_pending" in state["blobs"]
        assert state["album_items"] == [(album.id, "asset_pending")]
        assert (await first.adapters.outbox.backlog()).count == 0
        assert synced_state(first.factory) == state

    asyncio.run(scenario())


def test_initial_publish_sends_existing_local_library_once(tmp_path: Path) -> None:
    clock = SyncClock()
    cloud = tmp_path / "cloud"
    first = make_cloud_device(tmp_path, cloud, "laptop", clock)
    second = make_cloud_device(tmp_path, cloud, "desktop", clock)

    async def scenario() -> None:
        folder = await first.drive.create_folder(CreateFolderCommand(name="Antes del vault"))
        await first.add_asset("asset_local_era", folder_id=folder.id)
        assert (await first.adapters.outbox.backlog()).count == 0  # capture is off before the vault is ready

        await create_vault(first)
        await first.sync()
        await join_vault(second, first)
        await second.sync()
        assert synced_state(first.factory) == synced_state(second.factory)
        assert folder.id in synced_state(second.factory)["folders"]

        batches = len(await sync_messages(first, SyncMessageKind.BATCH))
        await first.sync()
        assert len(await sync_messages(first, SyncMessageKind.BATCH)) == batches

    asyncio.run(scenario())


def test_snapshot_bootstrap_of_a_third_device_equals_the_others(tmp_path: Path) -> None:
    clock = SyncClock()
    cloud = tmp_path / "cloud"
    first = make_cloud_device(tmp_path, cloud, "laptop", clock)
    second = make_cloud_device(tmp_path, cloud, "desktop", clock)
    third = make_cloud_device(tmp_path, cloud, "tablet", clock)

    async def scenario() -> None:
        await create_vault(first)
        await join_vault(second, first)
        await first.sync()
        await second.sync()
        docs = await first.drive.create_folder(CreateFolderCommand(name="Docs"))
        await first.add_asset("asset_one", folder_id=docs.id)
        await second.add_asset("asset_two")
        await exchange(first, second)
        album = await second.photos.create_album(CreateAlbumCommand(title="Viaje"))
        await second.photos.add_asset_to_album(AddAlbumAssetCommand(album_id=album.id, asset_id="asset_one"))
        await second.photos.add_asset_to_album(AddAlbumAssetCommand(album_id=album.id, asset_id="asset_two"))
        await second.photos.remove_asset_from_album(AddAlbumAssetCommand(album_id=album.id, asset_id="asset_two"))
        await first.add_asset("asset_gone")
        await exchange(first, second)
        first.purge(AssetModel, "asset_gone")
        await exchange(first, second)

        context = await first.context()
        assert await first.engine.maybe_snapshot(context, force=True)
        header = await first.vault.read_header()
        assert header is not None and header.snapshot is not None

        # Edits after the snapshot reach the new device through the tail.
        clock.advance()
        await second.drive.rename_folder(RenameFolderCommand(folder_id=docs.id, name="Docs 2026"))
        await second.push()

        await join_vault(third, first)
        await third.sync()
        assert await third.adapters.state.get_value("bootstrap") is None
        await first.pull()
        assert synced_state(third.factory) == synced_state(first.factory) == synced_state(second.factory)
        assert synced_state(third.factory)["folders"][docs.id][0] == "Docs 2026"
        with session_scope(third.factory) as session:
            assert session.get(SyncPurgedModel, ("asset", "asset_gone")) is not None

        clock.advance()
        await third.drive.rename_asset(UpdateAssetCommand(asset_id="asset_two", filename="desde-tablet.jpg"))
        await exchange(third, first, second)
        assert synced_state(first.factory)["assets"]["asset_two"][3] == "desde-tablet.jpg"
        assert synced_state(second.factory) == synced_state(third.factory)

    asyncio.run(scenario())


def test_idempotent_reapplication_of_a_batch(pair: tuple[SyncDevice, SyncDevice]) -> None:
    first, second = pair

    async def scenario() -> None:
        await first.drive.create_folder(CreateFolderCommand(name="Uno"))
        await first.push()
        await second.pull()
        state = synced_state(second.factory)
        # Forget the cursor and the applied-batch record: re-applying changes nothing.
        await second.adapters.state.set_value("last_applied_message_id", "0")
        await second.pull()
        assert synced_state(second.factory) == state

    asyncio.run(scenario())


def test_keys_grant_updates_the_keyring_and_old_epoch_batches_after_rotation_are_rejected(
    pair: tuple[SyncDevice, SyncDevice],
) -> None:
    first, second = pair

    async def scenario() -> None:
        from bento.application.sync.keys import build_keys_message
        from bento.domain.security import SealPurpose
        from bento.domain.sync import SyncBatch
        from tests.integration.sync.support import CRYPTO

        await first.register()
        await first.push()
        await second.pull()
        context = await first.context()
        old_keyring = context.keyring
        rotated = CRYPTO.rotate_keyring(old_keyring)
        message = build_keys_message(
            CRYPTO, first.vault.identity, rotated, {second.device_id: second.vault.identity.public_key},
            removed_device_ids=["dev_removed"],
        )
        await first.runtime.transport.post_sync_document(context.layout, SyncMessageKind.KEYS, message)
        await first.vault.update_keyring(rotated)

        # A removed device still holding epoch 1 posts after the rotation: rejected by the floor.
        stale = SyncBatch.from_dict(
            {"bento": "sync-batch", "v": 1, "batch": "stale-batch", "device": "dev_removed", "ops": [
                {"op": "op-stale", "hlc": "9999999999999999-000000-dev_removed", "device": "dev_removed",
                 "entity": "folder", "id": "folder_evil", "kind": "upsert", "fields": {"name": "evil"}}
            ]}
        )
        envelope = CRYPTO.seal_json(old_keyring, SealPurpose.SYNC, stale.to_dict(), aad=context.layout.vault_id.encode())
        await first.runtime.transport.post_sync_document(context.layout, SyncMessageKind.BATCH, envelope)

        await first.drive.create_folder(CreateFolderCommand(name="Nueva época"))
        await first.push()
        await second.pull()

        assert second.vault.keyring is not None and second.vault.keyring.current_epoch == 2
        assert set(second.vault.keyring.keys) == {1, 2}
        state = synced_state(second.factory)
        assert "folder_evil" not in state["folders"]
        assert "Nueva época" in [values[0] for values in state["folders"].values()]
        floor = await second.adapters.state.get_value("epoch_floor")
        assert floor is not None and '"epoch":2' in floor

    asyncio.run(scenario())
