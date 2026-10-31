"""Outbox flush planning: the hold rule and batch size limits.

Hold rule (architecture § Sync capture details): `asset`, `thumbnail`, `album_item`, and `asset_index` upserts
wait in the outbox until their asset has a remote original, and are released right after that asset's `blob`
op, so peers never see assets they cannot download. Purges are never held.

Size rule (architecture § Batches): a batch holds at most `MAX_BATCH_BYTES` of op JSON, or one larger op. An
`asset_index` op over `MAX_INDEX_OP_BYTES` is cut down first; any op still over `MAX_OP_BYTES` could never be
delivered (receivers skip a batch over their limits whole) and is dropped. So every batch stays far below the
receivers' 16 MiB inflate limit and 8 MiB document limit.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from bento.application.sync.asset_index import MAX_INDEX_OP_BYTES, fit_index_fields
from bento.application.sync.ports import AssetHoldState
from bento.domain.storage import BlobKind
from bento.domain.sync import SyncEntity, SyncOperation, SyncOpKind
from bento.domain.vault import canonical_json
from bento.ports.sync import OutboxEntry

LOGGER = logging.getLogger("bento.sync.batching")

MAX_BATCH_OPS = 256
MAX_BATCH_BYTES = 512 * 1024
MAX_OP_BYTES = 4 * 1024 * 1024
"""Largest op JSON the flush publishes: a batch holding only it stays below half the receivers' document limit."""


def held_asset_id(op: SyncOperation) -> str | None:
    """The asset an op must wait for, or None when the op is never held."""
    if op.kind == SyncOpKind.PURGE:
        return None
    if op.entity in {SyncEntity.ASSET, SyncEntity.ASSET_INDEX}:
        return op.entity_id
    if op.entity == SyncEntity.THUMBNAIL:
        value = op.fields.get("asset_id")
        return value if isinstance(value, str) and value else None
    if op.entity == SyncEntity.ALBUM_ITEM:
        value = op.fields.get("asset_id")
        if isinstance(value, str) and value:
            return value
        _, _, asset_id = op.entity_id.partition(":")
        return asset_id or None
    return None


def released_asset_id(op: SyncOperation) -> str | None:
    """The asset whose held ops follow this op: a remote original `blob` upsert."""
    if op.entity != SyncEntity.BLOB or op.kind != SyncOpKind.UPSERT:
        return None
    if op.fields.get("kind") != BlobKind.ORIGINAL.value:
        return None
    value = op.fields.get("asset_id")
    return value if isinstance(value, str) and value else None


def assets_to_check(entries: Iterable[OutboxEntry]) -> frozenset[str]:
    return frozenset(asset_id for entry in entries if (asset_id := held_asset_id(entry.operation)) is not None)


def deliverable(entry: OutboxEntry, *, max_op_bytes: int = MAX_OP_BYTES) -> OutboxEntry | None:
    """The entry as it is published: an oversized `asset_index` op is cut down (rows recorded before the cap
    existed), and anything still over `max_op_bytes` is None."""
    operation = entry.operation
    if (
        entry.size_bytes > MAX_INDEX_OP_BYTES
        and operation.entity == SyncEntity.ASSET_INDEX
        and operation.kind == SyncOpKind.UPSERT
    ):
        operation = replace(operation, fields=fit_index_fields(operation.fields))
        entry = OutboxEntry(seq=entry.seq, operation=operation, size_bytes=len(canonical_json(operation.to_dict())))
    return entry if entry.size_bytes <= max_op_bytes else None


@dataclass(frozen=True, slots=True)
class FlushPlan:
    batches: tuple[tuple[OutboxEntry, ...], ...]
    dropped: tuple[int, ...]
    """Seqs removed from the outbox unpublished: held ops whose asset no longer exists (the asset's purge op
    makes them moot) and `oversized` ops."""
    held: tuple[int, ...]
    """Seqs that stay in the outbox until their asset has a remote original."""
    oversized: tuple[int, ...] = ()
    """Seqs of ops over the op size cap, which no receiver would accept."""

    @property
    def op_count(self) -> int:
        return sum(len(batch) for batch in self.batches)


def plan_flush(
    entries: Sequence[OutboxEntry],
    asset_states: Mapping[str, AssetHoldState],
    *,
    max_ops: int = MAX_BATCH_OPS,
    max_bytes: int = MAX_BATCH_BYTES,
    max_op_bytes: int = MAX_OP_BYTES,
) -> FlushPlan:
    """Order publishable entries (held ops right after their releasing blob op) and split them into batches."""
    fitted: list[OutboxEntry] = []
    oversized: list[int] = []
    for entry in entries:
        published = deliverable(entry, max_op_bytes=max_op_bytes)
        if published is None:
            LOGGER.warning(
                "Dropped a %s op of %s bytes: it exceeds the sync op size cap", entry.operation.entity.value, entry.size_bytes
            )
            oversized.append(entry.seq)
        else:
            fitted.append(published)
    entries = fitted

    releasing_seq: dict[str, int] = {}
    for entry in entries:
        asset_id = released_asset_id(entry.operation)
        if asset_id is not None:
            releasing_seq.setdefault(asset_id, entry.seq)

    ordered: list[OutboxEntry] = []
    deferred: dict[str, list[OutboxEntry]] = {}
    dropped: list[int] = []
    held: list[int] = []
    for entry in entries:
        asset_id = held_asset_id(entry.operation)
        if asset_id is not None:
            state = asset_states.get(asset_id, AssetHoldState.MISSING)
            if state == AssetHoldState.MISSING:
                dropped.append(entry.seq)
                continue
            if state == AssetHoldState.LOCAL:
                held.append(entry.seq)
                continue
            release = releasing_seq.get(asset_id)
            if release is not None and release > entry.seq:
                deferred.setdefault(asset_id, []).append(entry)
                continue
        ordered.append(entry)
        released = released_asset_id(entry.operation)
        if released is not None:
            ordered.extend(deferred.pop(released, ()))
    for remaining in deferred.values():
        # The releasing blob op is in this plan, so `ordered` always drains `deferred`; keep it defensive.
        ordered.extend(remaining)

    return FlushPlan(
        batches=split_batches(ordered, max_ops=max_ops, max_bytes=max_bytes),
        dropped=tuple(sorted((*dropped, *oversized))),
        held=tuple(held),
        oversized=tuple(oversized),
    )


def split_batches(
    entries: Sequence[OutboxEntry], *, max_ops: int = MAX_BATCH_OPS, max_bytes: int = MAX_BATCH_BYTES
) -> tuple[tuple[OutboxEntry, ...], ...]:
    batches: list[tuple[OutboxEntry, ...]] = []
    current: list[OutboxEntry] = []
    size = 0
    for entry in entries:
        if current and (len(current) >= max_ops or size + entry.size_bytes > max_bytes):
            batches.append(tuple(current))
            current, size = [], 0
        current.append(entry)
        size += entry.size_bytes
    if current:
        batches.append(tuple(current))
    return tuple(batches)
