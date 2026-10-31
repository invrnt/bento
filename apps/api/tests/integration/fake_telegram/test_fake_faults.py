from __future__ import annotations

from pathlib import Path

import pytest

from bento.adapters.fake_telegram import FakeTelegramCloud
from bento.domain.errors import TelegramAccountError, TelegramFloodWaitError
from tests.integration.fake_telegram.support import ManualClock, make_device, run, sign_in


def test_injected_faults_fail_authorized_calls_of_every_instance_until_they_expire(tmp_path: Path) -> None:
    clock = ManualClock()
    first, second = make_device(tmp_path, clock=clock, name="a"), make_device(tmp_path, clock=clock, name="b")

    async def scenario() -> None:
        await sign_in(first)
        await sign_in(second)
        layout = await first.runtime.transport.create_vault("vlt_faults")
        cloud = FakeTelegramCloud(tmp_path, clock=clock)

        cloud.inject_fault("flood_wait", seconds=42.5)
        with pytest.raises(TelegramFloodWaitError) as flood:
            await second.runtime.transport.list_sync_messages(layout, after_message_id=0)
        assert flood.value.retry_after_seconds == 43
        assert (await second.runtime.account.status()).authorized  # sign-in state stays readable

        clock.advance(43)
        assert cloud.active_fault() is None
        assert await second.runtime.transport.list_sync_messages(layout, after_message_id=0) == ()

        cloud.inject_fault("network", seconds=5)
        with pytest.raises(TelegramAccountError) as network:
            await first.runtime.transport.find_vaults()
        assert network.value.code == "telegram_network"
        cloud.clear_fault()
        assert [item.vault_id for item in await first.runtime.transport.find_vaults()] == ["vlt_faults"]

        with pytest.raises(ValueError):
            cloud.inject_fault("meteor", seconds=1)

    run(scenario())
