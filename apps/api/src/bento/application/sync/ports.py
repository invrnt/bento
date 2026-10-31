"""Application-level ports of the sync engine, extending the Stage 14 contracts in `bento.ports.sync`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from bento.domain.sync import SyncOperation
from bento.ports.sync import OutboxEntry, SyncApplyPort, SyncOutboxPort, SyncStateRepositoryPort


@dataclass(frozen=True, slots=True)
class OutboxBacklog:
    count: int
    oldest_age_ms: int
    total_bytes: int
    max_seq: int


class SyncOutboxStorePort(SyncOutboxPort, Protocol):
    async def page(self, *, after_seq: int = 0, limit: int = 500) -> tuple[OutboxEntry, ...]:
        """Pending entries with `seq > after_seq`, ascending."""
        ...

    async def backlog(self, *, after_seq: int = 0) -> OutboxBacklog:
        """Size of the pending entries with `seq > after_seq`."""
        ...

    async def clear(self) -> None: ...


class SyncStateStorePort(SyncStateRepositoryPort, Protocol):
    async def delete_value(self, key: str) -> None: ...


class SyncApplierPort(SyncApplyPort, Protocol):
    async def apply_batch(
        self,
        batch_id: str,
        message_id: int,
        operations: tuple[SyncOperation, ...],
        *,
        sender: str | None = None,
        sent_at: datetime | None = None,
    ) -> int:
        """Also records `sent_at` as the sending device's `last_seen_at` (local-only column)."""
        ...


class AssetHoldState(StrEnum):
    REMOTE = "remote"
    """The asset exists and has an original stored in Telegram."""
    LOCAL = "local"
    """The asset exists but its original is still local-only."""
    MISSING = "missing"
    """No such asset row (purged locally)."""


class HoldStatePort(Protocol):
    async def asset_states(self, asset_ids: frozenset[str]) -> Mapping[str, AssetHoldState]: ...


class FullStatePublisherPort(Protocol):
    async def publish_full_state(self) -> int:
        """Enqueue upserts with every synced field of every entity (initial publish). Returns the op count."""
        ...


class AssetIndexRecorderPort(Protocol):
    """Explicit `asset_index` ops emitted by the OCR and embedding services after a successful index write."""

    async def record_ocr(
        self, asset_id: str, *, ocr_text: str, pdf_pages: Sequence[tuple[int, str]], language: str | None = None
    ) -> None: ...

    async def record_embedding(
        self, asset_id: str, *, provider: str, dimensions: int, vector: Sequence[float]
    ) -> None: ...
