from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DevicePlatform(StrEnum):
    LINUX = "linux"
    MACOS = "macos"
    WINDOWS = "windows"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Device:
    id: str
    name: str
    platform: DevicePlatform
    public_key: str
    added_at: datetime
    telegram_auth_hash: int | None = None
    last_seen_at: datetime | None = None
    removed_at: datetime | None = None
    current: bool = False
    introduced_by: str | None = None
    """Device-local: the device whose sync data first introduced this row here; None when added on this device."""
    first_seen_at: datetime | None = None
    reviewed_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.removed_at is None

    @property
    def needs_review(self) -> bool:
        """An active device this device first learned about through sync and the person has not acknowledged."""
        return self.active and not self.current and self.introduced_by is not None and self.reviewed_at is None


@dataclass(frozen=True, slots=True)
class DeviceRemoval:
    device: Device
    telegram_session_closed: bool
    recovery_code: str
    excluded: tuple[Device, ...] = ()
    """Devices the person chose to leave out of the new keys; they are removed too."""
