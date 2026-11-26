"""The desktop's power state, as the worker sees it (`BENTO_POWER_STATE_FILE`).

The Electron host writes `<data_dir>/run/power.json` as `{on_battery, battery_percent, low_battery, updated_at}`
from `powerMonitor` (rewritten about every minute while on battery). Indexing pauses while `low_battery` is
true. A missing, unreadable or stale file (older than `STALE_AFTER_SECONDS`) means "on AC": a desktop that
stopped writing it must never keep the library unindexed.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

POWER_STATE_FILE_ENV = "BENTO_POWER_STATE_FILE"
STALE_AFTER_SECONDS = 5 * 60.0


@dataclass(frozen=True, slots=True)
class PowerState:
    on_battery: bool = False
    battery_percent: int | None = None
    low_battery: bool = False


ON_AC = PowerState()


class PowerStateFile:
    """Reads the file at most once per change (mtime/size); staleness is re-checked on every call."""

    def __init__(self, path: Path, *, now: Callable[[], float] = time.time) -> None:
        self._path = path
        self._now = now
        self._stamp: tuple[int, int] | None = None
        self._cached: tuple[PowerState, float] | None = None

    @property
    def path(self) -> Path:
        return self._path

    def current(self) -> PowerState:
        try:
            stat = self._path.stat()
        except OSError:
            self._stamp, self._cached = None, None
            return ON_AC
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp != self._stamp:
            self._stamp, self._cached = stamp, _read(self._path, fallback_time=stat.st_mtime)
        if self._cached is None:
            return ON_AC
        state, written_at = self._cached
        if self._now() - written_at > STALE_AFTER_SECONDS:
            return ON_AC
        return state

    def low_battery(self) -> bool:
        return self.current().low_battery


def power_state_from_environment(environ: Mapping[str, str] | None = None) -> PowerStateFile | None:
    """None when no host writes a power state (headless, Docker, CLI daemon)."""
    source = os.environ if environ is None else environ
    raw = (source.get(POWER_STATE_FILE_ENV) or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return PowerStateFile(path) if path.is_absolute() else None


def _read(path: Path, *, fallback_time: float) -> tuple[PowerState, float] | None:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    on_battery = payload.get("on_battery") is True
    percent = payload.get("battery_percent")
    battery_percent = (
        int(percent)
        if isinstance(percent, (int, float)) and not isinstance(percent, bool) and 0 <= percent <= 100
        else None
    )
    state = PowerState(
        on_battery=on_battery,
        battery_percent=battery_percent,
        low_battery=on_battery and payload.get("low_battery") is True,
    )
    return state, _timestamp(payload.get("updated_at"), fallback_time)


def _timestamp(value: object, fallback: float) -> float:
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
        if parsed.tzinfo is not None:
            return parsed.timestamp()
    return fallback
