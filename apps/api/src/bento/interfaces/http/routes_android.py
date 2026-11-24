"""Android-only HTTP surface: imports of content handed over as file descriptors (`api/android-endpoints.md` §4)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bento.application.content_imports import ContentImport, ContentImportItem, ContentImportService
from bento.domain.errors import DomainError
from bento.interfaces.http.routes_content import error_response, pipeline

router = APIRouter()


class ImportItemRequest(BaseModel):
    fd_handle: int = Field(ge=0)
    display_name: str | None = Field(default=None, max_length=1024)
    mime_type: str | None = Field(default=None, max_length=255)
    size_bytes: int | None = Field(default=None, ge=0)


class ImportRequest(BaseModel):
    items: list[ImportItemRequest] = Field(min_length=1, max_length=500)
    folder_id: str | None = Field(default=None, max_length=64)
    album_id: str | None = Field(default=None, max_length=64)


class ImportNotFoundError(DomainError):
    def __init__(self, import_id: str) -> None:
        super().__init__("import_not_found", "Import not found", {"import_id": import_id})


@router.post("/android/imports", status_code=202, response_model=None)
async def start_import(request: Request, body: ImportRequest) -> dict[str, Any] | JSONResponse:
    try:
        job = await _service(request).start(
            [ContentImportItem(**item.model_dump()) for item in body.items], folder_id=body.folder_id, album_id=body.album_id
        )
        return _import(job)
    except DomainError as exc:
        return error_response(request, exc)


@router.get("/android/imports/{import_id}", response_model=None)
async def get_import(import_id: str, request: Request) -> dict[str, Any] | JSONResponse:
    try:
        job = await _service(request).get(import_id)
        if job is None:
            raise ImportNotFoundError(import_id)
        return _import(job)
    except DomainError as exc:
        return error_response(request, exc)


@router.post("/android/imports/{import_id}/dismiss", status_code=204, response_model=None)
async def dismiss_import(import_id: str, request: Request) -> Response | JSONResponse:
    """Hides the `import_failed` Activity item of a finished import (404 while unknown or still running)."""
    try:
        if not await _service(request).dismiss(import_id):
            raise ImportNotFoundError(import_id)
        return Response(status_code=204)
    except DomainError as exc:
        return error_response(request, exc)


def _import(job: ContentImport) -> dict[str, Any]:
    """`items[].error`: `import_interrupted` (the app restarted mid-import: share the file again),
    `content_unreadable`, `album_unavailable`, or an upload error code."""
    return {
        "import_id": job.id,
        "done": job.done,
        "counts": job.counts,
        "items": [
            {"client_index": item.client_index, "asset_id": item.asset_id, "status": item.status, "error": item.error}
            for item in job.items
        ],
    }


def _service(request: Request) -> ContentImportService:
    cached = getattr(request.app.state, "content_imports", None)
    if cached is not None:
        return cached
    from bento.adapters.backup.media import LocalMediaStaging
    from bento.adapters.repositories.content_imports import SQLiteContentImportStore
    from bento.infrastructure import services
    from bento.infrastructure.db.clock import SystemClock

    settings = request.app.state.settings
    components = pipeline(request)

    async def add_to_album(album_id: str, asset_id: str) -> None:
        from bento.application.photos import AddAlbumAssetCommand
        from bento.interfaces.http.routes import _product_dependencies

        await _product_dependencies(request).photos.add_asset_to_album(AddAlbumAssetCommand(album_id=album_id, asset_id=asset_id))

    service = ContentImportService(
        imports=services.get_content_imports(settings),
        ingestion=components.ingestion,
        staging=LocalMediaStaging(components.data_dir / "uploads" / "imports"),
        notifier=services.get_notifier(settings),
        store=SQLiteContentImportStore(components.session_factory),
        clock=SystemClock(),
        add_to_album=add_to_album,
    )
    request.app.state.content_imports = service
    return service
