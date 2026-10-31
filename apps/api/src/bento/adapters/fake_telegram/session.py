from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import ParamSpec, TypeVar

from bento.adapters.fake_telegram.cloud import FakeTelegramCloud
from bento.adapters.fake_telegram.options import FakeTelegramOptions
from bento.domain.errors import TelegramAccountError, TelegramFloodWaitError
from bento.ports.key_store import TELEGRAM_SESSION, KeyStorePort

SESSION_PREFIX = b"bento-fake-session:v1:"
_TOUCH_INTERVAL_SECONDS = 60.0

P = ParamSpec("P")
T = TypeVar("T")


DeviceModelProvider = Callable[[], Awaitable[str]]


class FakeTelegramSession:
    """One Bento instance: its authorization id lives in the key store under `telegram.session`.

    With a `device_model` provider the instance announces that name (like `Bento (ab12cd)`) when it signs in,
    exactly as the MTProto client does, instead of `options.device_model`.
    """

    def __init__(
        self,
        cloud: FakeTelegramCloud,
        key_store: KeyStorePort,
        options: FakeTelegramOptions,
        *,
        device_model: DeviceModelProvider | None = None,
    ) -> None:
        self.cloud = cloud
        self.options = options
        self._key_store = key_store
        self._device_model = device_model
        self._touched_at = 0.0

    async def announced_options(self) -> FakeTelegramOptions:
        """The options a new authorization of this instance is recorded with."""
        if self._device_model is None:
            return self.options
        return replace(self.options, device_model=await self._device_model())

    async def authorization_id(self) -> str | None:
        raw = await self._key_store.get(TELEGRAM_SESSION)
        if raw is None or not raw.startswith(SESSION_PREFIX):
            return None
        authorization_id = raw[len(SESSION_PREFIX) :].decode("ascii", "replace")
        record = await self.run(self.cloud.authorization, authorization_id)
        return authorization_id if record is not None else None

    async def require(self) -> str:
        self._raise_injected_fault()
        authorization_id = await self.authorization_id()
        if authorization_id is None:
            raise TelegramAccountError("telegram_not_authorized", "This device is not signed in to Telegram")
        if time.monotonic() - self._touched_at > _TOUCH_INTERVAL_SECONDS:
            self._touched_at = time.monotonic()
            await self.run(self.cloud.touch_authorization, authorization_id)
        return authorization_id

    def _raise_injected_fault(self) -> None:
        fault = self.cloud.active_fault()
        if fault is None:
            return
        kind, remaining = fault
        if kind == "flood_wait":
            raise TelegramFloodWaitError(max(1, math.ceil(remaining)))
        raise TelegramAccountError("telegram_network", "Telegram could not be reached")

    async def store(self, authorization_id: str) -> None:
        await self._key_store.put(TELEGRAM_SESSION, SESSION_PREFIX + authorization_id.encode("ascii"))

    async def clear(self) -> None:
        await self._key_store.delete(TELEGRAM_SESSION)

    async def run(self, function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        """Filesystem work happens off the event loop."""
        return await asyncio.to_thread(function, *args, **kwargs)

    async def call(self, function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        await self.require()
        return await self.run(function, *args, **kwargs)
