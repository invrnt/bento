from __future__ import annotations

import asyncio
import time
from collections.abc import Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from bento.adapters.fake_telegram import FAKE_LOGIN_CODE, FakeTelegramOptions
from bento.infrastructure.runtime import TelegramRuntime, create_fake_telegram_runtime

T = TypeVar("T")


class MemoryKeyStore:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    async def get(self, name: str) -> bytes | None:
        return self.values.get(name)

    async def put(self, name: str, value: bytes) -> None:
        self.values[name] = value

    async def delete(self, name: str) -> None:
        self.values.pop(name, None)


@dataclass
class ManualClock:
    current: float = field(default_factory=time.time)

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


@dataclass
class Device:
    runtime: TelegramRuntime
    key_store: MemoryKeyStore


def run(coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


def make_device(
    directory: Path,
    *,
    clock: ManualClock | None = None,
    name: str = "device",
    **option_overrides: Any,
) -> Device:
    key_store = MemoryKeyStore()
    options = FakeTelegramOptions(device_model=name, platform="linux", app_name="Bento test", **option_overrides)
    runtime = create_fake_telegram_runtime(directory, key_store, options=options, clock=clock)
    return Device(runtime=runtime, key_store=key_store)


async def sign_in(device: Device) -> None:
    await device.runtime.account.start_phone_login("+57 300 000 0001")
    status = await device.runtime.account.submit_code(FAKE_LOGIN_CODE)
    assert status.authorized
