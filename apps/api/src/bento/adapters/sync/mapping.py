"""Tracked ORM models ↔ synced entities: column → field mapping and JSON-safe values.

Values on the wire: timestamps are ISO-8601 UTC strings, `exif` is a JSON object, blob `parts` are
`[{index, channel_id, message_id, size_bytes}]` with integer ids, everything else is a JSON scalar.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from bento.domain.storage import StorageBackend
from bento.domain.sync import SyncEntity
from bento.infrastructure.db.models import (
    AlbumAssetModel,
    AlbumModel,
    AssetModel,
    BlobPartModel,
    BlobRefModel,
    DeviceModel,
    FolderModel,
    ThumbnailModel,
)

REMOVED_FIELD = "removed"
PARTS_FIELD = "parts"
TELEGRAM_BACKEND = StorageBackend.TELEGRAM.value
REMOTE_OBJECT_KEY_PREFIX = "vault/"
"""`object_key` of blob refs created from peers' ops (remote refs are self-describing through their parts)."""


@dataclass(frozen=True, slots=True)
class TrackedModel:
    entity: SyncEntity
    model: type[Any]
    columns: Mapping[str, str]
    """Synced field → mapped attribute name."""
    identity_fields: frozenset[str] = frozenset()
    """Fields always sent with upserts (needed by the hold rule on any later update)."""
    datetimes: frozenset[str] = frozenset()

    @property
    def table(self) -> str:
        return str(self.model.__tablename__)


FOLDER = TrackedModel(
    SyncEntity.FOLDER,
    FolderModel,
    {"name": "name", "parent_id": "parent_id", "created_at": "created_at", "deleted_at": "deleted_at"},
    datetimes=frozenset({"created_at", "deleted_at"}),
)
ALBUM = TrackedModel(
    SyncEntity.ALBUM,
    AlbumModel,
    {"title": "title", "created_at": "created_at", "deleted_at": "deleted_at"},
    datetimes=frozenset({"created_at", "deleted_at"}),
)
ASSET = TrackedModel(
    SyncEntity.ASSET,
    AssetModel,
    {
        "kind": "kind",
        "mode": "mode",
        "folder_id": "folder_id",
        "filename": "filename",
        "original_filename": "original_filename",
        "mime_type": "mime_type",
        "size_bytes": "size_bytes",
        "sha256": "sha256",
        "taken_at": "taken_at",
        "exif": "exif_json",
        "favorite": "favorite",
        "created_at": "created_at",
        "deleted_at": "deleted_at",
    },
    datetimes=frozenset({"taken_at", "created_at", "deleted_at"}),
)
BLOB = TrackedModel(
    SyncEntity.BLOB,
    BlobRefModel,
    {
        "asset_id": "asset_id",
        "kind": "kind",
        "size_bytes": "size_bytes",
        "sha256": "sha256",
        "encryption_mode": "encryption_mode",
        "key_epoch": "key_epoch",
        "format_version": "format_version",
    },
    identity_fields=frozenset({"asset_id", "kind"}),
)
THUMBNAIL = TrackedModel(
    SyncEntity.THUMBNAIL,
    ThumbnailModel,
    {"asset_id": "asset_id", "blob_id": "blob_ref_id", "width": "width", "height": "height"},
    identity_fields=frozenset({"asset_id"}),
)
ALBUM_ITEM = TrackedModel(
    SyncEntity.ALBUM_ITEM,
    AlbumAssetModel,
    {"album_id": "album_id", "asset_id": "asset_id", "created_at": "created_at"},
    identity_fields=frozenset({"album_id", "asset_id"}),
    datetimes=frozenset({"created_at"}),
)
DEVICE = TrackedModel(
    SyncEntity.DEVICE,
    DeviceModel,
    {
        "name": "name",
        "platform": "platform",
        "public_key": "public_key",
        "telegram_auth_hash": "telegram_auth_hash",
        "added_at": "added_at",
        "removed_at": "removed_at",
    },
    datetimes=frozenset({"added_at", "removed_at"}),
)

