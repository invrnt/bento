"""Deferral rules for every device-condition combination (`api/android-endpoints.md` §2)."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime

import pytest

from bento.domain.device import (
    NO_DEFERRAL,
    PERMISSIVE_CONDITIONS,
    DeviceConditions,
    DevicePolicy,
    JobClass,
    Thermal,
    WaitReason,
    job_deferral,
    wait_reason,
)

ANDROID_DEFAULT = DevicePolicy(wifi_only=True, ocr_requires_charging=True)


def test_permissive_conditions_never_defer_anything_under_any_policy() -> None:
    for flags in itertools.product((False, True), repeat=4):
        policy = DevicePolicy(*flags)
        for job_class in JobClass:
            assert wait_reason(job_class, PERMISSIVE_CONDITIONS, policy) is None
        assert job_deferral(PERMISSIVE_CONDITIONS, policy).empty


@pytest.mark.parametrize(
    ("online", "unmetered", "charging", "battery", "power_save", "thermal", "data_saver"),
    list(itertools.product((True, False), (True, False), (True, False), (80, 10), (False, True), (Thermal.NONE, Thermal.MODERATE), (False, True))),
)
def test_every_combination_matches_the_rules(
    online: bool, unmetered: bool, charging: bool, battery: int, power_save: bool, thermal: Thermal, data_saver: bool
) -> None:
    conditions = DeviceConditions(
        online=online,
        metered=online and not unmetered,
        unmetered=online and unmetered,
        charging=charging,
        battery_pct=battery,
        power_save=power_save,
        thermal=thermal,
        data_saver=data_saver,
    )
    for policy in (DevicePolicy(), ANDROID_DEFAULT, DevicePolicy(only_charging=True, videos_on_metered=True)):
        for job_class in JobClass:
            assert wait_reason(job_class, conditions, policy) == _expected(job_class, conditions, policy)


def _expected(job_class: JobClass, c: DeviceConditions, p: DevicePolicy) -> WaitReason | None:
    uploads = {JobClass.ORIGINAL_UPLOAD, JobClass.VIDEO_UPLOAD, JobClass.DERIVED_UPLOAD}
    originals = {JobClass.ORIGINAL_UPLOAD, JobClass.VIDEO_UPLOAD}
    bulk = originals | {JobClass.INDEXING, JobClass.BULK_LOCAL}
    if job_class in uploads and not c.online:
        return WaitReason.OFFLINE
    if job_class in bulk and c.thermal == Thermal.MODERATE:
        return WaitReason.THERMAL
    if job_class in bulk and ((not c.charging and c.battery_pct < 15) or c.power_save):
        return WaitReason.BATTERY
    if job_class == JobClass.INDEXING and p.ocr_requires_charging and not c.charging:
        return WaitReason.CHARGING
    if job_class in originals:
        if p.only_charging and not c.charging:
            return WaitReason.CHARGING
        if not c.unmetered and (p.wifi_only or c.data_saver or (job_class == JobClass.VIDEO_UPLOAD and not p.videos_on_metered)):
            return WaitReason.WIFI
    return None


def test_thumbnails_and_sync_may_use_metered_networks() -> None:
    metered = DeviceConditions(metered=True, unmetered=False, charging=False, battery_pct=60)
    assert wait_reason(JobClass.DERIVED_UPLOAD, metered, ANDROID_DEFAULT) is None
    assert wait_reason(JobClass.OTHER, metered, ANDROID_DEFAULT) is None
    assert wait_reason(JobClass.ORIGINAL_UPLOAD, metered, ANDROID_DEFAULT) == WaitReason.WIFI
    # Videos wait for Wi-Fi even with "Solo con Wi-Fi" off, unless videos on mobile data were enabled.
    assert wait_reason(JobClass.VIDEO_UPLOAD, metered, DevicePolicy()) == WaitReason.WIFI
    assert wait_reason(JobClass.VIDEO_UPLOAD, metered, DevicePolicy(videos_on_metered=True)) is None
    assert wait_reason(JobClass.ORIGINAL_UPLOAD, metered, DevicePolicy()) is None


def test_run_now_override_lifts_only_the_wifi_rule() -> None:
    cutoff = datetime(2026, 1, 1, tzinfo=UTC)
    metered = DeviceConditions(metered=True, unmetered=False)
    deferral = job_deferral(metered, ANDROID_DEFAULT, wifi_override_before=cutoff)
    assert deferral.reasons[JobClass.ORIGINAL_UPLOAD] == WaitReason.WIFI
    assert deferral.wifi_override_before == cutoff  # the queue lets uploads queued before the cutoff through
    hot = DeviceConditions(metered=True, unmetered=False, thermal=Thermal.SEVERE)
    deferral = job_deferral(hot, ANDROID_DEFAULT, wifi_override_before=cutoff)
    assert deferral.reasons[JobClass.ORIGINAL_UPLOAD] == WaitReason.THERMAL
    assert deferral.wifi_override_before is None  # nothing waits for Wi-Fi, so no override applies


def test_conditions_parse_tolerantly_and_stay_permissive_when_missing() -> None:
    assert DeviceConditions.from_mapping({}) == DeviceConditions()
    parsed = DeviceConditions.from_mapping(
        {"online": True, "unmetered_wifi": False, "charging": "false", "battery_pct": 300, "thermal": "MODERATE", "x": 1}
    )
    assert parsed.metered and not parsed.unmetered and not parsed.charging and parsed.battery_pct == 100 and parsed.hot
    offline = DeviceConditions.from_mapping({"online": False, "unmetered": True, "thermal": "lava"})
    assert not offline.unmetered and not offline.metered and offline.thermal == Thermal.NONE
    assert DeviceConditions(storage_free_bytes=5, storage_total_bytes=100).low_storage
    assert not DeviceConditions(storage_free_bytes=50, storage_total_bytes=100).low_storage
    assert NO_DEFERRAL.empty
