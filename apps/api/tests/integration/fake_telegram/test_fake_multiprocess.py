from __future__ import annotations

import multiprocessing
from pathlib import Path
from typing import Any

from bento.adapters.fake_telegram import FakeTelegramCloud
from tests.integration.fake_telegram.fake_cloud_device import VAULT_ID, guest_qr_login, sync_device
from tests.integration.fake_telegram.support import make_device, run, sign_in

POSTS = 15


def _collect(processes: list[Any], results: Any, count: int) -> list[dict[str, Any]]:
    for process in processes:
        process.start()
    collected = [results.get(timeout=60) for _ in range(count)]
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0
    return collected


def test_two_device_processes_share_one_vault_and_see_each_others_sync_messages(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    processes = [
        context.Process(target=sync_device, args=(str(tmp_path), "laptop", "desktop", POSTS, results)),
        context.Process(target=sync_device, args=(str(tmp_path), "desktop", "laptop", POSTS, results)),
    ]

    by_name = {item["name"]: item for item in _collect(processes, results, 2)}

    laptop, desktop = by_name["laptop"], by_name["desktop"]
    assert laptop["layout"] == desktop["layout"]
    assert laptop["seen"] == [f"desktop:{index}" for index in range(POSTS)]
    assert desktop["seen"] == [f"laptop:{index}" for index in range(POSTS)]
    message_ids = sorted(laptop["own_ids"] + desktop["own_ids"])
    assert message_ids == list(range(message_ids[0], message_ids[0] + 2 * POSTS))
    assert laptop["own_ids"] == sorted(laptop["own_ids"])
    observer = make_device(tmp_path)

    async def vaults() -> tuple[Any, ...]:
        await sign_in(observer)
        return await observer.runtime.transport.find_vaults()

    layouts = run(vaults())
    assert [layout.vault_id for layout in layouts] == [VAULT_ID]
    channels = [chat for chat in FakeTelegramCloud(tmp_path).dialogs() if chat.title.startswith("Bento")]
    assert len(channels) == 3


def test_qr_login_in_another_process_is_approved_with_accept_login_token(tmp_path: Path) -> None:
    host = make_device(tmp_path, name="host")

    async def prepare() -> None:
        await sign_in(host)
        await host.runtime.transport.create_vault("vlt_family")

    run(prepare())
    context = multiprocessing.get_context("spawn")
    tokens = context.Queue()
    results = context.Queue()
    guest = context.Process(target=guest_qr_login, args=(str(tmp_path), tokens, results))
    guest.start()
    try:
        token = tokens.get(timeout=60)
        accepted = run(host.runtime.account.accept_login_token(token))
        outcome = results.get(timeout=60)
    finally:
        guest.join(timeout=30)
    assert guest.exitcode == 0

    assert outcome == {"authorized": True, "devices": ["Pixel 8", "guest", "host"], "vaults": ["vlt_family"]}
    assert accepted.device_model == "guest"