TRACKED_MODELS: tuple[TrackedModel, ...] = (FOLDER, ALBUM, ASSET, BLOB, THUMBNAIL, ALBUM_ITEM, DEVICE)
"""Emission order within one flush: parents before children."""
BY_MODEL: Mapping[type[Any], TrackedModel] = {tracked.model: tracked for tracked in TRACKED_MODELS}
BY_ENTITY: Mapping[SyncEntity, TrackedModel] = {tracked.entity: tracked for tracked in TRACKED_MODELS}
BY_TABLE: Mapping[str, TrackedModel] = {tracked.table: tracked for tracked in TRACKED_MODELS}
BLOB_PARTS_TABLE = str(BlobPartModel.__tablename__)
ORDER: Mapping[SyncEntity, int] = {
    **{tracked.entity: index for index, tracked in enumerate(TRACKED_MODELS)},
    SyncEntity.ASSET_INDEX: len(TRACKED_MODELS),
}


def entity_key(tracked: TrackedModel, model: Any) -> str:
    if tracked.entity == SyncEntity.ALBUM_ITEM:
        return album_item_key(model.album_id, model.asset_id)
    return str(model.id)


def album_item_key(album_id: str, asset_id: str) -> str:
    return f"{album_id}:{asset_id}"


def split_album_item_key(key: str) -> tuple[str, str]:
    album_id, separator, asset_id = key.partition(":")
    if not separator or not album_id or not asset_id:
        raise ValueError("album item keys look like <album_id>:<asset_id>")
    return album_id, asset_id


def to_wire(tracked: TrackedModel, field: str, value: Any) -> Any:
    if field in tracked.datetimes:
        return format_datetime(value)
    if field == "exif":
        return dict(value) if isinstance(value, Mapping) else None
    return value


def from_wire(tracked: TrackedModel, field: str, value: Any) -> Any:
    """Column value for a wire value; raises `ValueError`/`TypeError` on malformed input."""
    if field in tracked.datetimes:
        return parse_datetime(value)
    if field == "exif":
        if value is not None and not isinstance(value, Mapping):
            raise TypeError("exif must be an object")
        return dict(value) if value is not None else None
    if field in {"favorite"}:
        if not isinstance(value, bool):
            raise TypeError(f"{field} must be a boolean")
        return value
    if field in {"size_bytes", "format_version"}:
        return _int(value)
    if field in {"key_epoch", "telegram_auth_hash", "width", "height"}:
        return None if value is None else _int(value)
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    return value


def model_fields(tracked: TrackedModel, model: Any) -> dict[str, Any]:
    return {field: to_wire(tracked, field, getattr(model, attribute)) for field, attribute in tracked.columns.items()}


def row_fields(tracked: TrackedModel, model: Any) -> dict[str, Any]:
    """Every synced field of a persisted row (initial publish, snapshots)."""
    fields = model_fields(tracked, model)
    if tracked.entity == SyncEntity.ALBUM_ITEM:
        fields[REMOVED_FIELD] = False
    if tracked.entity == SyncEntity.BLOB:
        fields[PARTS_FIELD] = parts_to_wire(model.parts)
    return fields


def parts_to_wire(parts: Any) -> list[dict[str, Any]]:
    return [
        {
            "index": part.part_index,
            "channel_id": _int_or_text(part.channel_id),
            "message_id": _int_or_text(part.message_id),
            "size_bytes": int(part.size_bytes),
        }
        for part in sorted(parts, key=lambda item: item.part_index)
    ]


def parts_from_wire(blob_id: str, value: Any) -> list[BlobPartModel]:
    if not isinstance(value, list):
        raise TypeError("parts must be a list")
    parts = [
        BlobPartModel(
            blob_ref_id=blob_id,
            part_index=_int(item["index"]),
            channel_id=str(item["channel_id"]),
            message_id=str(item["message_id"]),
            size_bytes=_int(item["size_bytes"]),
        )
        for item in value
    ]
    if sorted(part.part_index for part in parts) != list(range(len(parts))):
        raise ValueError("parts must be contiguous")
    return parts


def format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("timestamps must be ISO-8601 strings")
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def same_value(left: Any, right: Any) -> bool:
    """Equality after normalizing timestamps (SQLite returns naive UTC datetimes)."""
    if isinstance(left, datetime) or isinstance(right, datetime):
        return format_datetime(left) == format_datetime(right)
    return bool(left == right)


def _int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise TypeError("expected an integer")
    return int(value)


def _int_or_text(value: Any) -> int | str:
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)
