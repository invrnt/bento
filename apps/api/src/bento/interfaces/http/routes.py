from __future__ import annotations

import logging
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile

from bento.application.drive import (
    CreateFolderCommand,
    DriveUseCases,
    ListDriveItemsQuery,
    MoveAssetCommand,
    MoveFolderCommand,
    RenameFolderCommand,
    UpdateAssetCommand,
)
from bento.application.ingestion import AssetFileQueryService, AssetIngestionService, UploadedAssetFile
from bento.application.jobs import JobsUseCases, ListJobsQuery
from bento.application.photos import (
    AddAlbumAssetCommand,
    CreateAlbumCommand,
    PhotosUseCases,
    TimelineQuery,
    UpdateAlbumCommand,
)
from bento.application.settings import resolve_model_path
from bento.application.storage_maintenance import StorageMaintenanceService
from bento.domain.assets import Asset, AssetKind, AssetMode
from bento.domain.drive import DriveItem, DriveSort, Folder, SortOrder
from bento.domain.exif import summarize_exif
from bento.domain.errors import AssetNotFoundError, DomainError, UnsupportedMediaTypeError, ValidationFailedError
from bento.domain.jobs import Job, JobType
from bento.domain.photos import Album, TimelineGroup
from bento.domain.storage import BlobKind, BlobRef, StorageBackend
from bento.infrastructure.settings import Settings
from bento.interfaces.http.routes_account import router as account_router
from bento.interfaces.http.routes_activity import router as activity_router
from bento.interfaces.http.routes_android import router as android_router
from bento.interfaces.http.routes_backup import router as backup_router
from bento.interfaces.http.routes_content import pipeline as storage_pipeline
from bento.interfaces.http.routes_content import router as content_router
from bento.interfaces.http.routes_dev import router as dev_router
from bento.interfaces.http.routes_devices import router as devices_router
from bento.interfaces.http.routes_drive_paths import router as drive_paths_router
from bento.interfaces.http.routes_events import router as events_router
from bento.interfaces.http.routes_pairing import router as pairing_router
from bento.interfaces.http.routes_trash import router as trash_router
from bento.interfaces.http.routes_search import router as search_router
from bento.interfaces.http.routes_settings import router as settings_router
from bento.interfaces.http.routes_smart_search import activation_service as smart_search_activation
from bento.interfaces.http.routes_smart_search import live_embeddings_provider
from bento.interfaces.http.routes_smart_search import router as smart_search_router
from bento.interfaces.http.routes_sync import router as sync_router
from bento.interfaces.http.routes_telegram import router as telegram_router
from bento.interfaces.http.routes_vault import router as vault_router

LOGGER = logging.getLogger("bento.http")

router = APIRouter()
router.include_router(search_router)
router.include_router(settings_router)
router.include_router(dev_router)
router.include_router(account_router)
router.include_router(vault_router)
router.include_router(telegram_router)
router.include_router(pairing_router)
router.include_router(devices_router)
router.include_router(content_router)
router.include_router(backup_router)
router.include_router(trash_router)
router.include_router(activity_router)
router.include_router(sync_router)
router.include_router(drive_paths_router)
router.include_router(android_router)
router.include_router(events_router)
router.include_router(smart_search_router)


class HealthResponse(BaseModel):
    status: str
    storage_backend: str
    telegram_configured: bool


class VersionResponse(BaseModel):
    name: str
    version: str
    environment: str


class StorageMaintenanceStatusResponse(BaseModel):
    connection_state: str
    can_reclaim: bool
    fully_remote: bool
    reclaimable_bytes: int
    reclaimable_files: int
    local_blob_count: int
    telegram_blob_count: int


class SettingsResponse(BaseModel):
    storage_backend: str
    worker_concurrency: int
    telegram_configured: bool
    telegram_enabled: bool
    ocr_enabled: bool
    ocr_state: str
    embeddings_enabled: bool
    embeddings_state: str
    model_available: bool
    worker_status: str
    data_paths: dict[str, str]
    storage_maintenance: StorageMaintenanceStatusResponse


class StorageReclaimResponse(BaseModel):
    freed_bytes: int
    deleted_files: int
    retained_bytes: int
    retained_files: int
    skipped_recent_files: int


class ExifSummaryResponse(BaseModel):
    camera_make: str | None = None
    camera_model: str | None = None
    lens_model: str | None = None
    exposure_time_s: float | None = None
    exposure_display: str | None = None
    f_number: float | None = None
    iso: int | None = None
    focal_length_mm: float | None = None
    latitude: float | None = None
    longitude: float | None = None


