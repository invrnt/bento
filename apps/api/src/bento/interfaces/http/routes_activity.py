from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from bento.domain.activity import Activity, TransferStats
from bento.domain.errors import DomainError
from bento.interfaces.http.routes_content import error_response, pipeline

router = APIRouter()


@router.get("/activity", response_model=None)
async def get_activity(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        return activity_response(await pipeline(request).activity.current())
    except DomainError as exc:
        return error_response(request, exc)


def activity_response(activity: Activity) -> dict[str, Any]:
    return {
        "summary": activity.summary.value,
        "uploads": _stats(activity.uploads),
        "downloads": _stats(activity.downloads),
        "attention": [
            {
                "id": item.id,
                "kind": item.kind.value,
                "title_key": item.title_key,
                "params": dict(item.params),
                "action": item.action.value,
            }
            for item in activity.attention
        ],
    }


def _stats(stats: TransferStats) -> dict[str, Any]:
    return {
        "active": stats.active,
        "queued": stats.queued,
        "bytes_total": stats.bytes_total,
        "bytes_done": stats.bytes_done,
        "eta_seconds": stats.eta_seconds,
    }
