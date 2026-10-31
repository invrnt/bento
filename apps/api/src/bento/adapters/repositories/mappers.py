from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bento.domain.assets import Asset, AssetKind, AssetMetadata, AssetMode, ProcessingState
from bento.domain.devices import Device, DevicePlatform
from bento.domain.drive import Folder
from bento.domain.jobs import Job, JobStatus, JobType
from bento.domain.manifest import ManifestEntityType, ManifestEvent, ManifestEventType
from bento.domain.photos import Album
from bento.domain.security import EncryptionMetadata, EncryptionMode
from bento.domain.storage import BlobKind, BlobPart, BlobRef, StorageBackend
from bento.infrastructure.db.models import (
    AlbumModel,
    AssetModel,
    BlobPartModel,
    BlobRefModel,
    DeviceModel,
    FolderModel,
    JobModel,
    ManifestEventModel,
)


def aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def require_aware(value: datetime) -> datetime:
    result = aware(value)
    if result is None:
        raise ValueError("datetime value is required")
    return result


def asset_from_model(model: AssetModel) -> Asset:
    exif = model.exif_json if isinstance(model.exif_json, dict) else None
    return Asset(
        id=model.id,
        kind=AssetKind(model.kind),
        mode=AssetMode(model.mode),
        folder_id=model.folder_id,
        filename=model.filename,
        metadata=AssetMetadata(
            original_filename=model.original_filename,
            mime_type=model.mime_type,
            size_bytes=model.size_bytes,
            sha256=model.sha256,
            taken_at=aware(model.taken_at),
            exif=exif,
        ),
        processing_state=ProcessingState(model.processing_state),
        favorite=model.favorite,
        created_at=require_aware(model.created_at),
        updated_at=require_aware(model.updated_at),
        deleted_at=aware(model.deleted_at),
    )


def asset_to_model(asset: Asset) -> AssetModel:
    return AssetModel(
        id=asset.id,
        kind=asset.kind.value,
        mode=asset.mode.value,
        folder_id=asset.folder_id,
        filename=asset.filename,
        original_filename=asset.metadata.original_filename,
        mime_type=asset.metadata.mime_type,
        size_bytes=asset.metadata.size_bytes,
        sha256=asset.metadata.sha256,
        taken_at=asset.metadata.taken_at,
        exif_json=dict(asset.metadata.exif) if asset.metadata.exif is not None else None,
        processing_state=asset.processing_state.value,
        favorite=asset.favorite,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        deleted_at=asset.deleted_at,
    )


def folder_from_model(model: FolderModel) -> Folder:
    return Folder(
        id=model.id,
        name=model.name,
        parent_id=model.parent_id,
        created_at=require_aware(model.created_at),
        updated_at=require_aware(model.updated_at),
        deleted_at=aware(model.deleted_at),
    )


def folder_to_model(folder: Folder) -> FolderModel:
    return FolderModel(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
        deleted_at=folder.deleted_at,
    )


def album_from_model(model: AlbumModel, asset_ids: frozenset[str]) -> Album:
    return Album(
        id=model.id,
        title=model.title,
        asset_ids=asset_ids,
        created_at=require_aware(model.created_at),
        updated_at=require_aware(model.updated_at),
        deleted_at=aware(model.deleted_at),
    )


def album_to_model(album: Album) -> AlbumModel:
    return AlbumModel(
        id=album.id,
        title=album.title,
        created_at=album.created_at,
        updated_at=album.updated_at,
        deleted_at=album.deleted_at,
    )


def job_from_model(model: JobModel) -> Job:
    payload: dict[str, Any] = model.payload_json if isinstance(model.payload_json, dict) else {}
    return Job(
        id=model.id,
        type=JobType(model.type),
        status=JobStatus(model.status),
        priority=model.priority,
        payload=payload,
        attempts=model.attempts,
        max_attempts=model.max_attempts,
        created_at=require_aware(model.created_at),
        updated_at=require_aware(model.updated_at),
        asset_id=model.asset_id,
        locked_by=model.locked_by,
        locked_at=aware(model.locked_at),
        run_after=aware(model.run_after),
        error=model.error,
    )


