from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from bento.domain.errors import ValidationFailedError

SYNC_BATCH_MARKER = "sync-batch"
SYNC_PROTOCOL_VERSION = 1


class SyncEntity(StrEnum):
    FOLDER = "folder"
    ASSET = "asset"
    ALBUM = "album"
    ALBUM_ITEM = "album_item"
    BLOB = "blob"
    THUMBNAIL = "thumbnail"
    ASSET_INDEX = "asset_index"
    DEVICE = "device"


SYNCED_FIELDS: Mapping[SyncEntity, frozenset[str]] = {
    SyncEntity.FOLDER: frozenset({"name", "parent_id", "created_at", "deleted_at"}),
    SyncEntity.ASSET: frozenset(
        {
            "kind",
            "mode",
            "folder_id",
            "filename",
            "original_filename",
            "mime_type",
            "size_bytes",
            "sha256",
            "taken_at",
            "exif",
            "favorite",
            "created_at",
            "deleted_at",
        }
    ),
    SyncEntity.ALBUM: frozenset({"title", "created_at", "deleted_at"}),
    SyncEntity.ALBUM_ITEM: frozenset({"album_id", "asset_id", "created_at", "removed"}),
    SyncEntity.BLOB: frozenset(
        {"asset_id", "kind", "size_bytes", "sha256", "encryption_mode", "key_epoch", "format_version", "parts"}
    ),
    SyncEntity.THUMBNAIL: frozenset({"asset_id", "blob_id", "width", "height"}),
    SyncEntity.ASSET_INDEX: frozenset({"ocr_text", "pdf_pages", "language", "embedding"}),
    SyncEntity.DEVICE: frozenset({"name", "platform", "public_key", "telegram_auth_hash", "added_at", "removed_at"}),
}


class SyncOpKind(StrEnum):
    UPSERT = "upsert"
    PURGE = "purge"


class SyncMessageKind(StrEnum):
    BATCH = "batch"
    SNAPSHOT = "snapshot"
    KEYS = "keys"
    PAIRING = "pairing"
    HEADER = "header"

    @property
    def suffix(self) -> str:
        return _SUFFIXES[self]

    @classmethod
    def from_filename(cls, filename: str) -> SyncMessageKind | None:
        for kind, suffix in _SUFFIXES.items():
            if suffix and filename.endswith(suffix):
                return kind
        return None


_SUFFIXES = {
    SyncMessageKind.BATCH: ".bsync",
    SyncMessageKind.SNAPSHOT: ".bsnap",
    SyncMessageKind.KEYS: ".bkeys",
    SyncMessageKind.PAIRING: ".bpair",
    SyncMessageKind.HEADER: "",
}

_HLC_PATTERN = re.compile(r"^(\d{16})-(\d{6})-(dev_[0-9a-zA-Z_]+)$")
_MAX_COUNTER = 999_999


@dataclass(frozen=True, slots=True, order=True)
class Hlc:
    """Hybrid logical clock. Ordering of the formatted string equals ordering of the tuple."""

    physical_ms: int
    counter: int
    device_id: str

    def __post_init__(self) -> None:
        if self.physical_ms < 0 or not 0 <= self.counter <= _MAX_COUNTER:
            raise ValidationFailedError("Invalid HLC components")
        if not self.device_id.startswith("dev_"):
            raise ValidationFailedError("HLC device id must start with dev_")

    def format(self) -> str:
        return f"{self.physical_ms:016d}-{self.counter:06d}-{self.device_id}"

    @classmethod
    def parse(cls, value: str) -> Hlc:
        match = _HLC_PATTERN.match(value)
        if match is None:
            raise ValidationFailedError("Invalid HLC", {"value": value})
        return cls(int(match.group(1)), int(match.group(2)), match.group(3))

    @classmethod
    def zero(cls, device_id: str) -> Hlc:
        return cls(0, 0, device_id)


def hlc_tick(last: Hlc, now_ms: int) -> Hlc:
    """Next local HLC after `last` given the wall clock."""
    if now_ms > last.physical_ms:
        return Hlc(now_ms, 0, last.device_id)
    return _bump(last.physical_ms, last.counter, last.device_id)