class AssetResponse(BaseModel):
    id: str
    kind: str
    mode: str
    folder_id: str | None
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    favorite: bool
    processing_state: str
    created_at: str
    updated_at: str
    duplicate: bool = False
    preview_url: str | None = None
    taken_at: str | None = None
    thumbnail_url: str | None = None
    # Timeline items only (`api/android-endpoints.md` §5): grid overlays without extra calls. `width`/`height`
    # are those of the largest stored thumbnail (the aspect ratio the grid needs).
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    remote_state: str | None = None
    thumbnail_etag: str | None = None
    # Where the original is (`api/android-endpoints.md` §6): pinned for offline use, and openable offline.
    offline_pinned: bool = False
    locally_available: bool = False
    exif: ExifSummaryResponse | None = None
    """Parsed camera summary; absent when the file carries no usable EXIF."""


class FolderResponse(BaseModel):
    id: str
    name: str
    parent_id: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None = None


class DriveItemResponse(BaseModel):
    type: str
    id: str
    name: str
    updated_at: str
    asset: AssetResponse | None = None
    folder: FolderResponse | None = None
    item_count: int | None = None
    """Folders only: live direct children (subfolders and files)."""


class DriveBreadcrumbResponse(BaseModel):
    folder_id: str | None
    name: str


class DriveItemsResponse(BaseModel):
    breadcrumbs: list[DriveBreadcrumbResponse] = Field(default_factory=list)
    items: list[DriveItemResponse]
    next_cursor: str | None


class FolderCreateRequest(BaseModel):
    name: str
    parent_id: str | None = None


class FolderPatchRequest(BaseModel):
    name: str | None = None
    parent_id: str | None = None


class AssetPatchRequest(BaseModel):
    name: str


class AssetMoveRequest(BaseModel):
    folder_id: str | None = None


class PhotoTimelineGroupResponse(BaseModel):
    date: str
    assets: list[AssetResponse]


class PhotoTimelineResponse(BaseModel):
    groups: list[PhotoTimelineGroupResponse]
    next_cursor: str | None


class PhotoTimelineMonthResponse(BaseModel):
    month: str
    count: int
    first_cursor: str


class PhotoTimelineIndexResponse(BaseModel):
    months: list[PhotoTimelineMonthResponse]


class OfflinePinResponse(BaseModel):
    asset_id: str
    pinned: bool
    downloading: bool = False


class LocalStorageResponse(BaseModel):
    cache_bytes: int
    cache_files: int
    pinned_bytes: int
    pinned_count: int
    cache_limit_bytes: int
    thumbs_bytes: int


class FavoriteRequest(BaseModel):
    favorite: bool


class AlbumResponse(BaseModel):
    id: str
    title: str
    asset_ids: list[str]
    created_at: str
    updated_at: str
    deleted_at: str | None = None
    cover_asset_id: str | None = None
    """Chosen on this device (not synced to other devices); `null` lets the client pick one."""


class AlbumCreateRequest(BaseModel):
    title: str


class AlbumPatchRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    cover_asset_id: str | None = Field(default=None, max_length=64)


class AlbumItemRequest(BaseModel):
    asset_id: str


class AlbumsResponse(BaseModel):
    items: list[AlbumResponse]
    next_cursor: str | None


class JobResponse(BaseModel):
    id: str
    type: str
    status: str
    priority: int
    attempts: int
    max_attempts: int
    asset_id: str | None
    error: str | None
    created_at: str
    updated_at: str
    # Queued jobs held back by device conditions (Android): `offline|thermal|battery|charging|wifi`.
    wait_reason: str | None = None


class JobsResponse(BaseModel):
    items: list[JobResponse]
    next_cursor: str | None


class ReindexResponse(BaseModel):
    enqueued: int
    job_ids: list[str]


@dataclass(frozen=True, slots=True)
class AssetRouteDependencies:
    ingestion: AssetIngestionService
    files: AssetFileQueryService
    blob_store: Any
    data_dir: Path
    resolver: Any


@dataclass(frozen=True, slots=True)
class ProductRouteDependencies:
    assets: Any
    drive: DriveUseCases
    folders: Any
    jobs: JobsUseCases
    jobs_queue: Any
    photos: PhotosUseCases


@dataclass(frozen=True, slots=True)
class StorageMaintenanceDependencies:
    service: StorageMaintenanceService


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    return {
        "status": "ok",
        "storage_backend": settings.storage_backend,
        "telegram_configured": settings.telegram_configured,
    }


@router.get("/version", response_model=VersionResponse)
async def version(request: Request) -> dict[str, str]:
    settings = _settings(request)
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }


