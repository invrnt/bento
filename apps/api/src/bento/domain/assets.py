from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from bento.domain.errors import ValidationFailedError


class AssetKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    PDF = "pdf"
    AUDIO = "audio"
    OTHER = "other"


class AssetMode(StrEnum):
    DRIVE = "drive"
    PHOTOS = "photos"


class AssetOrigin(StrEnum):
    """How this device obtained an asset. Device-local: never synced."""

    DEVICE = "device"
    """Picked by the person on this device (upload, Send-to, folder backup)."""
    TELEGRAM_INBOX = "telegram_inbox"
    TELEGRAM_IMPORT = "telegram_import"

    @property
    def from_telegram(self) -> bool:
        return self in {AssetOrigin.TELEGRAM_INBOX, AssetOrigin.TELEGRAM_IMPORT}


class ProcessingState(StrEnum):
    CREATED = "created"
    BLOB_STORED = "blob_stored"
    METADATA_EXTRACTED = "metadata_extracted"
    THUMBNAIL_PENDING = "thumbnail_pending"
    THUMBNAIL_READY = "thumbnail_ready"
    OCR_PENDING = "ocr_pending"
    OCR_READY = "ocr_ready"
    EMBEDDING_PENDING = "embedding_pending"
    EMBEDDING_READY = "embedding_ready"
    INDEXED = "indexed"
    FAILED_PARTIAL = "failed_partial"
    FAILED = "failed"


_TRANSITIONS: Mapping[ProcessingState, frozenset[ProcessingState]] = MappingProxyType(
    {
        ProcessingState.CREATED: frozenset({ProcessingState.BLOB_STORED, ProcessingState.FAILED}),
        ProcessingState.BLOB_STORED: frozenset(
            {
                ProcessingState.METADATA_EXTRACTED,
                ProcessingState.THUMBNAIL_PENDING,
                ProcessingState.INDEXED,
                ProcessingState.FAILED_PARTIAL,
            }
        ),
        ProcessingState.METADATA_EXTRACTED: frozenset(
            {ProcessingState.THUMBNAIL_PENDING, ProcessingState.OCR_PENDING, ProcessingState.INDEXED}
        ),
        ProcessingState.THUMBNAIL_PENDING: frozenset(
            {
                ProcessingState.THUMBNAIL_READY,
                ProcessingState.OCR_PENDING,
                ProcessingState.INDEXED,
                ProcessingState.FAILED_PARTIAL,
            }
        ),
        ProcessingState.THUMBNAIL_READY: frozenset(
            {ProcessingState.OCR_PENDING, ProcessingState.EMBEDDING_PENDING, ProcessingState.INDEXED}
        ),
        ProcessingState.OCR_PENDING: frozenset(
            {ProcessingState.OCR_READY, ProcessingState.EMBEDDING_PENDING, ProcessingState.FAILED_PARTIAL}
        ),
        ProcessingState.OCR_READY: frozenset({ProcessingState.EMBEDDING_PENDING, ProcessingState.INDEXED}),
        ProcessingState.EMBEDDING_PENDING: frozenset(
            {ProcessingState.EMBEDDING_READY, ProcessingState.INDEXED, ProcessingState.FAILED_PARTIAL}
        ),
        ProcessingState.EMBEDDING_READY: frozenset({ProcessingState.INDEXED}),
        ProcessingState.INDEXED: frozenset({ProcessingState.FAILED_PARTIAL}),
        ProcessingState.FAILED_PARTIAL: frozenset(
            {
                ProcessingState.THUMBNAIL_PENDING,
                ProcessingState.OCR_PENDING,
                ProcessingState.EMBEDDING_PENDING,
                ProcessingState.INDEXED,
            }
        ),
        ProcessingState.FAILED: frozenset({ProcessingState.CREATED}),
    }
)
_SETTLED_STATES = frozenset({ProcessingState.INDEXED, ProcessingState.FAILED_PARTIAL, ProcessingState.FAILED})


