"""A device whose Telegram session was closed (e.g. removed from another device) learns `device_removed` as early
as the protocol allows: from local evidence while signed out, and before `ready` after it signs in again."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from bento.domain.sync import SyncState, SyncStatus
from bento.domain.vault import VaultState
from tests.integration.telegram_vault.support import make_vault_device


class FakeSync:
    def __init__(self) -> None:
        self.last_pull_at: datetime | None = None
        self.requests = 0

    async def status(self) -> SyncStatus:
        return SyncStatus(state=SyncState.IDLE, last_pull_at=self.last_pull_at)

    async def request_sync(self) -> None:
        self.requests += 1


def test_signed_in_again_the_vault_waits_for_a_pull_before_reporting_ready(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_vault_device(tmp_path, tmp_path / "cloud", "phone")
        await device.sign_in()
        await device.vault.create()
        sync = FakeSync()
        device.vault._sync = lambda: sync  # noqa: SLF001 - the API process wires the sync status provider here
        sync.last_pull_at = device.clock.now()
        assert (await device.vault.status()).state == VaultState.READY

        await device.runtime.account.log_out()  # the session is gone (closed from another device, or logged out)
        device.vault.invalidate()
        device.clock.advance(seconds=5)
        lost = await device.vault.status()
        assert (lost.state, lost.reason) == (VaultState.SIGNED_OUT, "session_closed")

        await device.sign_in()
        device.vault.invalidate()
        assert (await device.vault.status()).state == VaultState.BOOTSTRAPPING  # not `ready` before a pull
        assert sync.requests >= 1
        device.clock.advance(seconds=5)
        sync.last_pull_at = device.clock.now()  # the pull ran (and found no removal)
        assert (await device.vault.status()).state == VaultState.READY
        assert (await device.vault.status()).state == VaultState.READY  # the marker is cleared

    asyncio.run(scenario())


def test_signed_out_device_reports_device_removed_from_its_registry_row(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_vault_device(tmp_path, tmp_path / "cloud", "phone")
        await device.sign_in()
        await device.vault.create()
        identity = await device.vault.device_identity()
        row = await device.devices.get(identity.device_id)
        assert row is not None
        await device.devices.save(replace(row, removed_at=device.clock.now()))  # applied from a peer's removal op

        await device.runtime.account.log_out()
        device.vault.invalidate()
        status = await device.vault.status()
        assert (status.state, status.reason) == (VaultState.SIGNED_OUT, "device_removed")

    asyncio.run(scenario())