@router.get("/settings", response_model=SettingsResponse)
async def public_settings(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    data_dir = _data_dir(settings)
    ocr_enabled = settings.ocr_provider != "disabled"
    embeddings_provider = live_embeddings_provider(request)
    embeddings_enabled = embeddings_provider != "disabled"
    embeddings_state, model_available = await _embeddings_status(request, settings, embeddings_provider)
    maintenance = await _storage_maintenance_dependencies(request).service.status()
    return {
        "storage_backend": settings.storage_backend,
        "worker_concurrency": settings.worker_concurrency,
        "telegram_configured": settings.telegram_configured,
        "telegram_enabled": settings.storage_backend == "telegram" and settings.telegram_configured,
        "ocr_enabled": ocr_enabled,
        "ocr_state": "ready" if ocr_enabled else "disabled",
        "embeddings_enabled": embeddings_enabled,
        "embeddings_state": embeddings_state,
        "model_available": model_available,
        "worker_status": "running" if settings.worker_concurrency > 0 else "stopped",
        "data_paths": {
            "cache": str(data_dir / "cache"),
            "config": str(data_dir / "config"),
            "db": str(data_dir / "db"),
            "journal": str(data_dir / "journal"),
            "models": str(data_dir / "models"),
            "uploads": str(data_dir / "uploads"),
        },
        "storage_maintenance": _storage_maintenance_status_response(maintenance),
    }


@router.post("/admin/storage/reclaim", response_model=StorageReclaimResponse)
async def reclaim_storage(request: Request) -> StorageReclaimResponse | JSONResponse:
    try:
        result = await _storage_maintenance_dependencies(request).service.reclaim()
        return StorageReclaimResponse(
            freed_bytes=result.freed_bytes,
            deleted_files=result.deleted_files,
            retained_bytes=result.retained_bytes,
            retained_files=result.retained_files,
            skipped_recent_files=result.skipped_recent_files,
        )
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.get("/drive/items", response_model=DriveItemsResponse)
async def drive_items(
    request: Request,
    folder_id: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
    sort: DriveSort | None = None,
    order: SortOrder | None = None,
) -> DriveItemsResponse | JSONResponse:
    """`sort` (`name|modified|size|kind`) puts folders first; without it the listing is newest first, mixed.
    `order` defaults to `asc` (`desc` for `modified`). Keep the same `sort`/`order` across a cursor's pages."""
    try:
        dependencies = _product_dependencies(request)
        result = await dependencies.drive.list_items(
            ListDriveItemsQuery(folder_id=folder_id, cursor=cursor, limit=_safe_limit(limit), sort=sort, order=order)
        )
        items = [_drive_item_response(item) for item in result.items]
        _apply_local_states(request, [item.asset for item in items if item.asset is not None])
        return DriveItemsResponse(
            breadcrumbs=await _drive_breadcrumbs(dependencies.folders, folder_id),
            items=items,
            next_cursor=result.next_cursor,
        )
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.post("/drive/folders", response_model=FolderResponse)
async def create_folder(request: Request, body: FolderCreateRequest) -> FolderResponse | JSONResponse:
    try:
        folder = await _product_dependencies(request).drive.create_folder(
            CreateFolderCommand(name=body.name, parent_id=body.parent_id)
        )
        return _folder_response(folder)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.patch("/drive/folders/{folder_id}", response_model=FolderResponse)
async def update_folder(folder_id: str, request: Request, body: FolderPatchRequest) -> FolderResponse | JSONResponse:
    try:
        drive = _product_dependencies(request).drive
        folder: Folder | None = None
        if "name" in body.model_fields_set and body.name is not None:
            folder = await drive.rename_folder(RenameFolderCommand(folder_id=folder_id, name=body.name))
        if "parent_id" in body.model_fields_set:
            folder = await drive.move_folder(MoveFolderCommand(folder_id=folder_id, parent_id=body.parent_id))
        if folder is None:
            raise ValidationFailedError("Folder update requires name or parent_id")
        return _folder_response(folder)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.delete("/drive/folders/{folder_id}", response_model=FolderResponse)
async def delete_folder(folder_id: str, request: Request) -> FolderResponse | JSONResponse:
    try:
        folder = await _product_dependencies(request).drive.delete_folder(folder_id)
        return _folder_response(folder)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.patch("/drive/items/{asset_id}", response_model=AssetResponse)
async def rename_drive_asset(asset_id: str, request: Request, body: AssetPatchRequest) -> AssetResponse | JSONResponse:
    try:
        asset = await _product_dependencies(request).drive.rename_asset(
            UpdateAssetCommand(asset_id=asset_id, filename=body.name)
        )
        return _asset_response(asset)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.post("/drive/items/{asset_id}/move", response_model=AssetResponse)
async def move_drive_asset(asset_id: str, request: Request, body: AssetMoveRequest) -> AssetResponse | JSONResponse:
    try:
        asset = await _product_dependencies(request).drive.move_asset(
            MoveAssetCommand(asset_id=asset_id, folder_id=body.folder_id)
        )
        return _asset_response(asset)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.get("/photos/timeline", response_model=PhotoTimelineResponse)
async def photos_timeline(
    request: Request,
    cursor: str | None = None,
    limit: int = 50,
) -> PhotoTimelineResponse | JSONResponse:
    try:
        dependencies = _product_dependencies(request)
        result = await dependencies.photos.timeline(TimelineQuery(cursor=cursor, limit=_safe_limit(limit)))
        groups = [await _timeline_group_response(dependencies.assets, group) for group in result.groups]
        details = _photo_details(request).details([asset.id for group in groups for asset in group.assets])
        for group in groups:
            for asset in group.assets:
                item = details.get(asset.id)
                if item is not None:
                    asset.width, asset.height = item.width, item.height
                    asset.remote_state, asset.thumbnail_etag = item.remote_state, item.thumbnail_etag
        _apply_local_states(request, [asset for group in groups for asset in group.assets])
        return PhotoTimelineResponse(groups=groups, next_cursor=result.next_cursor)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.get("/photos/timeline/index", response_model=PhotoTimelineIndexResponse)
async def photos_timeline_index(request: Request) -> PhotoTimelineIndexResponse | JSONResponse:
    """Months with photo counts and a cursor to jump to each (fast scroller): one grouped query."""
    try:
        assets = storage_pipeline(request).assets
        months = await assets.photos_month_index()
        return PhotoTimelineIndexResponse(
            months=[PhotoTimelineMonthResponse(month=month, count=count, first_cursor=cursor) for month, count, cursor in months]
        )
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.get("/photos/albums", response_model=AlbumsResponse)
async def list_albums(
    request: Request,
    cursor: str | None = None,
    limit: int = 50,
) -> AlbumsResponse | JSONResponse:
    try:
        albums, next_cursor = await _product_dependencies(request).photos.list_albums(
            cursor=cursor,
            limit=_safe_limit(limit),
        )
        return AlbumsResponse(items=[_album_response(album) for album in albums], next_cursor=next_cursor)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.post("/photos/albums", response_model=AlbumResponse)
async def create_album(request: Request, body: AlbumCreateRequest) -> AlbumResponse | JSONResponse:
    try:
        album = await _product_dependencies(request).photos.create_album(CreateAlbumCommand(title=body.title))
        return _album_response(album)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.get("/photos/albums/{album_id}", response_model=AlbumResponse)
async def album_detail(album_id: str, request: Request) -> AlbumResponse | JSONResponse:
    try:
        return _album_response(await _product_dependencies(request).photos.get_album(album_id))
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.patch("/photos/albums/{album_id}", response_model=AlbumResponse)
async def update_album(album_id: str, request: Request, body: AlbumPatchRequest) -> AlbumResponse | JSONResponse:
    """`title` renames (synced); `cover_asset_id` picks the cover among the album's photos, `null` clears it."""
    try:
        album = await _product_dependencies(request).photos.update_album(
            UpdateAlbumCommand(
                album_id=album_id,
                title=body.title if "title" in body.model_fields_set else None,
                cover_asset_id=body.cover_asset_id,
                set_cover="cover_asset_id" in body.model_fields_set,
            )
        )
        return _album_response(album)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.delete("/photos/albums/{album_id}", response_model=AlbumResponse)
async def delete_album(album_id: str, request: Request) -> AlbumResponse | JSONResponse:
    """Deletes the album on every device; its photos stay in the library."""
    try:
        return _album_response(await _product_dependencies(request).photos.delete_album(album_id))
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.delete("/photos/albums/{album_id}/items/{asset_id}", response_model=AlbumResponse)
async def remove_album_item(album_id: str, asset_id: str, request: Request) -> AlbumResponse | JSONResponse:
    try:
        album = await _product_dependencies(request).photos.remove_asset_from_album(
            AddAlbumAssetCommand(album_id=album_id, asset_id=asset_id)
        )
        return _album_response(album)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.post("/photos/albums/{album_id}/items", response_model=AlbumResponse)
async def add_album_item(album_id: str, request: Request, body: AlbumItemRequest) -> AlbumResponse | JSONResponse:
    try:
        album = await _product_dependencies(request).photos.add_asset_to_album(
            AddAlbumAssetCommand(album_id=album_id, asset_id=body.asset_id)
        )
        return _album_response(album)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.get("/photos/{asset_id}", response_model=AssetResponse)
async def photo_detail(asset_id: str, request: Request) -> AssetResponse | JSONResponse:
    try:
        asset = await _asset_dependencies(request).files.get_asset(asset_id)
        return _apply_local_states(request, [_asset_response(asset)])[0]
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.post("/photos/{asset_id}/favorite", response_model=AssetResponse)
async def set_photo_favorite(asset_id: str, request: Request, body: FavoriteRequest) -> AssetResponse | JSONResponse:
    try:
        dependencies = _product_dependencies(request)
        asset = await dependencies.assets.get(asset_id)
        if asset is None:
            from bento.domain.errors import AssetNotFoundError

            raise AssetNotFoundError(asset_id)
        if asset.favorite != body.favorite:
            asset = await dependencies.photos.toggle_favorite(asset_id)
        return _apply_local_states(request, [_asset_response(asset)])[0]
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.get("/jobs", response_model=JobsResponse)
async def list_jobs(
    request: Request,
    cursor: str | None = None,
    limit: int = 50,
) -> JobsResponse | JSONResponse:
    try:
        result = await _product_dependencies(request).jobs.list_jobs(ListJobsQuery(cursor=cursor, limit=_safe_limit(limit)))
        items = [_job_response(job) for job in result.items]
        reasons = _wait_reasons(request, result.items)
        for item in items:
            item.wait_reason = reasons.get(item.id)
        return JobsResponse(items=items, next_cursor=result.next_cursor)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.post("/jobs/{job_id}/retry", response_model=JobResponse)
async def retry_job(job_id: str, request: Request) -> JobResponse | JSONResponse:
    try:
        job = await _product_dependencies(request).jobs.retry_failed_job(job_id)
        return _job_response(job)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.post("/admin/reindex", response_model=ReindexResponse)
async def enqueue_reindex(request: Request) -> ReindexResponse | JSONResponse:
    try:
        job = await _product_dependencies(request).jobs_queue.enqueue(
            type=JobType.REINDEX,
            priority=4,
            payload={"scope": "all"},
            asset_id=None,
        )
        return ReindexResponse(enqueued=1, job_ids=[job.id])
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.post("/assets/upload", response_model=AssetResponse)
async def upload_asset(request: Request, response: Response) -> AssetResponse | JSONResponse:
    try:
        form = await request.form()
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise ValidationFailedError("Multipart field 'file' is required")
        folder_id = _optional_form_value(form.get("folder_id"))
        mode = _optional_asset_mode(form.get("mode"))
        temp_path = await _save_upload_file(upload, _data_dir(_settings(request)) / "cache" / "uploads")
        try:
            result = await _asset_dependencies(request).ingestion.upload_file(
                UploadedAssetFile(
                    source_path=temp_path,
                    original_filename=upload.filename or "upload",
                    declared_mime_type=upload.content_type,
                    folder_id=folder_id,
                    mode=mode,
                )
            )
        finally:
            temp_path.unlink(missing_ok=True)
            await upload.close()
        response.headers["X-Bento-Duplicate"] = "true" if result.duplicate else "false"
        return _apply_local_states(request, [_asset_response(result.asset, duplicate=result.duplicate)])[0]
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.get("/assets/{asset_id}", response_model=AssetResponse)
async def asset_detail(asset_id: str, request: Request) -> AssetResponse | JSONResponse:
    try:
        asset = await _asset_dependencies(request).files.get_asset(asset_id)
        return _apply_local_states(request, [_asset_response(asset)])[0]
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.get("/assets/{asset_id}/download", response_model=None)
async def download_asset(asset_id: str, request: Request) -> FileResponse | JSONResponse:
    try:
        dependencies = _asset_dependencies(request)
        asset_file = await dependencies.files.original_file(asset_id)
        return await _file_response(
            request,
            asset_file.blob_ref,
            media_type=asset_file.asset.metadata.mime_type,
            filename=asset_file.asset.filename,
        )
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.get("/assets/{asset_id}/thumbnail", response_model=None)
async def asset_thumbnail(asset_id: str, request: Request, size: int | None = None) -> Response | JSONResponse:
    """Also serves thumbnails of trashed assets (the trash lists them).

    `size` (256, 512, 1024): the nearest stored thumbnail not smaller than requested (else the largest), with an
    `ETag` keyed by the thumbnail id and an immutable cache lifetime."""
    try:
        if size is None:
            blob_ref = await storage_pipeline(request).blob_refs.latest_for_asset(asset_id, BlobKind.THUMBNAIL)
            if blob_ref is None:
                raise AssetNotFoundError(asset_id)
            return await _file_response(request, blob_ref, media_type=_blob_media_type(blob_ref))
        if size not in THUMBNAIL_SIZES:
            raise ValidationFailedError("Unsupported thumbnail size", {"size": size, "allowed": list(THUMBNAIL_SIZES)})
        blob_ref = _photo_details(request).thumbnail_for_size(asset_id, size)
        if blob_ref is None:
            raise AssetNotFoundError(asset_id)
        etag = f'"{blob_ref.id}"'
        cache_control = "private, max-age=31536000, immutable"
        if etag in [value.strip() for value in request.headers.get("if-none-match", "").split(",")]:
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": cache_control})
        response = await _file_response(request, blob_ref, media_type=_blob_media_type(blob_ref))
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = cache_control
        return response
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.put("/assets/{asset_id}/offline", status_code=202, response_model=OfflinePinResponse)
async def pin_asset_offline(asset_id: str, request: Request) -> OfflinePinResponse | JSONResponse:
    """"Disponible sin conexión": keep the original on this device, excluded from cache eviction."""
    try:
        components = storage_pipeline(request)
        asset_file = await _asset_dependencies(request).files.original_file(asset_id)
        blob_ref = asset_file.blob_ref
        if blob_ref.backend == StorageBackend.LOCAL:
            return OfflinePinResponse(asset_id=asset_id, pinned=True)  # never uploaded: already local, never evicted
        if await components.cache.set_pinned(blob_ref.id, True):
            return OfflinePinResponse(asset_id=asset_id, pinned=True)
        _start_pinned_download(request, blob_ref)
        return OfflinePinResponse(asset_id=asset_id, pinned=False, downloading=True)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.delete("/assets/{asset_id}/offline", response_model=OfflinePinResponse)
async def unpin_asset_offline(asset_id: str, request: Request) -> OfflinePinResponse | JSONResponse:
    try:
        asset_file = await _asset_dependencies(request).files.original_file(asset_id)
        await storage_pipeline(request).cache.set_pinned(asset_file.blob_ref.id, False)
        return OfflinePinResponse(asset_id=asset_id, pinned=False)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.get("/storage/local", response_model=LocalStorageResponse)
async def local_storage(request: Request) -> LocalStorageResponse | JSONResponse:
    try:
        components = storage_pipeline(request)
        cached = await components.cache.evictable_usage()
        pinned = await components.cache.pinned_usage()
        return LocalStorageResponse(
            cache_bytes=cached.bytes,
            cache_files=cached.files,
            pinned_bytes=pinned.bytes,
            pinned_count=pinned.files,
            cache_limit_bytes=components.cache_max_bytes,
            thumbs_bytes=_photo_details(request).thumbnail_bytes(),
        )
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.get("/assets/{asset_id}/preview", response_model=None)
async def asset_preview(asset_id: str, request: Request) -> FileResponse | JSONResponse:
    try:
        dependencies = _asset_dependencies(request)
        asset_file = await dependencies.files.preview_file(asset_id)
        return await _file_response(request, asset_file.blob_ref, media_type=_blob_media_type(asset_file.blob_ref))
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.delete("/assets/{asset_id}", response_model=AssetResponse)
async def delete_asset(asset_id: str, request: Request) -> AssetResponse | JSONResponse:
    try:
        asset = await _asset_dependencies(request).files.delete_asset(asset_id)
        return _asset_response(asset)
    except DomainError as exc:
        return _domain_error_response(request, exc)


THUMBNAIL_SIZES = (256, 512, 1024)


def _wait_reasons(request: Request, jobs: tuple[Job, ...]) -> dict[str, str]:
    from bento.adapters.jobs.sqlite_queue import job_class
    from bento.domain.jobs import JobStatus
    from bento.infrastructure import services

    deferral = services.get_job_eligibility(_settings(request)).current()
    waiting = [job for job in jobs if job.status in {JobStatus.QUEUED, JobStatus.RETRYING}]
    if deferral.empty or not waiting:
        return {}
    videos = _photo_details(request).video_asset_ids([job.asset_id for job in waiting if job.asset_id])
    reasons: dict[str, str] = {}
    for job in waiting:
        reason = deferral.reasons.get(job_class(job, is_video=job.asset_id in videos))
        cutoff = deferral.wifi_override_before
        if reason is not None and not (reason.value == "wifi" and cutoff is not None and job.created_at <= cutoff):
            reasons[job.id] = reason.value
    return reasons
_pin_downloads: set[Any] = set()


def _photo_details(request: Request) -> Any:
    from bento.adapters.repositories.photo_details import SQLitePhotoDetails

    return SQLitePhotoDetails(storage_pipeline(request).session_factory)


def _start_pinned_download(request: Request, blob_ref: BlobRef) -> None:
    """Fetch the original into the cache in the background, then pin it (202 semantics)."""
    import asyncio

    components = storage_pipeline(request)

    async def download() -> None:
        try:
            await components.content.blob_path(blob_ref)
            await components.cache.set_pinned(blob_ref.id, True)
        except Exception:  # noqa: BLE001 - the next PUT retries; nothing to report to a finished request
            return

    task = asyncio.get_running_loop().create_task(download())
    _pin_downloads.add(task)
    task.add_done_callback(_pin_downloads.discard)


def _asset_dependencies(request: Request) -> AssetRouteDependencies:
    cached = getattr(request.app.state, "asset_route_dependencies", None)
    if cached is not None:
        return cached

    components = storage_pipeline(request)
    dependencies = AssetRouteDependencies(
        ingestion=components.ingestion,
        files=components.files,
        blob_store=components.local_store,
        data_dir=components.data_dir,
        resolver=components.local_resolver,
    )
    request.app.state.asset_route_dependencies = dependencies
    return dependencies


def _product_dependencies(request: Request) -> ProductRouteDependencies:
    cached = getattr(request.app.state, "product_route_dependencies", None)
    if cached is not None:
        return cached

    from bento.adapters.jobs import SQLiteJobQueue
    from bento.adapters.manifest import SQLiteManifestJournal
    from bento.adapters.repositories import SQLiteAlbumRepository, SQLiteAssetRepository, SQLiteFolderRepository
    from bento.infrastructure.db.clock import SystemClock
    from bento.infrastructure.db.engine import create_app_session_factory

    settings = _settings(request)
    data_dir = _data_dir(settings)
    clock = SystemClock()
    session_factory = create_app_session_factory(settings)
    assets = SQLiteAssetRepository(session_factory)
    folders = SQLiteFolderRepository(session_factory)
    albums = SQLiteAlbumRepository(session_factory)
    manifest = SQLiteManifestJournal(session_factory, clock, data_dir / "journal")
    jobs_queue = SQLiteJobQueue(session_factory, clock)
    dependencies = ProductRouteDependencies(
        assets=assets,
        folders=folders,
        drive=DriveUseCases(assets=assets, folders=folders, manifest=manifest, clock=clock),
        photos=PhotosUseCases(assets=assets, albums=albums, clock=clock),
        jobs=JobsUseCases(jobs=jobs_queue, clock=clock),
        jobs_queue=jobs_queue,
    )
    request.app.state.product_route_dependencies = dependencies
    return dependencies


def _storage_maintenance_dependencies(request: Request) -> StorageMaintenanceDependencies:
    cached = getattr(request.app.state, "storage_maintenance_dependencies", None)
    if cached is not None:
        return cached
    dependencies = StorageMaintenanceDependencies(service=storage_pipeline(request).maintenance)
    request.app.state.storage_maintenance_dependencies = dependencies
    return dependencies


async def _save_upload_file(upload: UploadFile, upload_dir: Path) -> Path:
    upload_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="upload-", suffix=".tmp", dir=upload_dir, delete=False) as handle:
        temp_path = Path(handle.name)
        while chunk := await upload.read(1024 * 1024):
            handle.write(chunk)
    return temp_path


