"""Device conditions (network, power, thermal, storage) and the job deferral policy they drive.

Desktop and headless hosts report `PERMISSIVE_CONDITIONS`, under which nothing is ever deferred, so the
policy only changes behavior where a host reports real conditions (Android). See `api/android-endpoints.md` §2.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

LOW_BATTERY_PCT = 15


class Thermal(StrEnum):
    NONE = "none"
    LIGHT = "light"
    MODERATE = "moderate"
    SEVERE = "severe"


_THERMAL_ORDER = {Thermal.NONE: 0, Thermal.LIGHT: 1, Thermal.MODERATE: 2, Thermal.SEVERE: 3}


@dataclass(frozen=True, slots=True)
class DeviceConditions:
    online: bool = True
    metered: bool = False
    unmetered: bool = True
    charging: bool = True
    battery_pct: int = 100
    power_save: bool = False
    data_saver: bool = False
    storage_free_bytes: int | None = None
    storage_total_bytes: int | None = None
    thermal: Thermal = Thermal.NONE

    @property
    def low_battery(self) -> bool:
        return not self.charging and self.battery_pct < LOW_BATTERY_PCT

    @property
    def hot(self) -> bool:
        return _THERMAL_ORDER[self.thermal] >= _THERMAL_ORDER[Thermal.MODERATE]

    @property
    def low_storage(self) -> bool:
        """Free space under 10 % of the volume (cache eviction trigger)."""
        if self.storage_free_bytes is None or not self.storage_total_bytes:
            return False
        return self.storage_free_bytes * 10 < self.storage_total_bytes

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> DeviceConditions:
        """Tolerant parse of a host snapshot: unknown keys are ignored, missing keys stay permissive."""
        online = _bool(data.get("online"), True)
        unmetered = _bool(data.get("unmetered", data.get("unmetered_wifi")), not _bool(data.get("metered"), False))
        metered = _bool(data.get("metered"), online and not unmetered)
        try:
            thermal = Thermal(str(data.get("thermal", Thermal.NONE.value)).lower())
        except ValueError:
            thermal = Thermal.NONE
        return cls(
            online=online,
            metered=metered and online,
            unmetered=unmetered and online,
            charging=_bool(data.get("charging"), True),
            battery_pct=max(0, min(100, _int(data.get("battery_pct"), 100))),
            power_save=_bool(data.get("power_save"), False),
            data_saver=_bool(data.get("data_saver"), False),
            storage_free_bytes=_optional_int(data.get("storage_free_bytes")),
            storage_total_bytes=_optional_int(data.get("storage_total_bytes")),
            thermal=thermal,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "online": self.online,
            "metered": self.metered,
            "unmetered": self.unmetered,
            "charging": self.charging,
            "battery_pct": self.battery_pct,
            "power_save": self.power_save,
            "data_saver": self.data_saver,
            "storage_free_bytes": self.storage_free_bytes,
            "storage_total_bytes": self.storage_total_bytes,
            "thermal": self.thermal.value,
        }


PERMISSIVE_CONDITIONS = DeviceConditions()


class WaitReason(StrEnum):
    OFFLINE = "offline"
    THERMAL = "thermal"
    BATTERY = "battery"
    CHARGING = "charging"
    WIFI = "wifi"


class JobClass(StrEnum):
    """How the deferral policy sees a job (the queue maps each class to a SQL predicate)."""

    ORIGINAL_UPLOAD = "original_upload"
    VIDEO_UPLOAD = "video_upload"
    DERIVED_UPLOAD = "derived_upload"
    INDEXING = "indexing"
    BULK_LOCAL = "bulk_local"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class DevicePolicy:
    wifi_only: bool = False
    videos_on_metered: bool = False
    only_charging: bool = False
    ocr_requires_charging: bool = False


@dataclass(frozen=True, slots=True)
class JobDeferral:
    """Job classes the worker must not claim now, each with the reason shown to people.

    `wifi_override_before`: `POST /backup/run-now` lifted the Wi-Fi rule for uploads queued up to this instant.
    """

    reasons: Mapping[JobClass, WaitReason]
    wifi_override_before: datetime | None = None

    @property
    def deferred(self) -> frozenset[JobClass]:
        return frozenset(self.reasons)

    @property
    def empty(self) -> bool:
        return not self.reasons


NO_DEFERRAL = JobDeferral(reasons={})


def wait_reason(
    job_class: JobClass, conditions: DeviceConditions, policy: DevicePolicy, *, wifi_override: bool = False
) -> WaitReason | None:
    """Why a job of `job_class` must wait under `conditions`, or None when it may run now.

    Order matters: the first reason that applies is the one people see.
    """
    uploads = {JobClass.ORIGINAL_UPLOAD, JobClass.VIDEO_UPLOAD, JobClass.DERIVED_UPLOAD}
    if job_class in uploads and not conditions.online:
        return WaitReason.OFFLINE
    bulk = {JobClass.ORIGINAL_UPLOAD, JobClass.VIDEO_UPLOAD, JobClass.INDEXING, JobClass.BULK_LOCAL}
    if job_class in bulk:
        if conditions.hot:
            return WaitReason.THERMAL
        if conditions.low_battery or conditions.power_save:
            return WaitReason.BATTERY
    if job_class == JobClass.INDEXING and policy.ocr_requires_charging and not conditions.charging:
        return WaitReason.CHARGING
    if job_class in {JobClass.ORIGINAL_UPLOAD, JobClass.VIDEO_UPLOAD}:
        if policy.only_charging and not conditions.charging:
            return WaitReason.CHARGING
        if not conditions.unmetered and not wifi_override:
            if policy.wifi_only or conditions.data_saver:
                return WaitReason.WIFI
            if job_class == JobClass.VIDEO_UPLOAD and not policy.videos_on_metered:
                return WaitReason.WIFI
    return None


def job_deferral(
    conditions: DeviceConditions, policy: DevicePolicy, *, wifi_override_before: datetime | None = None
) -> JobDeferral:
    """The deferral for every job class. With an active run-now override, Wi-Fi-deferred uploads queued before
    `wifi_override_before` stay claimable (the queue applies the cut-off); battery/thermal rules still apply."""
    reasons = {
        job_class: reason
        for job_class in JobClass
        if (reason := wait_reason(job_class, conditions, policy)) is not None
    }
    override = wifi_override_before if any(reason == WaitReason.WIFI for reason in reasons.values()) else None
    return JobDeferral(reasons=reasons, wifi_override_before=override)


def _bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"true", "1", "yes"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"false", "0", "no"}:
        return False
    return default


def _int(value: object, default: int) -> int:
    parsed = _optional_int(value)
    return default if parsed is None else parsed


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
