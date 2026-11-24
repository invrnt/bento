"""`ActivityService.announce`: one `attention {code, count}` per kind for Activity items not announced before."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

from bento.application.activity import ActivityService, ActivitySnapshot, FailedImport, FailedUpload, NewDevice
from bento.domain.backup import BackupPolicy
from bento.ports.device import NotifierEvent

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


@dataclass
class Source:
    snapshot_value: ActivitySnapshot = field(default_factory=ActivitySnapshot)

    async def snapshot(self, *, now: datetime) -> ActivitySnapshot:
        return self.snapshot_value


class Policy:
    async def get(self) -> BackupPolicy:
        return BackupPolicy()


class Clock:
    def now(self) -> datetime:
        return NOW


class Store:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get_value(self, key: str) -> str | None:
        return self.values.get(key)

    async def set_value(self, key: str, value: str) -> None:
        self.values[key] = value


class Notifier:
    def __init__(self) -> None:
        self.events: list[NotifierEvent] = []

    def emit(self, event: NotifierEvent) -> None:
        self.events.append(event)


def test_new_items_notify_once_per_kind_and_survive_a_new_service() -> None:
    async def scenario() -> None:
        source, store, notifier = Source(), Store(), Notifier()

        def service() -> ActivityService:
            return ActivityService(source=source, policy=Policy(), clock=Clock(), notifier=notifier, announced=store)  # type: ignore[arg-type]

        source.snapshot_value = ActivitySnapshot(
            failed_uploads=(FailedUpload("job_1", "asset_1", None), FailedUpload("job_2", "asset_2", None)),
            failed_imports=(FailedImport("imp_1", 2, "import_interrupted"),),
            new_devices=(NewDevice("dev_x", "Tablet", None, "dev_y"),),  # has its own `new_device` event
        )
        assert await service().announce() == 3
        payloads = sorted((event.name, event.payload["code"], event.payload["count"]) for event in notifier.events)
        assert payloads == [("attention", "import_failed", 1), ("attention", "upload_failed", 2)]

        notifier.events.clear()
        assert await service().announce() == 0  # a new process (background run) does not notify again
        assert notifier.events == []

        source.snapshot_value = ActivitySnapshot(failed_uploads=(FailedUpload("job_3", "asset_3", None),))
        assert await service().announce() == 1
        assert [(event.payload["code"], event.payload["count"]) for event in notifier.events] == [("upload_failed", 1)]

    asyncio.run(scenario())


def test_without_a_delivering_notifier_nothing_is_computed() -> None:
    from bento.adapters.device import NullNotifier

    async def scenario() -> None:
        service = ActivityService(
            source=Source(), policy=Policy(), clock=Clock(), notifier=NullNotifier(), announced=Store()  # type: ignore[arg-type]
        )
        assert await service.announce() == 0

    asyncio.run(scenario())
