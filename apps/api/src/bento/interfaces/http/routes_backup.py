from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bento.domain.backup import BackupPolicy, BackupSource, BackupSuggestion
from bento.domain.jobs import JobType
from bento.domain.errors import BackupSourceInvalidError, DomainError
from bento.interfaces.http.routes_content import error_response, pipeline

router = APIRouter()
_BACKUP_JOB_TYPES = frozenset({JobType.BACKUP_SCAN, JobType.BACKUP_UPLOAD, JobType.REMOTE_UPLOAD})


class BackupSourceCreateRequest(BaseModel):
    kind: Literal["folder", "media_store"] = "folder"
    path: str | None = Field(default=None, min_length=1, max_length=4096)
    bucket_id: str | None = Field(default=None, min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=255)


class FreeUpSpaceConfirmRequest(BaseModel):
    media_ids: list[str] = Field(max_length=10_000)


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
        backup = pipeline(request).backup
        if body.kind == "media_store":
            if not body.bucket_id:
                raise BackupSourceInvalidError("invalid_bucket")
            return _source(await backup.add_media_source(body.bucket_id, body.label))
        if not body.path:
            raise BackupSourceInvalidError("invalid_path")
        return _source(await backup.add_source(body.path, body.label))
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
        return {"items": [_suggestion(item) for item in items]}
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


@router.get("/backup/status", response_model=None)
async def backup_status(request: Request) -> dict[str, Any] | JSONResponse:
    """Phone-backup header: pending work, what it waits for, today's progress, and media access."""
    try:
        from bento.domain.device import WaitReason
        from bento.infrastructure import services

        components = pipeline(request)
        settings = request.app.state.settings
        backlog = await components.jobs.backlog(
            types=_BACKUP_JOB_TYPES, deferral=services.get_job_eligibility(settings).current()
        )
        summary = await components.backup.media_summary()
        last = summary["last_backup_at"]
        return {
            "pending": await components.backup.pending_files() + backlog.remaining,
            "waiting": {reason.value: backlog.deferred.get(reason, 0) for reason in WaitReason},
            "uploaded_today": summary["uploaded_today"],
            "last_backup_at": last.isoformat() if last is not None else None,  # type: ignore[union-attr]
            "partial_access": summary["partial_access"],
            "location_access": summary["location_access"],
        }
    except DomainError as exc:
        return error_response(request, exc)


@router.post("/backup/run-now", status_code=202, response_model=None)
async def backup_run_now(request: Request) -> dict[str, Any] | JSONResponse:
    """"Respaldar ahora": lifts the Wi-Fi rule for the current backlog (battery and thermal rules still apply)."""
    try:
        from bento.adapters.device_state import SQLiteRunNowState
        from bento.infrastructure.db.clock import SystemClock
        from bento.infrastructure.db.engine import create_app_session_factory

        components = pipeline(request)
        SQLiteRunNowState(create_app_session_factory(request.app.state.settings), SystemClock()).request()
        await components.backup.enqueue_scans_for_all()
        await components.backup.ensure_upload_job()
        backlog = await components.jobs.backlog(types=_BACKUP_JOB_TYPES)
        return {"accepted": True, "pending": await components.backup.pending_files() + backlog.remaining}
    except DomainError as exc:
        return error_response(request, exc)


@router.get("/backup/free-up-space/preview", response_model=None)
async def free_up_space_preview(request: Request, source_id: str | None = None) -> dict[str, Any] | JSONResponse:
    try:
        preview = await pipeline(request).backup.free_up_space_preview(source_id)
        return {
            "items": [
                {"asset_id": item.asset_id, "media_id": item.media_id, "size_bytes": item.size_bytes} for item in preview.items
            ],
            "total_bytes": preview.total_bytes,
            "count": len(preview.items),
        }
    except DomainError as exc:
        return error_response(request, exc)


@router.post("/backup/free-up-space/confirm", response_model=None)
async def free_up_space_confirm(request: Request, body: FreeUpSpaceConfirmRequest) -> dict[str, Any] | JSONResponse:
    try:
        freed = await pipeline(request).backup.free_up_space_confirm(tuple(str(item)[:64] for item in body.media_ids))
        return {"freed": freed}
    except DomainError as exc:
        return error_response(request, exc)


def _suggestion(item: BackupSuggestion) -> dict[str, Any]:
    body: dict[str, Any] = {"path": item.path, "label": item.label, "kind": item.kind.value}
    if item.bucket_id is not None:
        body.update(
            {"id": item.bucket_id, "name": item.label, "count": item.count or 0, "sample_asset_hint": None, "suggested": item.suggested}
        )
    return body


def _source(source: BackupSource) -> dict[str, Any]:
    return {
        "id": source.id,
        "kind": source.kind.value,
        "bucket_id": source.bucket_id,
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
