"""Development-only helpers for the fake Telegram cloud.

The router is always included, but every route answers a plain 404 unless the fake backend is configured
outside production, so it behaves as if it were not registered.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from bento.infrastructure.runtime import approve_fake_telegram_logins
from bento.infrastructure.settings import Settings


def _fake_cloud_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    if settings.storage_backend != "fake" or settings.environment == "production":
        raise HTTPException(status_code=404)
    return settings


router = APIRouter(
    prefix="/dev/fake-telegram",
    include_in_schema=False,
    dependencies=[Depends(_fake_cloud_settings)],
)


class ApproveLoginResponse(BaseModel):
    approved: int


@router.post("/approve-login", response_model=ApproveLoginResponse)
async def approve_login(request: Request) -> ApproveLoginResponse:
    """Approve every pending QR login, as if the phone had scanned it. The instance claims it on its next poll."""
    approved = await asyncio.to_thread(approve_fake_telegram_logins, request.app.state.settings)
    return ApproveLoginResponse(approved=approved)