def job_to_model(job: Job) -> JobModel:
    return JobModel(
        id=job.id,
        type=job.type.value,
        status=job.status.value,
        priority=job.priority,
        payload_json=dict(job.payload),
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        asset_id=job.asset_id,
        locked_by=job.locked_by,
        locked_at=job.locked_at,
        run_after=job.run_after,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def manifest_event_from_model(model: ManifestEventModel) -> ManifestEvent:
    payload: dict[str, Any] = model.payload_json if isinstance(model.payload_json, dict) else {}
    return ManifestEvent(
        id=model.id,
        type=ManifestEventType(model.type),
        entity_type=ManifestEntityType(model.entity_type),
        entity_id=model.entity_id,
        payload=payload,
        created_at=require_aware(model.created_at),
    )


def blob_ref_from_model(model: BlobRefModel) -> BlobRef:
    return BlobRef(
        id=model.id,
        asset_id=model.asset_id,
        backend=StorageBackend(model.backend),
        kind=BlobKind(model.kind),
        object_key=model.object_key,
        size_bytes=model.size_bytes,
        sha256=model.sha256,
        chat_id=model.chat_id,
        message_id=model.message_id,
        file_id=model.file_id,
        file_unique_id=model.file_unique_id,
        encryption=EncryptionMetadata(
            mode=EncryptionMode(model.encryption_mode),
            key_id=model.encryption_key_id,
            nonce=model.encryption_nonce,
            tag=model.encryption_tag,
            key_epoch=model.key_epoch,
            format_version=model.format_version if model.format_version is not None else 1,
        ),
        parts=tuple(
            BlobPart(
                index=part.part_index,
                channel_id=part.channel_id,
                message_id=part.message_id,
                size_bytes=part.size_bytes,
            )
            for part in sorted(model.parts, key=lambda item: item.part_index)
        ),
    )


def blob_ref_to_model(blob_ref: BlobRef, *, created_at: datetime) -> BlobRefModel:
    return BlobRefModel(
        id=blob_ref.id,
        asset_id=blob_ref.asset_id,
        backend=blob_ref.backend.value,
        kind=blob_ref.kind.value,
        object_key=blob_ref.object_key,
        size_bytes=blob_ref.size_bytes,
        sha256=blob_ref.sha256,
        chat_id=blob_ref.chat_id,
        message_id=blob_ref.message_id,
        file_id=blob_ref.file_id,
        file_unique_id=blob_ref.file_unique_id,
        encryption_mode=blob_ref.encryption.mode.value,
        encryption_key_id=blob_ref.encryption.key_id,
        encryption_nonce=blob_ref.encryption.nonce,
        encryption_tag=blob_ref.encryption.tag,
        key_epoch=blob_ref.encryption.key_epoch,
        format_version=blob_ref.encryption.format_version,
        created_at=created_at,
        parts=[
            BlobPartModel(
                blob_ref_id=blob_ref.id,
                part_index=part.index,
                channel_id=part.channel_id,
                message_id=part.message_id,
                size_bytes=part.size_bytes,
            )
            for part in blob_ref.parts
        ],
    )


def device_from_model(model: DeviceModel) -> Device:
    try:
        platform = DevicePlatform(model.platform)
    except ValueError:
        platform = DevicePlatform.OTHER
    return Device(
        id=model.id,
        name=model.name,
        platform=platform,
        public_key=model.public_key,
        added_at=require_aware(model.added_at),
        telegram_auth_hash=model.telegram_auth_hash,
        last_seen_at=aware(model.last_seen_at),
        removed_at=aware(model.removed_at),
        current=model.is_current,
    )


def device_to_model(device: Device) -> DeviceModel:
    return DeviceModel(
        id=device.id,
        name=device.name,
        platform=device.platform.value,
        public_key=device.public_key,
        telegram_auth_hash=device.telegram_auth_hash,
        added_at=device.added_at,
        last_seen_at=device.last_seen_at,
        removed_at=device.removed_at,
        is_current=device.current,
    )
