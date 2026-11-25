from __future__ import annotations

import asyncio

from bento.application.events import ChangeEvent, ChangeTopic, LibraryEventsService


class Signatures:
    def __init__(self, script: list[dict[ChangeTopic, str]]) -> None:
        self.script = script
        self.calls = 0

    async def signatures(self, topics: frozenset[ChangeTopic]) -> dict[ChangeTopic, str]:
        value = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return {topic: value.get(topic, "") for topic in topics}


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


def _collect(service: LibraryEventsService, **kwargs) -> list[ChangeEvent]:  # type: ignore[no-untyped-def]
    async def run() -> list[ChangeEvent]:
        return [event async for event in service.stream(**kwargs)]

    return asyncio.run(run())


def test_ready_then_changes_for_watched_topics_and_heartbeats_when_idle() -> None:
    clock = Clock()
    library, jobs = ChangeTopic.LIBRARY, ChangeTopic.JOBS
    signatures = Signatures(
        [
            {library: "a", jobs: "1"},
            {library: "a", jobs: "1"},
            {library: "b", jobs: "1"},
            {library: "b", jobs: "2"},
            {library: "b", jobs: "2"},
        ]
    )
    service = LibraryEventsService(signatures=signatures, interval=1.0, heartbeat=3.0, sleep=clock.sleep, monotonic=clock)
    events = _collect(service, topics=[library, jobs], max_seconds=8)
    assert [(event.kind, event.topics) for event in events] == [
        ("ready", (jobs, library)),
        ("change", (library,)),
        ("change", (jobs,)),
        ("heartbeat", ()),
    ]


def test_unwatched_topics_never_fire_and_a_disconnect_ends_the_stream() -> None:
    clock = Clock()
    signatures = Signatures([{ChangeTopic.LIBRARY: "a", ChangeTopic.JOBS: "1"}, {ChangeTopic.LIBRARY: "a", ChangeTopic.JOBS: "2"}])
    service = LibraryEventsService(signatures=signatures, interval=1.0, sleep=clock.sleep, monotonic=clock)
    assert [event.kind for event in _collect(service, topics=[ChangeTopic.LIBRARY], max_seconds=5)] == ["ready"]

    calls = 0

    async def disconnected() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 2

    events = _collect(service, max_seconds=100, disconnected=disconnected)
    assert events[0].kind == "ready" and len(events) <= 2
