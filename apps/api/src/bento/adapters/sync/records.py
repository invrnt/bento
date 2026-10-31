"""Sync bookkeeping rows written inside a caller's session: HLC, outbox ops, field clocks, purge tombstones."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from bento.application.sync.state import CAPTURE, LAST_HLC
from bento.domain.errors import ValidationFailedError
from bento.domain.sync import Hlc, SyncEntity, SyncOperation, SyncOpKind, hlc_receive, hlc_tick
from bento.domain.vault import canonical_json
from bento.infrastructure.db.models import SyncFieldClockModel, SyncOutboxModel, SyncPurgedModel, SyncStateModel

NowMs = Callable[[], int]
Now = Callable[[], datetime]


def system_now_ms() -> int:
    return time.time_ns() // 1_000_000


def system_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CaptureConfig:
    vault_id: str
    device_id: str

    @classmethod
    def parse(cls, raw: str | None) -> CaptureConfig | None:
        if not raw:
            return None
        try:
            data = json.loads(raw)
            vault_id, device_id = data["vault_id"], data["device_id"]
        except (ValueError, KeyError, TypeError):
            return None
        if not isinstance(vault_id, str) or not isinstance(device_id, str) or not device_id.startswith("dev_"):
            return None
        return cls(vault_id=vault_id, device_id=device_id)


def load_capture_config(session: Session) -> CaptureConfig | None:
    with session.no_autoflush:
        try:
            row = session.get(SyncStateModel, CAPTURE)
        except OperationalError:
            # Databases older than migration 0004 have no sync tables: nothing to capture.
            return None
    return CaptureConfig.parse(row.value if row is not None else None)


def put_state(session: Session, key: str, value: str, now: datetime) -> SyncStateModel:
    row = session.get(SyncStateModel, key)
    if row is None:
        row = SyncStateModel(key=key, value=value, updated_at=now)
        session.add(row)
    else:
        row.value = value
        row.updated_at = now
    return row


def op_size(operation: SyncOperation) -> int:
    return len(canonical_json(operation.to_dict()))


class HlcCursor:
    """The device HLC inside one transaction: loaded once, ticked per op, stored back on every change."""

    def __init__(self, session: Session, device_id: str, *, now_ms: NowMs, now: Now) -> None:
        self._session = session
        self._device_id = device_id
        self._now_ms = now_ms
        self._now = now
        self._last: Hlc | None = None
        self._row: SyncStateModel | None = None

    def current(self) -> Hlc:
        if self._last is None:
            with self._session.no_autoflush:
                row = self._session.get(SyncStateModel, LAST_HLC)
            self._row = row
            stored = _parse_hlc(row.value) if row is not None else None
            base = stored or Hlc.zero(self._device_id)
            self._last = Hlc(base.physical_ms, base.counter, self._device_id)
        return self._last

    def tick(self, *, after: str = "") -> str:
        """Next local HLC, strictly greater than the stored one and than `after` (an existing field clock)."""
        candidate = hlc_tick(self.current(), self._now_ms())
        floor = _parse_hlc(after) if after else None
        if floor is not None and candidate.format() <= after:
            candidate = hlc_receive(candidate, floor, self._now_ms())
        return self._store(candidate)

    def observe(self, remote: str) -> str:
        parsed = _parse_hlc(remote)
        if parsed is None:
            return self.current().format()
        return self._store(hlc_receive(self.current(), parsed, self._now_ms()))

    def _store(self, value: Hlc) -> str:
        self._last = value
        formatted = value.format()
        if self._row is None:
            with self._session.no_autoflush:
                self._row = put_state(self._session, LAST_HLC, formatted, self._now())
        else:
            self._row.value = formatted
            self._row.updated_at = self._now()
        return formatted


class OpWriter:
    """Adds outbox rows and local field clocks/tombstones for local ops, in the caller's transaction."""

    def __init__(self, session: Session, config: CaptureConfig, *, now_ms: NowMs = system_now_ms, now: Now = system_now) -> None:
        self._session = session
        self._config = config
        self._now = now
        self.hlc = HlcCursor(session, config.device_id, now_ms=now_ms, now=now)
        self._clocks: dict[tuple[str, str], dict[str, SyncFieldClockModel]] = {}
        self._purged: set[tuple[str, str]] = set()
        self.count = 0

    def emit(self, entity: SyncEntity, entity_id: str, kind: SyncOpKind, fields: dict[str, Any]) -> SyncOperation:
        clocks = self._clock_rows(entity, entity_id)
        newest = max((row.hlc for row in clocks.values()), default="")
        operation = SyncOperation(
            op_id=str(uuid.uuid4()),
            hlc=self.hlc.tick(after=newest),
            device_id=self._config.device_id,
            entity=entity,
            entity_id=entity_id,
            kind=kind,
            fields=fields,
        )
        self.write(operation)
        return operation

    def write(self, operation: SyncOperation) -> None:
        now = self._now()
        with self._session.no_autoflush:
            self._session.add(
                SyncOutboxModel(
                    op_id=operation.op_id,
                    hlc=operation.hlc,
                    entity=operation.entity.value,
                    entity_id=operation.entity_id,
                    kind=operation.kind.value,
                    fields_json=operation.fields,
                    size_bytes=op_size(operation),
                    created_at=now,
                )
            )
            clocks = self._clock_rows(operation.entity, operation.entity_id)
            if operation.kind == SyncOpKind.UPSERT:
                for name in operation.fields:
                    row = clocks.get(name)
                    if row is None:
                        row = SyncFieldClockModel(
                            entity=operation.entity.value, entity_id=operation.entity_id, field=name, hlc=operation.hlc
                        )
                        self._session.add(row)
                        clocks[name] = row
                    elif row.hlc < operation.hlc:
                        row.hlc = operation.hlc
            else:
                for row in clocks.values():
                    if inspect(row).pending:
                        self._session.expunge(row)
                    else:
                        self._session.delete(row)
                clocks.clear()
                key = (operation.entity.value, operation.entity_id)
                if key not in self._purged and self._session.get(SyncPurgedModel, key) is None:
                    self._purged.add(key)
                    self._session.add(
                        SyncPurgedModel(
                            entity=operation.entity.value, entity_id=operation.entity_id, hlc=operation.hlc, purged_at=now
                        )
                    )
        self.count += 1

    def _clock_rows(self, entity: SyncEntity, entity_id: str) -> dict[str, SyncFieldClockModel]:
        key = (entity.value, entity_id)
        cached = self._clocks.get(key)
        if cached is None:
            with self._session.no_autoflush:
                cached = {
                    row.field: row
                    for row in self._session.scalars(
                        select(SyncFieldClockModel).where(
                            SyncFieldClockModel.entity == entity.value, SyncFieldClockModel.entity_id == entity_id
                        )
                    )
                }
            self._clocks[key] = cached
        return cached


def _parse_hlc(value: str) -> Hlc | None:
    try:
        return Hlc.parse(value)
    except ValidationFailedError:
        return None
