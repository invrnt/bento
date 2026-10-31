"""FLOOD_WAIT policy (architecture/telegram-first.md § Rate and size policy).

Waits up to `max_sleep_seconds` are slept exactly plus jitter and the request retried; longer waits are recorded
(so status can say "Telegram pidió esperar N min") and raised as `TelegramFloodWaitError` for the caller to
reschedule.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from bento.adapters.telegram_mtproto.errors import flood_wait_seconds
from bento.domain.errors import TelegramFloodWaitError

LOGGER = logging.getLogger("bento.telegram.flood")

T = TypeVar("T")
LongWaitRecorder = Callable[[int], Awaitable[None]]


class FloodWaitPolicy:
    def __init__(
        self,
        *,
        max_sleep_seconds: float = 60.0,
        max_retries: int = 3,
        jitter_seconds: float = 1.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_fraction: Callable[[], float] = random.random,
        on_long_wait: LongWaitRecorder | None = None,
    ) -> None:
        self._max_sleep = max_sleep_seconds
        self._max_retries = max_retries
        self._jitter = jitter_seconds
        self._sleep = sleep
        self._random = random_fraction
        self._on_long_wait = on_long_wait

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        attempt = 0
        while True:
            try:
                return await operation()
            except Exception as exc:
                seconds = flood_wait_seconds(exc)
                if seconds is None:
                    raise
                if seconds > self._max_sleep or attempt >= self._max_retries:
                    if self._on_long_wait is not None:
                        try:
                            await self._on_long_wait(seconds)
                        except Exception:  # noqa: BLE001 - recording the wait must never hide it
                            LOGGER.warning("Could not record a Telegram flood wait of %ss", seconds)
                    raise TelegramFloodWaitError(seconds) from exc
                attempt += 1
                delay = seconds + self._jitter * self._random()
                LOGGER.info("Telegram asked to wait %ss; retrying in %.1fs", seconds, delay)
                await self._sleep(delay)
