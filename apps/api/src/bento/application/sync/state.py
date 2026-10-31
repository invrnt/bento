"""`sync_state` keys owned by the sync engine and typed accessors over the key/value store.

Values are text: integers in decimal, timestamps in ISO-8601 UTC, structured values as compact JSON.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from bento.application.sync.ports import SyncStateStorePort

LAST_HLC = "last_hlc"
"""Last hybrid logical clock issued or observed by this device (`Hlc.format()`)."""
CAPTURE = "capture"
"""`{"vault_id", "device_id"}` once the vault is ready on this device; change capture is off without it."""
INITIAL_PUBLISH = "initial_publish"
"""Vault id whose full-state publish already ran on this device."""
CURSOR = "last_applied_message_id"
"""Highest Sync channel message id processed (applied, skipped, or rejected)."""
EPOCH_FLOOR = "epoch_floor"
"""`{"epoch", "message_id"}`: envelopes sealed below `epoch` and posted after `message_id` are rejected."""
REMOVED_DEVICES = "removed_device_ids"
"""Sorted device ids listed as removed by an accepted keys message; their grants are rejected from then on."""
LAST_PUSH_AT = "last_push_at"
LAST_PULL_AT = "last_pull_at"
OPS_SINCE_SNAPSHOT = "ops_since_snapshot"
LAST_SNAPSHOT_AT = "last_snapshot_at"
BOOTSTRAP = "bootstrap"
"""`{"done", "total"}` while this device bootstraps; removed once it reaches the tip."""
LOOP = "loop"
"""`{"state", "waiting_until", "error", "updated_at"}` written by the worker's sync loop."""
SYNC_REQUESTED_AT = "sync_requested_at"
"""Cross-process "sync now" marker written by the API and consumed by the worker loop."""
SNAPSHOT_REQUESTED_AT = "snapshot_requested_at"
"""Marker from the `sync_snapshot` job: create a snapshot on the next caught-up cycle."""
LAST_NOTICE = "last_notice"
"""Latest local merge notice (folder moved to the root after a cycle or a purged parent)."""
PENDING_INDEX_PREFIX = "pending_index:"
"""Search index writes accepted by an applied batch and not yet written (crash recovery)."""
SKIPPED_MESSAGES = "skipped_messages"
"""Count of Sync messages passed over as permanently invalid (too large, malformed, unauthenticated, below floor)."""
LAST_SKIPPED = "last_skipped"
"""`{"message_id", "kind", "reason", "at"}` of the latest skipped Sync message."""
SKIPPED_OPS = "skipped_ops"
"""Count of remote ops dropped because their clock ran ahead of the message date or the local clock."""
DEVICE_REMOVED = "device_removed"
"""`{"device_id", "epoch", "message_id", "by", "at"}` once an authenticated keys message rotated the vault keys
without this device (or listed it as removed). The vault reports `locked` (`reason: device_removed`), sync is
paused, and re-joining installs a fresh device identity."""
OWN_BATCHES = "own_batch_message_ids"
"""Message ids of batches this device posted and has not pulled yet (re-published if they land below the floor)."""

VAULT_SCOPED_KEYS = (
    INITIAL_PUBLISH,
    CURSOR,
    EPOCH_FLOOR,
    REMOVED_DEVICES,
    LAST_PUSH_AT,
    LAST_PULL_AT,
    OPS_SINCE_SNAPSHOT,
    LAST_SNAPSHOT_AT,
    BOOTSTRAP,
    SNAPSHOT_REQUESTED_AT,
    SKIPPED_MESSAGES,
    LAST_SKIPPED,
    SKIPPED_OPS,
    OWN_BATCHES,
)
"""Keys reset when this device is attached to a different vault."""


class SyncStateValues:
    """Typed helpers over `SyncStateStorePort`."""

    def __init__(self, store: SyncStateStorePort) -> None:
        self.store = store

    async def get_json(self, key: str) -> Any:
        raw = await self.store.get_value(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    async def set_json(self, key: str, value: Any) -> None:
        await self.store.set_value(key, json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))

    async def get_int(self, key: str, default: int = 0) -> int:
        raw = await self.store.get_value(key)
        try:
            return int(raw) if raw is not None else default
        except ValueError:
            return default

    async def set_int(self, key: str, value: int) -> None:
        await self.store.set_value(key, str(int(value)))

    async def get_datetime(self, key: str) -> datetime | None:
        return parse_timestamp(await self.store.get_value(key))

    async def set_datetime(self, key: str, value: datetime) -> None:
        await self.store.set_value(key, format_timestamp(value))

    async def delete(self, key: str) -> None:
        await self.store.delete_value(key)


def format_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
