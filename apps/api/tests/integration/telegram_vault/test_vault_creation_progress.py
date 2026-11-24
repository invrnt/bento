"""`VaultService.create` reports each compartment while it runs (onboarding polls `GET /vault`)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from bento.domain.errors import DomainError
from bento.domain.vault import VaultChannelRole, VaultCreationState, VaultState
from tests.integration.telegram_vault.support import make_vault_device


def test_status_reports_the_steps_while_create_runs_and_after_a_failure(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_vault_device(tmp_path, tmp_path / "cloud", "desk")
        await device.sign_in()
        transport = device.runtime.transport
        original = transport.create_vault
        seen: list[dict[str, str]] = []

        async def observed(vault_id: str, *, on_channel: Any = None) -> Any:
            def report(role: VaultChannelRole) -> None:
                on_channel(role)
                seen.append({step.value: state.value for step, state in device.vault._creation.steps})  # noqa: SLF001

            layout = await original(vault_id, on_channel=report)
            mid = await device.vault.status()  # answered from memory while create runs
            assert mid.state == VaultState.NO_VAULT and mid.creation is not None
            assert mid.creation.state == VaultCreationState.RUNNING
            return layout

        transport.create_vault = observed  # type: ignore[method-assign]
        created = await device.vault.create()
        assert created.status.creation is not None and created.status.creation.state == VaultCreationState.DONE
        assert seen[0]["files"] == "done" and seen[0]["sync"] == "running"
        assert seen[-1]["inbox"] == "done" and seen[-1]["header"] == "running"
        assert (await device.vault.status()).creation.state == VaultCreationState.DONE  # type: ignore[union-attr]

        second = make_vault_device(tmp_path, tmp_path / "cloud-2", "laptop")
        await second.sign_in()

        async def broken(vault_id: str, *, on_channel: Any = None) -> Any:
            on_channel(VaultChannelRole.FILES)
            raise DomainError("telegram_network", "Telegram could not be reached")

        second.runtime.transport.create_vault = broken  # type: ignore[method-assign]
        with pytest.raises(DomainError):
            await second.vault.create()
        failed = (await second.vault.status()).creation
        assert failed is not None and failed.state == VaultCreationState.FAILED and failed.error_code == "telegram_network"
        assert dict((step.value, state.value) for step, state in failed.steps)["sync"] == "failed"

    asyncio.run(scenario())
