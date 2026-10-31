from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
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
from bento.application.photos import AddAlbumAssetCommand, CreateAlbumCommand, PhotosUseCases, TimelineQuery
from bento.application.storage_maintenance import StorageMaintenanceService
from bento.domain.assets import Asset, AssetKind, AssetMode
from bento.domain.drive import DriveItem, Folder
from bento.domain.errors import DomainError, UnsupportedMediaTypeError, ValidationFailedError
from bento.domain.jobs import Job, JobType
from bento.domain.photos import Album, TimelineGroup
from bento.domain.security import EncryptionMode
from bento.domain.storage import BlobKind, BlobRef, StorageBackend
from bento.infrastructure.settings import Settings
from bento.interfaces.http.routes_dev import router as dev_router
from bento.interfaces.http.routes_devices import router as devices_router
from bento.interfaces.http.routes_pairing import router as pairing_router
from bento.interfaces.http.routes_search import router as search_router
from bento.interfaces.http.routes_settings import router as settings_router
from bento.interfaces.http.routes_sync import router as sync_router
from bento.interfaces.telegram.routes import router as telegram_router

router = APIRouter()
router.include_router(search_router)
router.include_router(settings_router)
router.include_router(telegram_router)
router.include_router(dev_router)
router.include_router(pairing_router)
router.include_router(devices_router)
router.include_router(sync_router)


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


class FavoriteRequest(BaseModel):
    favorite: bool


class AlbumResponse(BaseModel):
    id: str
    title: str
    asset_ids: list[str]
    created_at: str
    updated_at: str
    deleted_at: str | None = None