def hlc_receive(last: Hlc, remote: Hlc, now_ms: int) -> Hlc:
    """Local HLC after observing a remote HLC; always greater than both."""
    physical = max(last.physical_ms, remote.physical_ms, now_ms)
    if physical == last.physical_ms == remote.physical_ms:
        return _bump(physical, max(last.counter, remote.counter), last.device_id)
    if physical == last.physical_ms:
        return _bump(physical, last.counter, last.device_id)
    if physical == remote.physical_ms:
        return _bump(physical, remote.counter, last.device_id)
    return Hlc(physical, 0, last.device_id)


def _bump(physical_ms: int, counter: int, device_id: str) -> Hlc:
    if counter >= _MAX_COUNTER:
        return Hlc(physical_ms + 1, 0, device_id)
    return Hlc(physical_ms, counter + 1, device_id)


@dataclass(frozen=True, slots=True)
class SyncOperation:
    op_id: str
    hlc: str
    device_id: str
    entity: SyncEntity
    entity_id: str
    kind: SyncOpKind
    fields: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Hlc.parse(self.hlc)
        if not self.entity_id.strip():
            raise ValidationFailedError("Sync operation entity id is required")
        unknown = set(self.fields) - SYNCED_FIELDS[self.entity]
        if unknown:
            raise ValidationFailedError("Sync operation has unsynced fields", {"fields": sorted(unknown)})
        if self.kind == SyncOpKind.PURGE and self.fields:
            raise ValidationFailedError("Purge operations carry no fields")

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": self.op_id,
            "hlc": self.hlc,
            "device": self.device_id,
            "entity": self.entity.value,
            "id": self.entity_id,
            "kind": self.kind.value,
            "fields": self.fields,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SyncOperation:
        try:
            return cls(
                op_id=str(payload["op"]),
                hlc=str(payload["hlc"]),
                device_id=str(payload["device"]),
                entity=SyncEntity(payload["entity"]),
                entity_id=str(payload["id"]),
                kind=SyncOpKind(payload["kind"]),
                fields=dict(payload.get("fields") or {}),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationFailedError("Invalid sync operation") from exc


@dataclass(frozen=True, slots=True)
class SyncBatch:
    batch_id: str
    device_id: str
    ops: tuple[SyncOperation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "bento": SYNC_BATCH_MARKER,
            "v": SYNC_PROTOCOL_VERSION,
            "batch": self.batch_id,
            "device": self.device_id,
            "ops": [op.to_dict() for op in self.ops],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SyncBatch:
        if payload.get("bento") != SYNC_BATCH_MARKER or payload.get("v") != SYNC_PROTOCOL_VERSION:
            raise ValidationFailedError("Invalid sync batch")
        try:
            return cls(
                batch_id=str(payload["batch"]),
                device_id=str(payload["device"]),
                ops=tuple(SyncOperation.from_dict(item) for item in payload["ops"]),
            )
        except (KeyError, TypeError) as exc:
            raise ValidationFailedError("Invalid sync batch") from exc


def fields_to_apply(op: SyncOperation, clocks: Mapping[str, str]) -> dict[str, Any]:
    """Last-writer-wins per field: keep only fields whose stored clock is older than the op."""
    return {name: value for name, value in op.fields.items() if clocks.get(name, "") < op.hlc}


@dataclass(frozen=True, slots=True)
class SyncMessageRef:
    message_id: int
    kind: SyncMessageKind
    filename: str
    size_bytes: int
    created_at: datetime
    text: str | None = None


class SyncState(StrEnum):
    DISABLED = "disabled"
    IDLE = "idle"
    SYNCING = "syncing"
    BOOTSTRAPPING = "bootstrapping"
    OFFLINE = "offline"
    PAUSED = "paused"
    WAITING = "waiting"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class BootstrapProgress:
    done: int
    total: int


@dataclass(frozen=True, slots=True)
class SyncStatus:
    state: SyncState
    pending_ops: int = 0
    last_push_at: datetime | None = None
    last_pull_at: datetime | None = None
    bootstrap: BootstrapProgress | None = None
    waiting_until: datetime | None = None
    error_code: str | None = None
