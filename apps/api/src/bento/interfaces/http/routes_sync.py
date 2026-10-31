"""`/sync/status` and `/sync/now` (contract: `orchestration/api/telegram-first-endpoints.md` § Sync)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from bento.domain.sync import SyncStatus
from bento.infrastructure.services import get_sync_status_provider
from bento.infrastructure.settings import Settings

router = APIRouter(prefix="/sync")

_ERROR_MESSAGES = {
    "telegram_flood_wait": "Telegram asked to wait before retrying",
    "telegram_network": "Telegram is unreachable",
    "telegram_not_authorized": "This device is not signed in to Telegram",
    "vault_locked": "This device has not been granted access to the vault",
    "vault_not_found": "No Bento vault exists in this Telegram account",
    "storage_unavailable": "Telegram is unreachable",
    "device_removed": "Another device removed this one from the vault; join again to sync",
    "clock_skew": "This device's clock is more than 5 minutes off; fix it so devices keep each other's changes",
}


class SyncBootstrapResponse(BaseModel):
    done: int
    total: int


class SyncErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, object] = {}


class SyncStatusResponse(BaseModel):
    state: str
    pending_ops: int
    last_push_at: str | None
    last_pull_at: str | None
    bootstrap: SyncBootstrapResponse | None
    waiting_until: str | None
    error: SyncErrorResponse | None


class SyncNowResponse(BaseModel):
    accepted: bool


@router.get("/status", response_model=SyncStatusResponse)
async def sync_status(request: Request) -> SyncStatusResponse:
    status = await get_sync_status_provider(_settings(request)).status()
    return _status_response(status)


@router.post("/now", response_model=SyncNowResponse)
async def sync_now(request: Request) -> SyncNowResponse:
    settings = _settings(request)
    if settings.storage_backend == "local":
        return SyncNowResponse(accepted=False)
    await get_sync_status_provider(settings).request_sync()
    return SyncNowResponse(accepted=True)


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _status_response(status: SyncStatus) -> SyncStatusResponse:
    return SyncStatusResponse(
        state=status.state.value,
        pending_ops=status.pending_ops,
        last_push_at=_iso(status.last_push_at),
        last_pull_at=_iso(status.last_pull_at),
        bootstrap=None
        if status.bootstrap is None
        else SyncBootstrapResponse(done=status.bootstrap.done, total=status.bootstrap.total),
        waiting_until=_iso(status.waiting_until),
        error=None
        if status.error_code is None
        else SyncErrorResponse(
            code=status.error_code,
            message=_ERROR_MESSAGES.get(status.error_code, "Sync failed; it will retry"),
            details=_error_details(status),
        ),
    )


def _error_details(status: SyncStatus) -> dict[str, object]:
    if status.error_code != "clock_skew" or status.clock_skew_ms is None:
        return {}
    return {
        "direction": "ahead" if status.clock_skew_ms > 0 else "behind",
        "skew_seconds": abs(status.clock_skew_ms) // 1000,
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
