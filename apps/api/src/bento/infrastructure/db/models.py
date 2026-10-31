from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bento.infrastructure.db.base import Base


class FolderModel(Base):
    __tablename__ = "folders"
    __table_args__ = (
        Index("ix_folders_parent_id", "parent_id"),
        Index("ix_folders_deleted_at", "deleted_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("folders.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssetModel(Base):
    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_folder_id", "folder_id"),
        Index("ix_assets_sha256", "sha256"),
        Index("ix_assets_mode_deleted", "mode", "deleted_at"),
        Index("ix_assets_taken_at", "taken_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    folder_id: Mapped[str | None] = mapped_column(ForeignKey("folders.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exif_json: Mapped[dict[str, Any] | None] = mapped_column("exif", JSON)
    processing_state: Mapped[str] = mapped_column(String(64), nullable=False)
    favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str | None] = mapped_column(String(32))
    """Device-local provenance (`AssetOrigin`), not synced; NULL for assets that arrived from another device."""


class AlbumModel(Base):
    __tablename__ = "albums"
    __table_args__ = (Index("ix_albums_deleted_at", "deleted_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlbumAssetModel(Base):
    __tablename__ = "album_assets"
    __table_args__ = (Index("ix_album_assets_asset_id", "asset_id"),)

    album_id: Mapped[str] = mapped_column(ForeignKey("albums.id", ondelete="CASCADE"), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BlobRefModel(Base):
    __tablename__ = "blob_refs"
    __table_args__ = (Index("ix_blob_refs_asset_id", "asset_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"))
    backend: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    chat_id: Mapped[str | None] = mapped_column(String(128))
    message_id: Mapped[str | None] = mapped_column(String(128))
    file_id: Mapped[str | None] = mapped_column(String(512))
    file_unique_id: Mapped[str | None] = mapped_column(String(512))
    encryption_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    encryption_key_id: Mapped[str | None] = mapped_column(String(128))
    encryption_nonce: Mapped[str | None] = mapped_column(String(64))
    encryption_tag: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    key_epoch: Mapped[int | None] = mapped_column(Integer)
    format_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    cipher_header_sha256: Mapped[str | None] = mapped_column(String(64))
    """b64url SHA-256 of the 36-byte blob v2 header; binds the remote ciphertext to this ref."""
    remote_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parts: Mapped[list[BlobPartModel]] = relationship(
        order_by="BlobPartModel.part_index",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )


class BlobPartModel(Base):
    __tablename__ = "blob_parts"

    blob_ref_id: Mapped[str] = mapped_column(ForeignKey("blob_refs.id", ondelete="CASCADE"), primary_key=True)
    part_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False)
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ThumbnailModel(Base):
    __tablename__ = "thumbnails"
    __table_args__ = (Index("ix_thumbnails_asset_id", "asset_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    blob_ref_id: Mapped[str | None] = mapped_column(ForeignKey("blob_refs.id", ondelete="SET NULL"))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AssetTextModel(Base):
    __tablename__ = "asset_text"
    __table_args__ = (
        Index("ix_asset_text_asset_id", "asset_id"),
        Index("ix_asset_text_source", "source"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AssetEmbeddingModel(Base):
    __tablename__ = "asset_embeddings"
    __table_args__ = (
        Index("ix_asset_embeddings_asset_id", "asset_id"),
        Index("ix_asset_embeddings_provider", "provider"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    vector_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PDFPageModel(Base):
    __tablename__ = "pdf_pages"
    __table_args__ = (Index("ix_pdf_pages_asset_id", "asset_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OCRBlockModel(Base):
    __tablename__ = "ocr_blocks"
    __table_args__ = (Index("ix_ocr_blocks_asset_id", "asset_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobModel(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_claim", "status", "run_after", "priority", "created_at"),
        Index("ix_jobs_asset_id", "asset_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column("payload", JSON, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"))
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ManifestEventModel(Base):
    __tablename__ = "manifest_events"
    __table_args__ = (
        Index("ix_manifest_events_entity", "entity_type", "entity_id"),
        Index("ix_manifest_events_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column("payload", JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SettingModel(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(String(2048), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SettingsMetaModel(Base):
    __tablename__ = "settings_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SettingSecretReferenceModel(Base):
    __tablename__ = "setting_secret_references"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    reference: Mapped[str | None] = mapped_column(String(256))
    configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SyncOutboxModel(Base):
    __tablename__ = "sync_outbox"
    __table_args__ = {"sqlite_autoincrement": True}

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    op_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    hlc: Mapped[str] = mapped_column(String(96), nullable=False)
    entity: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    fields_json: Mapped[dict[str, Any]] = mapped_column("fields", JSON, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SyncFieldClockModel(Base):
    __tablename__ = "sync_field_clocks"

    entity: Mapped[str] = mapped_column(String(32), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    field: Mapped[str] = mapped_column(String(64), primary_key=True)
    hlc: Mapped[str] = mapped_column(String(96), nullable=False)


class SyncPurgedModel(Base):
    __tablename__ = "sync_purged"

    entity: Mapped[str] = mapped_column(String(32), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    hlc: Mapped[str] = mapped_column(String(96), nullable=False)
    purged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SyncAppliedBatchModel(Base):
    __tablename__ = "sync_applied_batches"

    batch_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SyncStateModel(Base):
    __tablename__ = "sync_state"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DeviceModel(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    public_key: Mapped[str] = mapped_column(String(128), nullable=False)
    telegram_auth_hash: Mapped[int | None] = mapped_column(BigInteger)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    introduced_by: Mapped[str | None] = mapped_column(String(64))
    """Device-local: id of the device whose sync data first created this row here; NULL when created locally."""
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Device-local: when the person acknowledged a device first seen through sync (or it predates this device)."""


class BackupSourceModel(Base):
    __tablename__ = "backup_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    path: Mapped[str] = mapped_column(String(4096), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))


class BackupFileModel(Base):
    __tablename__ = "backup_files"
    __table_args__ = (Index("ix_backup_files_state", "state"),)

    source_id: Mapped[str] = mapped_column(ForeignKey("backup_sources.id", ondelete="CASCADE"), primary_key=True)
    relative_path: Mapped[str] = mapped_column(String(4096), primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mtime_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    asset_id: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UploadSessionModel(Base):
    __tablename__ = "upload_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str | None] = mapped_column(String(64))
    blob_ref_id: Mapped[str | None] = mapped_column(String(64))
    source_path: Mapped[str] = mapped_column(String(4096), nullable=False)
    blob_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    file_salt: Mapped[bytes] = mapped_column(LargeBinary(16), nullable=False)
    nonce_prefix: Mapped[bytes] = mapped_column(LargeBinary(7), nullable=False)
    segment_size: Mapped[int] = mapped_column(Integer, nullable=False)
    plaintext_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ciphertext_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    completed_parts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CacheEntryModel(Base):
    __tablename__ = "cache_entries"
    __table_args__ = (Index("ix_cache_entries_last_accessed_at", "last_accessed_at"),)

    blob_ref_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    path: Mapped[str] = mapped_column(String(4096), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InboxItemModel(Base):
    __tablename__ = "inbox_items"

    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    asset_id: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