class AlbumCreateRequest(BaseModel):
    title: str


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
    model_path = _resolve_data_path(settings.jina_model_path, data_dir)
    ocr_enabled = settings.ocr_provider != "disabled"
    embeddings_enabled = settings.embeddings_provider != "disabled"
    model_available = model_path.is_file()
    maintenance = await _storage_maintenance_dependencies(request).service.status()
    return {
        "storage_backend": settings.storage_backend,
        "worker_concurrency": settings.worker_concurrency,
        "telegram_configured": settings.telegram_configured,
        "telegram_enabled": settings.storage_backend == "telegram" and settings.telegram_configured,
        "ocr_enabled": ocr_enabled,
        "ocr_state": "ready" if ocr_enabled else "disabled",
        "embeddings_enabled": embeddings_enabled,
        "embeddings_state": _embeddings_state(settings, model_available),
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
) -> DriveItemsResponse | JSONResponse:
    try:
        dependencies = _product_dependencies(request)
        result = await dependencies.drive.list_items(
            ListDriveItemsQuery(folder_id=folder_id, cursor=cursor, limit=_safe_limit(limit))
        )
        return DriveItemsResponse(
            breadcrumbs=await _drive_breadcrumbs(dependencies.folders, folder_id),
            items=[_drive_item_response(item) for item in result.items],
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
        return PhotoTimelineResponse(
            groups=[await _timeline_group_response(dependencies.assets, group) for group in result.groups],
            next_cursor=result.next_cursor,
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
        return _asset_response(asset)
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
        return _asset_response(asset)
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
        return JobsResponse(items=[_job_response(job) for job in result.items], next_cursor=result.next_cursor)
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
        return _asset_response(result.asset, duplicate=result.duplicate)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.get("/assets/{asset_id}", response_model=AssetResponse)
async def asset_detail(asset_id: str, request: Request) -> AssetResponse | JSONResponse:
    try:
        asset = await _asset_dependencies(request).files.get_asset(asset_id)
        return _asset_response(asset)
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.get("/assets/{asset_id}/download", response_model=None)
async def download_asset(asset_id: str, request: Request) -> FileResponse | JSONResponse:
    try:
        dependencies = _asset_dependencies(request)
        asset_file = await dependencies.files.original_file(asset_id)
        return await _file_response(
            dependencies,
            asset_file.blob_ref,
            media_type=asset_file.asset.metadata.mime_type,
            filename=asset_file.asset.filename,
        )
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.get("/assets/{asset_id}/thumbnail", response_model=None)
async def asset_thumbnail(asset_id: str, request: Request) -> FileResponse | JSONResponse:
    try:
        dependencies = _asset_dependencies(request)
        asset_file = await dependencies.files.thumbnail_file(asset_id)
        return await _file_response(dependencies, asset_file.blob_ref, media_type=_blob_media_type(asset_file.blob_ref))
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.get("/assets/{asset_id}/preview", response_model=None)
async def asset_preview(asset_id: str, request: Request) -> FileResponse | JSONResponse:
    try:
        dependencies = _asset_dependencies(request)
        asset_file = await dependencies.files.preview_file(asset_id)
        return await _file_response(dependencies, asset_file.blob_ref, media_type=_blob_media_type(asset_file.blob_ref))
    except DomainError as exc:
        return _domain_error_response(request, exc)


@router.delete("/assets/{asset_id}", response_model=AssetResponse)
async def delete_asset(asset_id: str, request: Request) -> AssetResponse | JSONResponse:
    try:
        asset = await _asset_dependencies(request).files.delete_asset(asset_id)
        return _asset_response(asset)
    except DomainError as exc:
        return _domain_error_response(request, exc)


def _asset_dependencies(request: Request) -> AssetRouteDependencies:
    cached = getattr(request.app.state, "asset_route_dependencies", None)
    if cached is not None:
        return cached

    from bento.adapters.jobs import SQLiteJobQueue
    from bento.adapters.manifest import SQLiteManifestJournal
    from bento.adapters.media import LocalBlobPathResolver, LocalUploadMetadataExtractor, SQLiteBlobRefCatalog
    from bento.adapters.repositories import SQLiteAssetRepository, SQLiteFolderRepository
    from bento.application.upload import UploadAssetUseCase
    from bento.infrastructure.db.clock import SystemClock
    from bento.infrastructure.db.engine import create_session_factory, sqlite_url
    from bento.infrastructure.storage.factory import create_blob_store

    settings = _settings(request)
    data_dir = _data_dir(settings)
    clock = SystemClock()
    session_factory = create_session_factory(sqlite_url(data_dir / "db" / "bento.sqlite3"))
    assets = SQLiteAssetRepository(session_factory)
    folders = SQLiteFolderRepository(session_factory)
    blob_refs = SQLiteBlobRefCatalog(session_factory, clock)
    manifest = SQLiteManifestJournal(session_factory, clock, data_dir / "journal")
    blob_store = create_blob_store(settings)
    upload_use_case = UploadAssetUseCase(
        assets=assets,
        folders=folders,
        blob_store=blob_store,
        jobs=SQLiteJobQueue(session_factory, clock),
        manifest=manifest,
        clock=clock,
    )
    dependencies = AssetRouteDependencies(
        ingestion=AssetIngestionService(
            upload=upload_use_case,
            blob_refs=blob_refs,
            metadata_extractor=LocalUploadMetadataExtractor(),
        ),
        files=AssetFileQueryService(assets=assets, blob_refs=blob_refs, manifest=manifest, clock=clock),
        blob_store=blob_store,
        data_dir=data_dir,
        resolver=LocalBlobPathResolver(data_dir / "uploads"),
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
    from bento.infrastructure.db.engine import create_session_factory, sqlite_url

    settings = _settings(request)
    data_dir = _data_dir(settings)
    clock = SystemClock()
    session_factory = create_session_factory(sqlite_url(data_dir / "db" / "bento.sqlite3"))
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

    from bento.adapters.storage.maintenance import LocalEphemeralCache, SQLiteStorageInventory
    from bento.infrastructure.db.engine import create_session_factory, sqlite_url
    from bento.infrastructure.storage.factory import create_blob_store

    settings = _settings(request)
    data_dir = _data_dir(settings)
    session_factory = create_session_factory(sqlite_url(data_dir / "db" / "bento.sqlite3"))
    blob_store = None
    if settings.storage_backend == StorageBackend.TELEGRAM.value and settings.telegram_configured:
        try:
            blob_store = create_blob_store(settings)
        except DomainError:
            blob_store = None
    dependencies = StorageMaintenanceDependencies(
        service=StorageMaintenanceService(
            storage_backend=StorageBackend(settings.storage_backend),
            telegram_configured=settings.telegram_configured,
            blob_store=blob_store,
            inventory=SQLiteStorageInventory(session_factory),
            cache=LocalEphemeralCache(data_dir),
        )
    )
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


def _resolve_data_path(path: str, data_dir: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return (data_dir.parent / candidate).resolve()


def _embeddings_state(settings: Settings, model_available: bool) -> str:
    if settings.embeddings_provider == "disabled":
        return "disabled"
    if settings.embeddings_provider == "mock":
        return "ready"
    return "ready" if model_available else "pending"


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
    dependencies: AssetRouteDependencies,
    blob_ref: BlobRef,
    *,
    media_type: str,
    filename: str | None = None,
) -> FileResponse:
    cleanup = None
    if blob_ref.backend == StorageBackend.LOCAL and blob_ref.encryption.mode == EncryptionMode.NONE:
        path = dependencies.resolver.resolve(blob_ref)
    elif blob_ref.backend in {StorageBackend.LOCAL, StorageBackend.TELEGRAM}:
        path = await dependencies.blob_store.download(blob_ref, _download_cache_path(dependencies.data_dir, blob_ref))
        cleanup = BackgroundTask(path.unlink, missing_ok=True)
    else:
        from bento.domain.errors import StorageUnavailableError

        raise StorageUnavailableError(blob_ref.backend.value)
    response = FileResponse(path, media_type=media_type, filename=filename, background=cleanup)
    response.headers["Cache-Control"] = (
        "private, max-age=3600" if blob_ref.kind in {BlobKind.THUMBNAIL, BlobKind.PREVIEW} else "no-store"
    )
    return response


def _download_cache_path(data_dir: Path, blob_ref: BlobRef) -> Path:
    safe_id = "".join(character if character.isalnum() or character in {"-", "_", "."} else "_" for character in blob_ref.id)
    return data_dir / "cache" / "downloads" / f"{safe_id}-{uuid.uuid4().hex}"


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
    )


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
    if error.code in {"asset_not_found", "folder_not_found", "album_not_found", "job_not_found"}:
        return 404
    if error.code in {"duplicate_asset", "invalid_folder_move", "job_not_retryable"}:
        return 409
    if error.code == "upload_too_large":
        return 413
    if isinstance(error, UnsupportedMediaTypeError):
        return 415
    if error.code in {"storage_unavailable", "telegram_not_configured"}:
        return 503
    return 400