@dataclass(frozen=True, slots=True)
class AssetMetadata:
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    taken_at: datetime | None = None
    exif: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.original_filename.strip():
            raise ValidationFailedError("Asset filename is required")
        if not self.mime_type.strip():
            raise ValidationFailedError("Asset MIME type is required")
        if self.size_bytes < 0:
            raise ValidationFailedError("Asset size cannot be negative", {"size_bytes": self.size_bytes})
        if len(self.sha256) != 64:
            raise ValidationFailedError("Asset sha256 must be 64 hexadecimal characters", {"sha256": self.sha256})
        try:
            int(self.sha256, 16)
        except ValueError as exc:
            raise ValidationFailedError("Asset sha256 must be hexadecimal", {"sha256": self.sha256}) from exc


@dataclass(frozen=True, slots=True)
class Asset:
    id: str
    kind: AssetKind
    mode: AssetMode
    folder_id: str | None
    filename: str
    metadata: AssetMetadata
    processing_state: ProcessingState
    favorite: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    origin: AssetOrigin | None = AssetOrigin.DEVICE
    """Device-local provenance; None when the asset arrived from another device (unknown here)."""

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValidationFailedError("Asset id is required")
        if not self.filename.strip():
            raise ValidationFailedError("Asset filename is required")

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def ai_indexing_allowed(self) -> bool:
        """OCR and embeddings run only on the person's own files from this device.

        Telegram's API terms forbid feeding data obtained from Telegram (Inbox, imports) to ML models. Assets that
        arrived from another device are never indexed here either: that device publishes its own index.
        """
        return self.origin is AssetOrigin.DEVICE

    def finish_processing(self, at: datetime, *, failed: bool = False) -> Asset:
        """The terminal state once no processing is pending: ready (`indexed`), or `failed_partial` after a step
        failed for good. Settled assets stay as they are."""
        if self.processing_state in _SETTLED_STATES:
            return self
        target = ProcessingState.FAILED_PARTIAL if failed else ProcessingState.INDEXED
        if target not in _TRANSITIONS[self.processing_state]:
            return self
        return self.transition_to(target, at)

    def transition_to(self, state: ProcessingState, at: datetime) -> Asset:
        if state == self.processing_state:
            return replace(self, updated_at=at)
        allowed = _TRANSITIONS[self.processing_state]
        if state not in allowed:
            raise ValidationFailedError(
                "Invalid asset processing state transition",
                {"from": self.processing_state.value, "to": state.value},
            )
        return replace(self, processing_state=state, updated_at=at)

    def rename(self, filename: str, at: datetime) -> Asset:
        if not filename.strip():
            raise ValidationFailedError("Asset filename is required")
        return replace(self, filename=filename, updated_at=at)

    def move_to(self, folder_id: str | None, at: datetime) -> Asset:
        return replace(self, folder_id=folder_id, updated_at=at)

    def toggle_favorite(self, at: datetime) -> Asset:
        return replace(self, favorite=not self.favorite, updated_at=at)

    def mark_deleted(self, at: datetime) -> Asset:
        return replace(self, deleted_at=at, updated_at=at)


def infer_asset_kind(mime_type: str) -> AssetKind:
    normalized = mime_type.lower()
    if normalized.startswith("image/"):
        return AssetKind.IMAGE
    if normalized.startswith("video/"):
        return AssetKind.VIDEO
    if normalized == "application/pdf":
        return AssetKind.PDF
    if normalized.startswith("audio/"):
        return AssetKind.AUDIO
    if normalized.startswith("text/") or normalized in {
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }:
        return AssetKind.DOCUMENT
    return AssetKind.OTHER


def supports_ocr(kind: AssetKind) -> bool:
    return kind in {AssetKind.IMAGE, AssetKind.PDF, AssetKind.DOCUMENT}


def infer_asset_mode(kind: AssetKind) -> AssetMode:
    if kind in {AssetKind.IMAGE, AssetKind.VIDEO}:
        return AssetMode.PHOTOS
    return AssetMode.DRIVE