def _data_dir(settings: Settings) -> Path:
    return Path(settings.data_dir)


def _safe_limit(limit: int) -> int:
    return max(1, min(limit, 200))


async def _embeddings_status(request: Request, settings: Settings, provider: str) -> tuple[str, bool]:
    """`(embeddings_state, model_available)` for old clients (`api/smart-search-contract.md`), for `provider` as in
    effect now.

    `managed` folds the smart search status (`legacy_embeddings_state()`) and its verified install; `custom`
    looks for the person's own model file (`custom_model_path`)."""
    if provider == "managed":
        try:
            view = await smart_search_activation(request).status()
        except Exception as exc:  # noqa: BLE001 - the settings summary never fails on smart search bookkeeping
            LOGGER.warning("Could not read the smart search status: %s", exc.__class__.__name__)
            return "pending", False
        return view.status.legacy_embeddings_state().value, view.model_installed
    model_path = str(settings.custom_model_path or "").strip()
    model_available = bool(model_path) and resolve_model_path(model_path, settings.data_dir).is_file()
    if provider == "disabled":
        return "disabled", model_available
    if provider == "mock":
        return "ready", model_available
    return ("ready" if model_available else "pending"), model_available


def _storage_maintenance_status_response(status: Any) -> StorageMaintenanceStatusResponse:
    return StorageMaintenanceStatusResponse(
        connection_state=status.connection_state,
        can_reclaim=status.can_reclaim,
        fully_remote=status.fully_remote,
        reclaimable_bytes=status.reclaimable_bytes,
        reclaimable_files=status.reclaimable_files,
        local_blob_count=status.local_blob_count,
        telegram_blob_count=status.telegram_blob_count,
    )


