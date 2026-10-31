from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from bento.domain.sync import SyncEntity, SyncOperation


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    seq: int
    operation: SyncOperation
    size_bytes: int


@dataclass(frozen=True, slots=True)
class EntityState:
    """Full synced state of one entity plus per-field clocks, as carried by snapshots."""

    entity: SyncEntity
    entity_id: str
    fields: dict[str, object]
    clocks: dict[str, str]


class SyncOutboxPort(Protocol):
    async def pending(self, *, limit: int = 256) -> tuple[OutboxEntry, ...]: ...

    async def remove(self, seqs: tuple[int, ...]) -> None: ...

    async def stats(self) -> tuple[int, int]:
        """(pending op count, oldest op age in milliseconds or 0)."""
        ...

    async def record(self, operation: SyncOperation) -> None:
        """Explicit ops (e.g. `asset_index`, `device`) not produced by change capture."""
        ...


class SyncStateRepositoryPort(Protocol):
    async def get_value(self, key: str) -> str | None: ...

    async def set_value(self, key: str, value: str) -> None: ...

    async def is_batch_applied(self, batch_id: str) -> bool: ...


class SyncApplyPort(Protocol):
    """Applies remote operations to local tables in one `sync_apply` transaction (no change capture)."""

    async def apply_batch(self, batch_id: str, message_id: int, operations: tuple[SyncOperation, ...]) -> int:
        """Returns the number of fields actually applied after LWW and purge checks."""
        ...

    async def apply_snapshot(self, states: AsyncIterator[EntityState], purged: tuple[tuple[str, str, str], ...]) -> int: ...


class SnapshotSourcePort(Protocol):
    def iter_states(self) -> AsyncIterator[EntityState]: ...

    async def purged(self) -> tuple[tuple[str, str, str], ...]:
        """(entity, entity_id, hlc) tuples."""
        ...


class HlcSourcePort(Protocol):
    """Process-wide HLC generator persisted in sync state."""

    async def next(self) -> str: ...

    async def observe(self, remote_hlc: str) -> None: ...
