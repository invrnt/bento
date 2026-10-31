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

    @property
    def active(self) -> bool:
        return self.removed_at is None


@dataclass(frozen=True, slots=True)
class DeviceRemoval:
    device: Device
    telegram_session_closed: bool
    recovery_code: str