async def _file_response(
    request: Request,
    blob_ref: BlobRef,
    *,
    media_type: str,
    filename: str | None = None,
) -> FileResponse:
    """Serve a blob from a local copy; remote-only blobs are downloaded into the cache first."""
    path = await storage_pipeline(request).content.blob_path(blob_ref)
    response = FileResponse(path, media_type=media_type, filename=filename)
    response.headers["Cache-Control"] = (
        "private, max-age=3600" if blob_ref.kind in {BlobKind.THUMBNAIL, BlobKind.PREVIEW} else "no-store"
    )
    return response


def _optional_form_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_asset_mode(value: object) -> AssetMode | None:
    text = _optional_form_value(value)
    if text is None:
        return None
    try:
        return AssetMode(text)
    except ValueError as exc:
        raise ValidationFailedError("Invalid asset mode", {"mode": text}) from exc


def _asset_response(asset: Asset, *, duplicate: bool = False) -> AssetResponse:
    media_version = quote(asset.updated_at.isoformat(), safe="")
    has_media = asset.kind in {AssetKind.IMAGE, AssetKind.PDF, AssetKind.VIDEO}
    return AssetResponse(
        id=asset.id,
        kind=asset.kind.value,
        mode=asset.mode.value,
        folder_id=asset.folder_id,
        filename=asset.filename,
        mime_type=asset.metadata.mime_type,
        size_bytes=asset.metadata.size_bytes,
        sha256=asset.metadata.sha256,
        favorite=asset.favorite,
        processing_state=asset.processing_state.value,
        created_at=asset.created_at.isoformat(),
        updated_at=asset.updated_at.isoformat(),
        duplicate=duplicate,
        preview_url=f"/api/assets/{asset.id}/preview?v={media_version}" if has_media else None,
        taken_at=asset.metadata.taken_at.isoformat() if asset.metadata.taken_at else None,
        thumbnail_url=f"/api/assets/{asset.id}/thumbnail?v={media_version}" if has_media else None,
        exif=_exif_response(asset),
    )


