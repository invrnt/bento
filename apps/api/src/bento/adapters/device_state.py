"""Device policy settings and the run-now override, read from the catalog (shared by the API and worker)."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.mappers import aware
from bento.domain.device import DevicePolicy
from bento.domain.settings_registry import platform_default
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import SettingModel, SyncStateModel
from bento.ports.repositories import ClockPort

RUN_NOW_KEY = "backup.run_now_at"
POLICY_KEYS = ("backup_wifi_only", "backup_videos_on_metered", "backup_only_charging", "ocr_requires_charging")
CACHE_SECONDS = 2.0


class SQLiteDevicePolicySource:
    """`DevicePolicy` from saved settings (LIVE apply), falling back to locked values and platform defaults.

    `locked` holds values fixed by the host (environment in headless mode); they win over saved values.
    Cached for `CACHE_SECONDS` because the worker asks before every claim.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        platform: str,
        locked: Mapping[str, object] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session_factory = session_factory
        self._platform = platform
        self._locked = dict(locked or {})
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: tuple[float, DevicePolicy] | None = None

    def __call__(self) -> DevicePolicy:
        with self._lock:
            if self._cached is not None and self._clock() - self._cached[0] < CACHE_SECONDS:
                return self._cached[1]
        with session_scope(self._session_factory) as session:
            saved = dict(session.execute(select(SettingModel.key, SettingModel.value).where(SettingModel.key.in_(POLICY_KEYS))).all())
        values = {key: self._value(key, saved) for key in POLICY_KEYS}
        policy = DevicePolicy(
            wifi_only=values["backup_wifi_only"],
            videos_on_metered=values["backup_videos_on_metered"],
            only_charging=values["backup_only_charging"],
            ocr_requires_charging=values["ocr_requires_charging"],
        )
        with self._lock:
            self._cached = (self._clock(), policy)
        return policy

    def _value(self, key: str, saved: Mapping[str, str]) -> bool:
        if key in self._locked:
            return _as_bool(self._locked[key], default=bool(platform_default(key, self._platform)))
        raw = saved.get(key)
        default = bool(platform_default(key, self._platform))
        if raw is None:
            return default
        try:
            return _as_bool(json.loads(raw), default=default)
        except json.JSONDecodeError:
            return _as_bool(raw, default=default)


class SQLiteRunNowState:
    """`POST /backup/run-now`: uploads queued up to that instant ignore the Wi-Fi rule."""

    def __init__(self, session_factory: sessionmaker[Session], clock: ClockPort) -> None:
        self._session_factory = session_factory
        self._clock = clock

    def __call__(self) -> datetime | None:
        with session_scope(self._session_factory) as session:
            model = session.get(SyncStateModel, RUN_NOW_KEY)
            if model is None or not model.value:
                return None
        try:
            return aware(datetime.fromisoformat(model.value))
        except ValueError:
            return None

    def request(self) -> datetime:
        now = self._clock.now()
        with session_scope(self._session_factory) as session:
            session.merge(SyncStateModel(key=RUN_NOW_KEY, value=now.isoformat(), updated_at=now))
        return now


def _as_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return default
