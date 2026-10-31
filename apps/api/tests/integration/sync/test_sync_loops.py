"""Two real sync loops running concurrently converge through activity wake-ups and the "sync now" marker."""

from __future__ import annotations

import asyncio
from pathlib import Path

from bento.application.drive import CreateFolderCommand, RenameFolderCommand
from bento.application.sync import SyncLoop, SyncLoopPolicy, SyncPolicy, SyncStatusService
from bento.domain.sync import SyncState
from tests.integration.sync.support import (
    SyncClock,
    SyncDevice,
    create_vault,
    join_vault,
    make_cloud_device,
    synced_state,
)


def sync_loop(device: SyncDevice) -> SyncLoop:
    return SyncLoop(
        engine=device.engine,
        vault=device.vault,
        transport=device.runtime.transport,
        state=device.adapters.state,
        clock=device.clock,
        policy=SyncLoopPolicy(activity_timeout_seconds=5.0, tick_seconds=0.02),
    )


async def eventually(condition, timeout: float = 10.0) -> None:  # type: ignore[no-untyped-def]
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "devices did not converge"
        await asyncio.sleep(0.02)


def test_two_running_loops_converge_and_report_status(tmp_path: Path) -> None:
    clock = SyncClock()
    cloud = tmp_path / "cloud"
    policy = SyncPolicy(post_interval_seconds=0, flush_min_age_ms=0)
    first = make_cloud_device(tmp_path, cloud, "laptop", clock, policy=policy)
    second = make_cloud_device(tmp_path, cloud, "desktop", clock, policy=policy)

    async def scenario() -> None:
        await create_vault(first)
        await join_vault(second, first)
        stop = asyncio.Event()
        tasks = [asyncio.create_task(sync_loop(device).run(stop)) for device in (first, second)]
        try:
            folder = await first.drive.create_folder(CreateFolderCommand(name="En vivo"))
            await eventually(lambda: folder.id in synced_state(second.factory)["folders"])

            clock.advance()
            await second.drive.rename_folder(RenameFolderCommand(folder_id=folder.id, name="Renombrada"))
            await SyncStatusService(enabled=True, state=second.adapters.state, outbox=second.adapters.outbox, clock=clock).request_sync()
            await eventually(lambda: synced_state(first.factory)["folders"][folder.id][0] == "Renombrada")
            await eventually(lambda: synced_state(first.factory) == synced_state(second.factory))

            status = SyncStatusService(enabled=True, state=first.adapters.state, outbox=first.adapters.outbox, clock=clock)
            report = await status.status()
            assert report.state in {SyncState.IDLE, SyncState.SYNCING}
            assert report.pending_ops == 0 and report.last_pull_at is not None and report.last_push_at is not None
        finally:
            stop.set()
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)

    asyncio.run(scenario())