def _exif_response(asset: Asset) -> ExifSummaryResponse | None:
    summary = summarize_exif(asset.metadata.exif)
    if summary is None:
        return None
    return ExifSummaryResponse(**{name: getattr(summary, name) for name in ExifSummaryResponse.model_fields})


def _apply_local_states(request: Request, responses: list[AssetResponse]) -> list[AssetResponse]:
    """Fills `offline_pinned`/`locally_available` for a page of assets with one batched lookup."""
    states = _photo_details(request).local_states([response.id for response in responses])
    for response in responses:
        state = states.get(response.id)
        if state is not None:
            response.offline_pinned, response.locally_available = state.offline_pinned, state.locally_available
    return responses


def _folder_response(folder: Folder) -> FolderResponse:
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        created_at=folder.created_at.isoformat(),
        updated_at=folder.updated_at.isoformat(),
        deleted_at=folder.deleted_at.isoformat() if folder.deleted_at else None,
    )


def _drive_item_response(item: DriveItem) -> DriveItemResponse:
    return DriveItemResponse(
        type=item.type.value,
        id=item.id,
        name=item.name,
        updated_at=item.updated_at.isoformat(),
        asset=_asset_response(item.asset) if item.asset is not None else None,
        folder=_folder_response(item.folder) if item.folder is not None else None,
        item_count=item.item_count,
    )


