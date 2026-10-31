from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bento.application.trash import TrashEntry
from bento.domain.errors import DomainError
from bento.interfaces.http.routes_content import error_response, pipeline

router = APIRouter()


class TrashIdsRequest(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=500)


@router.get("/trash", response_model=None)
async def list_trash(request: Request, cursor: str | None = None, limit: int = 50) -> dict[str, Any] | JSONResponse:
    try:
        entries, next_cursor = await pipeline(request).trash.list(cursor=cursor, limit=max(1, min(limit, 200)))
        return {"items": [_entry(entry) for entry in entries], "next_cursor": next_cursor}
    except DomainError as exc:
        return error_response(request, exc)


@router.post("/trash/restore", response_model=None)
async def restore_trash(request: Request, body: TrashIdsRequest) -> dict[str, Any] | JSONResponse:
    try:
        return {"restored": await pipeline(request).trash.restore(tuple(body.ids))}
    except DomainError as exc:
        return error_response(request, exc)


@router.post("/trash/purge", response_model=None)
async def purge_trash(request: Request, body: TrashIdsRequest) -> dict[str, Any] | JSONResponse:
    try:
        result = await pipeline(request).trash.purge(tuple(body.ids))
        return {"purged": result.purged, "deferred": list(result.deferred)}
    except DomainError as exc:
        return error_response(request, exc)


@router.post("/trash/empty", response_model=None)
async def empty_trash(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        result = await pipeline(request).trash.empty()
        return {"purged": result.purged, "deferred": list(result.deferred)}
    except DomainError as exc:
        return error_response(request, exc)


def _entry(entry: TrashEntry) -> dict[str, Any]:
    item = entry.item
    return {
        "id": item.id,
        "type": item.type.value,
        "name": item.name,
        "size_bytes": item.size_bytes,
        "deleted_at": item.deleted_at.isoformat(),
        "purge_at": item.purge_at.isoformat(),
        "thumbnail_url": f"/api/assets/{item.id}/thumbnail" if entry.has_thumbnail else None,
    }
