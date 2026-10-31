"""Transfer limits: parallel transfers (`telegram_parallel_transfers`) and the upload bandwidth token bucket
(`backup_bandwidth_limit_kbps`, read live so the backup policy applies without a restart)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

MIN_BURST_BYTES = 64 * 1024


class TokenBucket:
    """`consume(n)` waits until `n` bytes fit in a budget of `limit_kbps` KiB/s (0 = unlimited)."""

    def __init__(
        self,
        limit_kbps: Callable[[], int],
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._limit = limit_kbps
        self._clock = clock
        self._sleep = sleep
        self._tokens = 0.0
        self._updated = clock()
        self._lock = asyncio.Lock()

    async def consume(self, size_bytes: int) -> None:
        if size_bytes <= 0:
            return
        async with self._lock:
            remaining = float(size_bytes)
            while remaining > 0:
                rate = max(0, int(self._limit())) * 1024.0
                if rate <= 0:
                    self._tokens = 0.0
                    return
                capacity = max(rate, float(MIN_BURST_BYTES))
                now = self._clock()
                self._tokens = min(capacity, self._tokens + (now - self._updated) * rate)
                self._updated = now
                take = min(remaining, self._tokens)
                self._tokens -= take
                remaining -= take
                if remaining > 0:
                    await self._sleep(min(remaining, capacity) / rate)


class TransferLimits:
    """One semaphore per direction plus the upload bucket (`TransferLimiter` for the MTProto adapters)."""

    def __init__(self, *, parallel_transfers: int, upload_bucket: TokenBucket | None = None) -> None:
        slots = max(1, min(int(parallel_transfers), 4))
        self._uploads = asyncio.Semaphore(slots)
        self._downloads = asyncio.Semaphore(slots)
        self._bucket = upload_bucket

    @asynccontextmanager
    async def upload_slot(self) -> AsyncIterator[None]:
        async with self._uploads:
            yield

    @asynccontextmanager
    async def download_slot(self) -> AsyncIterator[None]:
        async with self._downloads:
            yield

    async def consume_upload(self, size_bytes: int) -> None:
        if self._bucket is not None:
            await self._bucket.consume(size_bytes)