async def _drive_breadcrumbs(folders: Any, folder_id: str | None) -> list[DriveBreadcrumbResponse]:
    breadcrumbs: list[DriveBreadcrumbResponse] = []
    seen: set[str] = set()
    current_id = folder_id
    while current_id is not None and current_id not in seen:
        seen.add(current_id)
        folder = await folders.get(current_id)
        if folder is None:
            break
        breadcrumbs.append(DriveBreadcrumbResponse(folder_id=folder.id, name=folder.name))
        current_id = folder.parent_id
    breadcrumbs.reverse()
    return breadcrumbs


async def _timeline_group_response(assets: Any, group: TimelineGroup) -> PhotoTimelineGroupResponse:
    group_assets: list[AssetResponse] = []
    for asset_id in group.asset_ids:
        asset = await assets.get(asset_id)
        if asset is not None:
            group_assets.append(_asset_response(asset))
    return PhotoTimelineGroupResponse(date=group.day.isoformat(), assets=group_assets)


def _album_response(album: Album) -> AlbumResponse:
    return AlbumResponse(
        id=album.id,
        title=album.title,
        asset_ids=sorted(album.asset_ids),
        created_at=album.created_at.isoformat(),
        updated_at=album.updated_at.isoformat(),
        deleted_at=album.deleted_at.isoformat() if album.deleted_at else None,
        cover_asset_id=album.cover_asset_id,
    )


def _job_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        type=job.type.value,
        status=job.status.value,
        priority=job.priority,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        asset_id=job.asset_id,
        error=job.error,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )


def _blob_media_type(blob_ref: BlobRef) -> str:
    if blob_ref.kind.value in {"thumbnail", "preview"}:
        return "image/jpeg"
    if blob_ref.object_key.lower().endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if blob_ref.object_key.lower().endswith(".png"):
        return "image/png"
    return "application/octet-stream"


def _domain_error_response(request: Request, error: DomainError) -> JSONResponse:
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    return JSONResponse(
        status_code=_status_code(error),
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "details": error.details,
                "request_id": request_id,
            }
        },
    )


def _status_code(error: DomainError) -> int:
    if error.code in {"asset_not_found", "folder_not_found", "album_not_found", "job_not_found", "path_not_found"}:
        return 404
    if error.code in {"duplicate_asset", "invalid_folder_move", "job_not_retryable", "path_ambiguous"}:
        return 409
    if error.code == "upload_too_large":
        return 413
    if isinstance(error, UnsupportedMediaTypeError):
        return 415
    if error.code in {"storage_unavailable", "telegram_not_configured"}:
        return 503
    return 400
