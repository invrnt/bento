"""Snapshot payload (sealed with `SealPurpose.SNAPSHOT`, uploaded as `<uuid4>.bsnap`).

```json
{"bento": "sync-snapshot", "v": 1, "snapshot": "<uuid4>", "device": "dev_…", "vault_id": "vlt_…",
 "covers_through_message_id": 456, "created_at": "ISO-8601",
 "states": [{"entity": "asset", "id": "asset_…", "fields": {…}, "clocks": {"filename": "<hlc>"}}],
 "purged": [["asset", "asset_…", "<hlc>"]]}
```
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bento.application.sync.state import format_timestamp
from bento.domain.errors import ValidationFailedError
from bento.domain.sync import SYNCED_FIELDS, SyncEntity
from bento.ports.sync import EntityState

SNAPSHOT_MARKER = "sync-snapshot"
SNAPSHOT_VERSION = 1


@dataclass(frozen=True, slots=True)
class ParsedSnapshot:
    snapshot_id: str
    vault_id: str
    covers_through_message_id: int
    states: tuple[EntityState, ...]
    purged: tuple[tuple[str, str, str], ...]


def snapshot_payload(
    *,
    snapshot_id: str,
    device_id: str,
    vault_id: str,
    covers_through_message_id: int,
    created_at: datetime,
    states: Iterable[EntityState],
    purged: Iterable[tuple[str, str, str]],
) -> dict[str, Any]:
    return {
        "bento": SNAPSHOT_MARKER,
        "v": SNAPSHOT_VERSION,
        "snapshot": snapshot_id,
        "device": device_id,
        "vault_id": vault_id,
        "covers_through_message_id": covers_through_message_id,
        "created_at": format_timestamp(created_at),
        "states": [
            {"entity": state.entity.value, "id": state.entity_id, "fields": state.fields, "clocks": state.clocks}
            for state in states
        ],
        "purged": [list(item) for item in purged],
    }


def parse_snapshot(payload: Any) -> ParsedSnapshot:
    if not isinstance(payload, Mapping) or payload.get("bento") != SNAPSHOT_MARKER or payload.get("v") != SNAPSHOT_VERSION:
        raise ValidationFailedError("Invalid sync snapshot")
    try:
        states = tuple(_state(item) for item in payload["states"])
        purged = tuple(_purged(item) for item in payload["purged"])
        return ParsedSnapshot(
            snapshot_id=str(payload["snapshot"]),
            vault_id=str(payload["vault_id"]),
            covers_through_message_id=int(payload["covers_through_message_id"]),
            states=states,
            purged=purged,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationFailedError("Invalid sync snapshot") from exc


def _state(item: Any) -> EntityState:
    entity = SyncEntity(item["entity"])
    fields = dict(item["fields"])
    clocks = {str(name): str(value) for name, value in dict(item["clocks"]).items()}
    allowed = SYNCED_FIELDS[entity]
    if not set(fields) <= allowed or not set(clocks) <= allowed:
        raise ValueError("snapshot state has unsynced fields")
    entity_id = str(item["id"])
    if not entity_id:
        raise ValueError("snapshot state without id")
    return EntityState(entity=entity, entity_id=entity_id, fields=fields, clocks=clocks)


def _purged(item: Any) -> tuple[str, str, str]:
    entity, entity_id, hlc = item
    return SyncEntity(entity).value, str(entity_id), str(hlc)
