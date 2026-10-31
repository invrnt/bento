"""The storage pipeline's ORM writes (ingest, remote upload swap, trash, restore, purge) reach peers through capture."""

from __future__ import annotations

import asyncio
from pathlib import Path

from bento.application.ingestion import UploadedAssetFile
from bento.domain.jobs import JobType
from bento.domain.storage import StorageBackend
from bento.domain.sync import SyncEntity, SyncOpKind
from bento.infrastructure.settings import Settings
from bento.infrastructure.storage_pipeline import StoragePipelineComponents, build_storage_pipeline
from tests.integration.storage_pipeline.support import JobRunner, RemoteSwitch, vault_remote_store
from tests.integration.sync.support import (
    SyncClock,
    SyncDevice,
    create_vault,
    join_vault,
    make_cloud_device,
    synced_state,
)


def pipeline(device: SyncDevice, tmp_path: Path, remote: RemoteSwitch) -> StoragePipelineComponents:
    data_dir = tmp_path / f"{device.name}-data"
    (data_dir / "db").mkdir(parents=True, exist_ok=True)
    return build_storage_pipeline(
        Settings(data_dir=str(data_dir), storage_backend="fake"), remote=remote, session_factory=device.factory
    )


async def outbox_ops(device: SyncDevice) -> list[tuple[str, str]]:
    return [(entry.operation.entity.value, entry.operation.kind.value) for entry in await device.adapters.outbox.page()]


def test_remote_upload_completion_publishes_the_blob_and_releases_held_asset_ops(tmp_path: Path) -> None:
    clock = SyncClock()
    cloud = tmp_path / "cloud"
    first = make_cloud_device(tmp_path, cloud, "laptop", clock)
    second = make_cloud_device(tmp_path, cloud, "desktop", clock)

    async def scenario() -> None:
        await create_vault(first)
        await join_vault(second, first)
        await first.sync()
        await second.sync()
        components = pipeline(first, tmp_path, RemoteSwitch(await vault_remote_store(tmp_path, part_size=4096)))

        source = tmp_path / "incoming" / "factura.txt"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"factura confidencial " * 600)
        uploaded = await components.ingestion.upload_file(UploadedAssetFile(source_path=source, original_filename="factura.txt"))
        asset_id = uploaded.asset.id
        assert uploaded.blob_ref is not None and uploaded.blob_ref.backend == StorageBackend.LOCAL

        await first.push()
        await second.pull()
        assert asset_id not in synced_state(second.factory)["assets"]
        assert ("asset", "upsert") in await outbox_ops(first)  # held: no remote original yet

        assert await JobRunner(components).run_all(types={JobType.REMOTE_UPLOAD.value}) == 1
        pending = await first.adapters.outbox.page()
        blob_ops = [entry.operation for entry in pending if entry.operation.entity == SyncEntity.BLOB]
        assert len(blob_ops) == 1 and blob_ops[0].kind == SyncOpKind.UPSERT
        assert blob_ops[0].fields["asset_id"] == asset_id and blob_ops[0].fields["kind"] == "original"
        assert len(blob_ops[0].fields["parts"]) > 1

        await first.push()
        assert await first.adapters.outbox.page() == ()
        await second.pull()
        state = synced_state(second.factory)
        assert state["assets"][asset_id][3] == "factura.txt"
        [(remote_id, blob)] = [(blob_id, value) for blob_id, value in state["blobs"].items() if value[0] == asset_id]
        assert remote_id != uploaded.blob_ref.id and len(blob[7]) > 1
        assert synced_state(first.factory) == state

        clock.advance()
        await components.drive.delete_asset(asset_id)
        await first.push()
        await second.pull()
        assert synced_state(second.factory)["assets"][asset_id][12] is not None

        clock.advance()
        assert await components.trash.restore((asset_id,)) == 1
        await first.push()
        await second.pull()
        assert synced_state(second.factory)["assets"][asset_id][12] is None

        clock.advance()
        await components.drive.delete_asset(asset_id)
        await components.trash.purge((asset_id,))
        assert {"asset", "blob"} <= {entity for entity, kind in await outbox_ops(first) if kind == "purge"}
        await first.push()
        await second.pull()
        state = synced_state(second.factory)
        assert asset_id not in state["assets"] and remote_id not in state["blobs"]
        assert state == synced_state(first.factory)

    asyncio.run(scenario())
