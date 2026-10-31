from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bento.domain.backup import BackupPolicy, BackupSource
from bento.domain.errors import DomainError
from bento.interfaces.http.routes_content import error_response, pipeline

router = APIRouter()


class BackupSourceCreateRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    label: str | None = Field(default=None, max_length=255)


class BackupSourcePatchRequest(BaseModel):
    enabled: bool | None = None
    label: str | None = Field(default=None, max_length=255)


class BackupPolicyPatchRequest(BaseModel):
    paused: bool | None = None
    pause_on_battery: bool | None = None
    bandwidth_limit_kbps: int | None = Field(default=None, ge=0, le=1_000_000)


class BackupPowerRequest(BaseModel):
    on_battery: bool


@router.get("/backup/sources", response_model=None)
async def list_backup_sources(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        sources = await pipeline(request).backup.list_sources()
        return {"items": [_source(source) for source in sources]}
    except DomainError as exc:
        return error_response(request, exc)


@router.post("/backup/sources", response_model=None)
async def add_backup_source(request: Request, body: BackupSourceCreateRequest) -> dict[str, Any] | JSONResponse:
    try:
        return _source(await pipeline(request).backup.add_source(body.path, body.label))
    except DomainError as exc:
        return error_response(request, exc)


@router.patch("/backup/sources/{source_id}", response_model=None)
async def update_backup_source(
    source_id: str, request: Request, body: BackupSourcePatchRequest
) -> dict[str, Any] | JSONResponse:
    try:
        source = await pipeline(request).backup.update_source(source_id, enabled=body.enabled, label=body.label)
        return _source(source)
    except DomainError as exc:
        return error_response(request, exc)


@router.delete("/backup/sources/{source_id}", response_model=None)
async def remove_backup_source(source_id: str, request: Request) -> dict[str, Any] | JSONResponse:
    try:
        await pipeline(request).backup.remove_source(source_id)
        return {"removed": True}
    except DomainError as exc:
        return error_response(request, exc)


@router.post("/backup/sources/{source_id}/scan", response_model=None)
async def scan_backup_source(source_id: str, request: Request) -> dict[str, Any] | JSONResponse:
    try:
        return _source(await pipeline(request).backup.request_scan(source_id))
    except DomainError as exc:
        return error_response(request, exc)


@router.get("/backup/suggestions", response_model=None)
async def backup_suggestions(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        items = await pipeline(request).backup.suggestions()
        return {"items": [{"path": item.path, "label": item.label, "kind": item.kind.value} for item in items]}
    except DomainError as exc:
        return error_response(request, exc)


@router.get("/backup/policy", response_model=None)
async def get_backup_policy(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        return _policy(await pipeline(request).backup.get_policy())
    except DomainError as exc:
        return error_response(request, exc)


@router.patch("/backup/policy", response_model=None)
async def update_backup_policy(request: Request, body: BackupPolicyPatchRequest) -> dict[str, Any] | JSONResponse:
    try:
        policy = await pipeline(request).backup.update_policy(
            paused=body.paused,
            pause_on_battery=body.pause_on_battery,
            bandwidth_limit_kbps=body.bandwidth_limit_kbps,
        )
        return _policy(policy)
    except DomainError as exc:
        return error_response(request, exc)


@router.post("/backup/power", response_model=None)
async def report_power(request: Request, body: BackupPowerRequest) -> dict[str, Any] | JSONResponse:
    try:
        return _policy(await pipeline(request).backup.set_power(on_battery=body.on_battery))
    except DomainError as exc:
        return error_response(request, exc)


def _source(source: BackupSource) -> dict[str, Any]:
    return {
        "id": source.id,
        "path": source.path,
        "label": source.label,
        "enabled": source.enabled,
        "state": source.state.value,
        "files_total": source.files_total,
        "files_done": source.files_done,
        "files_pending": source.files_pending,
        "bytes_pending": source.bytes_pending,
        "last_scan_at": source.last_scan_at.isoformat() if source.last_scan_at else None,
        "error": source.error_code,
    }


def _policy(policy: BackupPolicy) -> dict[str, Any]:
    return {
        "paused": policy.paused,
        "pause_on_battery": policy.pause_on_battery,
        "bandwidth_limit_kbps": policy.bandwidth_limit_kbps,
        "on_battery": policy.on_battery,
        "effective_paused": policy.effective_paused,
    }
