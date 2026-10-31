"""Telegram sign-in (`/account`). Sessions, login tokens, codes, and passwords never appear in responses."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bento.application.account import AccountService
from bento.domain.account import AccountStatus, TelegramAccount
from bento.domain.errors import DomainError, TelegramFloodWaitError, ValidationFailedError
from bento.interfaces.http.qr import QrMatrix, qr_matrix

router = APIRouter(prefix="/account")

ERROR_MESSAGES = {
    "telegram_not_available": "This build has no Telegram application credentials",
    "telegram_login_expired": "The login expired; start again",
    "telegram_code_invalid": "The login code is not valid",
    "telegram_password_invalid": "The password is not valid",
    "telegram_phone_invalid": "The phone number is not valid",
    "telegram_flood_wait": "Telegram asked to wait before retrying",
    "telegram_network": "Telegram could not be reached",
    "telegram_not_authorized": "This device is not signed in to Telegram",
}
_STATUS_CODES = {
    "telegram_not_available": 503,
    "telegram_network": 503,
    "storage_unavailable": 503,
    "telegram_flood_wait": 429,
    "telegram_login_expired": 409,
    "telegram_not_authorized": 409,
    "telegram_session_too_new": 409,
    "vault_locked": 409,
    "vault_already_exists": 409,
    "integrity_failed": 409,
    "vault_not_found": 404,
    "asset_not_found": 404,
    "avatar_not_found": 404,
}


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class TelegramAccountResponse(BaseModel):
    user_id: int
    display_name: str
    username: str | None
    phone_masked: str | None
    premium: bool


class AccountStatusResponse(BaseModel):
    step: str
    account: TelegramAccountResponse | None
    qr_url: str | None
    qr: QrMatrix | None
    qr_expires_at: str | None
    password_hint: str | None
    error: ErrorBody | None


# Length limits are checked in code: schema errors (422) would echo the submitted secret back.
class PhoneRequest(BaseModel):
    phone: str


class CodeRequest(BaseModel):
    code: str


class PasswordRequest(BaseModel):
    password: str


@router.get("", response_model=AccountStatusResponse)
async def account_status(request: Request) -> AccountStatusResponse | JSONResponse:
    return await _respond(request, lambda service: service.status())


@router.post("/login/qr", response_model=AccountStatusResponse)
async def start_qr_login(request: Request) -> AccountStatusResponse | JSONResponse:
    return await _respond(request, lambda service: service.start_qr_login())


@router.post("/login/phone", response_model=AccountStatusResponse)
async def start_phone_login(request: Request, body: PhoneRequest) -> AccountStatusResponse | JSONResponse:
    return await _respond(request, lambda service: service.start_phone_login(_bounded(body.phone, 32, "phone")))


@router.post("/login/code", response_model=AccountStatusResponse)
async def submit_code(request: Request, body: CodeRequest) -> AccountStatusResponse | JSONResponse:
    return await _respond(request, lambda service: service.submit_code(_bounded(body.code, 16, "code")))


@router.post("/login/password", response_model=AccountStatusResponse)
async def submit_password(request: Request, body: PasswordRequest) -> AccountStatusResponse | JSONResponse:
    return await _respond(request, lambda service: service.submit_password(_bounded(body.password, 256, "password")))


@router.post("/logout", response_model=AccountStatusResponse)
async def log_out(request: Request) -> AccountStatusResponse | JSONResponse:
    return await _respond(request, lambda service: service.log_out())


@router.get("/avatar", response_model=None)
async def avatar(request: Request) -> Response:
    try:
        jpeg = await account_service(request).avatar_jpeg()
    except DomainError as exc:
        return domain_error_response(request, exc)
    if not jpeg:
        return domain_error_response(request, DomainError("avatar_not_found", "This account has no profile photo"))
    return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


def account_service(request: Request) -> AccountService:
    cached = getattr(request.app.state, "account_service", None)
    if cached is not None:
        return cached
    from bento.infrastructure.mtproto import wiring

    service = wiring.account_service(request.app.state.settings)
    request.app.state.account_service = service
    return service


def account_status_response(status: AccountStatus) -> AccountStatusResponse:
    """The public view of a login state; `qr_token` (pairing only) is never serialized."""
    error = None
    if status.error_code is not None:
        details: dict[str, Any] = {}
        if status.retry_after_seconds is not None:
            details["retry_after_seconds"] = status.retry_after_seconds
        error = ErrorBody(
            code=status.error_code, message=ERROR_MESSAGES.get(status.error_code, "Telegram sign-in failed"), details=details
        )
    return AccountStatusResponse(
        step=status.step.value,
        account=_account_response(status.account),
        qr_url=status.qr_url,
        qr=qr_matrix(status.qr_url) if status.qr_url else None,
        qr_expires_at=status.qr_expires_at.isoformat() if status.qr_expires_at else None,
        password_hint=status.password_hint,
        error=error,
    )


def domain_error_response(request: Request, error: DomainError) -> JSONResponse:
    """The API error model for the Telegram-first routes (account, vault, telegram)."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    headers = {"Cache-Control": "no-store"}
    if isinstance(error, TelegramFloodWaitError):
        headers["Retry-After"] = str(error.retry_after_seconds)
    return JSONResponse(
        status_code=_STATUS_CODES.get(error.code, 400),
        headers=headers,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "details": error.details,
                "request_id": request_id,
            }
        },
    )


async def _respond(request: Request, call: Any) -> AccountStatusResponse | JSONResponse:
    try:
        status = await call(account_service(request))
    except DomainError as exc:
        return domain_error_response(request, exc)
    return account_status_response(status)


def _bounded(value: str, limit: int, field: str) -> str:
    if not value.strip() or len(value) > limit:
        raise ValidationFailedError("Invalid value", {"field": field})
    return value


def _account_response(account: TelegramAccount | None) -> TelegramAccountResponse | None:
    if account is None:
        return None
    return TelegramAccountResponse(
        user_id=account.user_id,
        display_name=account.display_name,
        username=account.username,
        phone_masked=account.phone_masked,
        premium=account.premium,
    )
