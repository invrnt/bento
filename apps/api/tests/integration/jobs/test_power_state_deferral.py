"""Desktop power state (`BENTO_POWER_STATE_FILE`): indexing waits while the battery is low, through the queue's
existing job deferral. Missing, broken or stale files mean "on AC"."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bento.adapters.jobs import SQLiteJobQueue
from bento.adapters.runtime.power_state import (
    POWER_STATE_FILE_ENV,
    STALE_AFTER_SECONDS,
    PowerStateFile,
    power_state_from_environment,
)
from bento.application.jobs import AlwaysEligible
from bento.domain.device import NO_DEFERRAL, JobClass, JobDeferral, WaitReason
from bento.domain.jobs import JobPriority, JobType
from bento.interfaces.worker.runtime import PowerAwareEligibility, with_power_state
from tests.integration.db.support import FixedClock, migrated_session_factory

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


def write_power(path: Path, *, low: bool, on_battery: bool = True, updated_at: datetime | None = NOW, percent: int = 12) -> None:
    document: dict[str, object] = {"on_battery": on_battery, "battery_percent": percent, "low_battery": low}
    if updated_at is not None:
        document["updated_at"] = updated_at.isoformat().replace("+00:00", "Z")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def reader(path: Path, at: datetime = NOW) -> PowerStateFile:
    return PowerStateFile(path, now=lambda: at.timestamp())


def test_missing_broken_and_stale_files_mean_on_ac(tmp_path: Path) -> None:
    path = tmp_path / "run" / "power.json"
    assert reader(path).low_battery() is False

    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert reader(path).low_battery() is False

    write_power(path, low=True)
    assert reader(path).low_battery() is True
    assert reader(path).current().battery_percent == 12
    assert reader(path, NOW + timedelta(seconds=STALE_AFTER_SECONDS - 1)).low_battery() is True
    assert reader(path, NOW + timedelta(seconds=STALE_AFTER_SECONDS + 1)).low_battery() is False

    write_power(path, low=True, on_battery=False)  # low only counts on battery
    assert reader(path).low_battery() is False


def test_the_file_time_stands_in_for_a_missing_updated_at(tmp_path: Path) -> None:
    path = tmp_path / "power.json"
    write_power(path, low=True, updated_at=None)
    written = NOW.timestamp()
    os.utime(path, (written, written))

    assert reader(path).low_battery() is True
    assert reader(path, NOW + timedelta(minutes=6)).low_battery() is False


def test_a_rewritten_file_is_read_again(tmp_path: Path) -> None:
    path = tmp_path / "power.json"
    power = reader(path)
    write_power(path, low=True)
    assert power.low_battery() is True

    write_power(path, low=False, percent=80)
    os.utime(path, (NOW.timestamp() + 60, NOW.timestamp() + 60))  # a new mtime even on coarse filesystems
    assert power.low_battery() is False


def test_power_file_comes_from_the_environment(tmp_path: Path) -> None:
    assert power_state_from_environment({}) is None
    assert power_state_from_environment({POWER_STATE_FILE_ENV: "relative/power.json"}) is None
    found = power_state_from_environment({POWER_STATE_FILE_ENV: str(tmp_path / "power.json")})
    assert found is not None and found.path == tmp_path / "power.json"

    base = AlwaysEligible()
    assert with_power_state(base, {}) is base
    assert isinstance(with_power_state(base, {POWER_STATE_FILE_ENV: str(tmp_path / "power.json")}), PowerAwareEligibility)


class Low:
    def __init__(self, value: bool) -> None:
        self.value = value

    def low_battery(self) -> bool:
        return self.value


class FixedEligibility:
    def __init__(self, deferral: JobDeferral) -> None:
        self.deferral = deferral

    def current(self) -> JobDeferral:
        return self.deferral

    def conditions(self) -> object:
        return AlwaysEligible().conditions()


def test_low_battery_adds_an_indexing_deferral_on_top_of_the_host_rules() -> None:
    assert PowerAwareEligibility(AlwaysEligible(), Low(False)).current() is NO_DEFERRAL
    assert PowerAwareEligibility(AlwaysEligible(), Low(True)).current().reasons == {JobClass.INDEXING: WaitReason.BATTERY}

    host = JobDeferral(reasons={JobClass.VIDEO_UPLOAD: WaitReason.WIFI, JobClass.INDEXING: WaitReason.THERMAL})
    kept = PowerAwareEligibility(FixedEligibility(host), Low(True)).current()  # type: ignore[arg-type]
    assert kept.reasons == host.reasons  # the host's own reason wins

    wifi = JobDeferral(reasons={JobClass.VIDEO_UPLOAD: WaitReason.WIFI}, wifi_override_before=NOW)
    merged = PowerAwareEligibility(FixedEligibility(wifi), Low(True)).current()  # type: ignore[arg-type]
    assert merged.reasons == {JobClass.VIDEO_UPLOAD: WaitReason.WIFI, JobClass.INDEXING: WaitReason.BATTERY}
    assert merged.wifi_override_before == NOW


def test_queue_holds_embedding_jobs_while_the_battery_is_low(tmp_path: Path) -> None:
    async def scenario() -> None:
        queue = SQLiteJobQueue(migrated_session_factory(tmp_path), FixedClock())
        power_file = tmp_path / "run" / "power.json"
        eligibility = PowerAwareEligibility(AlwaysEligible(), reader(power_file, datetime.now(UTC)))
        write_power(power_file, low=True, updated_at=datetime.now(UTC))
        await queue.enqueue(type=JobType.EMBEDDING, priority=int(JobPriority.EMBEDDING), payload={"asset_id": "a"})
        await queue.enqueue(type=JobType.THUMBNAIL, priority=int(JobPriority.THUMBNAIL), payload={"asset_id": "a"})

        backlog = await queue.backlog(deferral=eligibility.current())
        assert backlog.deferred == {WaitReason.BATTERY: 1}
        claimed = await queue.claim_next("worker-1", deferral=eligibility.current())
        assert claimed is not None and claimed.type is JobType.THUMBNAIL
        await queue.save(claimed.complete(FixedClock().now()))
        assert await queue.claim_next("worker-1", deferral=eligibility.current()) is None

        write_power(power_file, low=False, on_battery=False, percent=90, updated_at=datetime.now(UTC))
        later = datetime.now(UTC).timestamp() + 5
        os.utime(power_file, (later, later))
        resumed = await queue.claim_next("worker-1", deferral=eligibility.current())
        assert resumed is not None and resumed.type is JobType.EMBEDDING

    asyncio.run(scenario())
