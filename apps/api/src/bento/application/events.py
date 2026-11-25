"""Library change events for `GET /events` (Server-Sent Events), so clients stop polling every few seconds.

The service compares cheap per-topic change signatures (counts and latest timestamps read from SQLite) once per
`interval`: that catches changes made by any process (API, worker, sync applying peers' ops) without a message
bus. Events say *what* changed (topics), never the data; clients refetch the affected endpoints.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ChangeTopic(StrEnum):
    LIBRARY = "library"
    """Assets, folders, albums, album items, thumbnails: refetch Drive, Photos, albums, search."""
    JOBS = "jobs"
    """Background jobs (uploads, OCR, thumbnails): refetch `/jobs`, `/activity`, `/backup/status`."""
    IMPORTS = "imports"
    """Android content imports: refetch `/android/imports/{id}`, `/activity`."""
    SYNC = "sync"
    """Sync, vault and device registry state: refetch `/sync/status`, `/vault`, `/devices`, `/activity`."""


class ChangeSignaturesPort(Protocol):
    async def signatures(self, topics: frozenset[ChangeTopic]) -> Mapping[ChangeTopic, str]: ...


@dataclass(frozen=True, slots=True)
class ChangeEvent:
    kind: str
    """`ready` (first event: subscribed), `change`, or `heartbeat` (keeps proxies and the client's timeout happy)."""
    topics: tuple[ChangeTopic, ...] = ()


DEFAULT_INTERVAL_SECONDS = 1.0
HEARTBEAT_SECONDS = 15.0
MAX_STREAM_SECONDS = 3600


class LibraryEventsService:
    def __init__(
        self,
        *,
        signatures: ChangeSignaturesPort,
        interval: float = DEFAULT_INTERVAL_SECONDS,
        heartbeat: float = HEARTBEAT_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._signatures = signatures
        self._interval = interval
        self._heartbeat = heartbeat
        self._sleep = sleep
        self._monotonic = monotonic

    async def stream(
        self,
        topics: Iterable[ChangeTopic] | None = None,
        *,
        max_seconds: float = MAX_STREAM_SECONDS,
        disconnected: Callable[[], Awaitable[bool]] | None = None,
    ) -> AsyncIterator[ChangeEvent]:
        """`ready`, then `change` whenever a watched topic's signature moves, `heartbeat` when idle; ends after
        `max_seconds` (clients reconnect) or once `disconnected()` says so."""
        watched = frozenset(topics) if topics else frozenset(ChangeTopic)
        started = last_sent = self._monotonic()
        previous = dict(await self._signatures.signatures(watched))
        yield ChangeEvent("ready", tuple(sorted(watched)))
        while self._monotonic() - started < max_seconds:
            await self._sleep(self._interval)
            if disconnected is not None and await disconnected():
                return
            current = dict(await self._signatures.signatures(watched))
            changed = tuple(sorted(topic for topic in watched if current.get(topic) != previous.get(topic)))
            previous = current
            now = self._monotonic()
            if changed:
                last_sent = now
                yield ChangeEvent("change", changed)
            elif now - last_sent >= self._heartbeat:
                last_sent = now
                yield ChangeEvent("heartbeat")
