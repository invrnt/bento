"""Entry points run in separate processes (multiprocessing spawn) to act as independent Bento devices."""

from __future__ import annotations

import asyncio
import time
from multiprocessing.queues import Queue
from pathlib import Path
from typing import Any

from bento.adapters.fake_telegram import FakeTelegramOptions
from bento.domain.sync import SyncMessageKind
from bento.infrastructure.runtime import create_fake_telegram_runtime
from tests.integration.fake_telegram.support import MemoryKeyStore, sign_in

VAULT_ID = "vlt_shared"


def sync_device(directory: str, name: str, peer: str, posts: int, results: Queue[dict[str, Any]]) -> None:
    results.put(asyncio.run(_sync_device(Path(directory), name, peer, posts)))


def guest_qr_login(directory: str, tokens: Queue[bytes], results: Queue[dict[str, Any]]) -> None:
    results.put(asyncio.run(_guest_qr_login(Path(directory), tokens)))


async def _sync_device(directory: Path, name: str, peer: str, posts: int) -> dict[str, Any]:
    options = FakeTelegramOptions(device_model=name, poll_interval_seconds=0.05)
    runtime = create_fake_telegram_runtime(directory, MemoryKeyStore(), options=options)
    device = type("Device", (), {"runtime": runtime})()
    await sign_in(device)  # type: ignore[arg-type]
    layout = await runtime.transport.create_vault(VAULT_ID)
    own_ids = []
    for index in range(posts):
        ref = await runtime.transport.post_sync_document(layout, SyncMessageKind.BATCH, f"{name}:{index}".encode())
        own_ids.append(ref.message_id)
    seen: list[str] = []
    cursor = 0
    deadline = time.monotonic() + 30
    while len(seen) < posts and time.monotonic() < deadline:
        for ref in await runtime.transport.list_sync_messages(layout, after_message_id=cursor):
            cursor = ref.message_id
            payload = (await runtime.transport.download_sync_document(layout, ref.message_id)).decode()
            if payload.startswith(f"{peer}:"):
                seen.append(payload)
        if len(seen) < posts:
            await runtime.transport.wait_for_activity(layout, 1.0)
    return {"name": name, "layout": layout, "own_ids": own_ids, "seen": seen}


async def _guest_qr_login(directory: Path, tokens: Queue[bytes]) -> dict[str, Any]:
    options = FakeTelegramOptions(device_model="guest", manual_login=True)
    runtime = create_fake_telegram_runtime(directory, MemoryKeyStore(), options=options)
    status = await runtime.account.start_qr_login()
    assert status.qr_token is not None
    tokens.put(status.qr_token)
    deadline = time.monotonic() + 20
    while not status.authorized and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
        status = await runtime.account.poll_login()
    authorizations = await runtime.account.list_authorizations() if status.authorized else ()
    return {
        "authorized": status.authorized,
        "devices": sorted(item.device_model for item in authorizations),
        "vaults": [layout.vault_id for layout in await runtime.transport.find_vaults()] if status.authorized else [],
    }
