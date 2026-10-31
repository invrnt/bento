"""Vault and recovery kit (`/vault`). A recovery code is returned once, only in the response that created it."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from bento.application.vault import VaultService
from bento.domain.errors import DomainError, ValidationFailedError
from bento.domain.vault import VaultStatus
from bento.interfaces.http.qr import QrMatrix, qr_matrix
from bento.interfaces.http.routes_account import domain_error_response

router = APIRouter(prefix="/vault")

RECOVERY_QR_PREFIX = "bento-recovery:"
_NO_STORE = {"Cache-Control": "no-store"}


class VaultUsageResponse(BaseModel):
    files: int
    bytes: int


class VaultStatusResponse(BaseModel):
    state: str
    vault_id: str | None
    created_at: str | None
    recovery_kit_saved: bool
    devices_count: int
    usage: VaultUsageResponse
    other_vaults: int


class CreatedVaultResponse(BaseModel):
    vault: VaultStatusResponse
    recovery_code: str
    recovery_qr: QrMatrix


class RecoveryCodeResponse(BaseModel):
    recovery_code: str
    recovery_qr: QrMatrix


class RecoveryCodeRequest(BaseModel):
    # Checked in code: schema errors (422) would echo the code back.
    recovery_code: str


class LastGroupRequest(BaseModel):
    last_group: str


class VerifyResponse(BaseModel):
    valid: bool


@router.get("", response_model=VaultStatusResponse)
async def vault_status(request: Request) -> Any:
    return await _respond(request, lambda vault: _status_payload(vault.status()))


@router.post("", response_model=CreatedVaultResponse)
async def create_vault(request: Request, response: Response) -> Any:
    async def create(vault: VaultService) -> CreatedVaultResponse:
        created = await vault.create()
        return CreatedVaultResponse(
            vault=vault_status_response(created.status),
            recovery_code=created.recovery_code,
            recovery_qr=recovery_qr(created.recovery_code),
        )

    response.headers.update(_NO_STORE)
    return await _respond(request, create)


@router.post("/unlock", response_model=VaultStatusResponse)
async def unlock_vault(request: Request, body: RecoveryCodeRequest) -> Any:
    return await _respond(request, lambda vault: _status_payload(vault.unlock(_bounded(body.recovery_code))))


@router.post("/recovery-code", response_model=RecoveryCodeResponse)
async def rotate_recovery_code(request: Request, response: Response) -> Any:
    async def rotate(vault: VaultService) -> RecoveryCodeResponse:
        code = await vault.rotate_recovery_code()
        return RecoveryCodeResponse(recovery_code=code, recovery_qr=recovery_qr(code))

    response.headers.update(_NO_STORE)
    return await _respond(request, rotate)


@router.post("/recovery-code/confirm", response_model=VaultStatusResponse)
async def confirm_recovery_kit(request: Request, body: LastGroupRequest) -> Any:
    return await _respond(request, lambda vault: _status_payload(vault.confirm_recovery_kit(_bounded(body.last_group))))


@router.post("/recovery-code/verify", response_model=VerifyResponse)
async def verify_recovery_code(request: Request, body: RecoveryCodeRequest) -> Any:
    async def verify(vault: VaultService) -> VerifyResponse:
        return VerifyResponse(valid=await vault.verify_recovery_code(_bounded(body.recovery_code)))

    return await _respond(request, verify)


def vault_service(request: Request) -> VaultService:
    cached = getattr(request.app.state, "vault_service", None)
    if cached is not None:
        return cached
    from bento.infrastructure.mtproto import wiring

    service = wiring.vault_session(request.app.state.settings)
    request.app.state.vault_service = service
    return service


def vault_status_response(status: VaultStatus) -> VaultStatusResponse:
    return VaultStatusResponse(
        state=status.state.value,
        vault_id=status.vault_id,
        created_at=status.created_at.isoformat() if status.created_at else None,
        recovery_kit_saved=status.recovery_kit_saved,
        devices_count=status.devices_count,
        usage=VaultUsageResponse(files=status.usage.files, bytes=status.usage.bytes),
        other_vaults=status.other_vaults,
    )


def recovery_qr(recovery_code: str) -> QrMatrix:
    """The kit's QR (`bento-recovery:<code>`), drawn by the renderer like every other QR."""
    return qr_matrix(f"{RECOVERY_QR_PREFIX}{recovery_code}")


async def _status_payload(pending: Any) -> VaultStatusResponse:
    return vault_status_response(await pending)


async def _respond(request: Request, call: Any) -> Any:
    try:
        return await call(vault_service(request))
    except DomainError as exc:
        return domain_error_response(request, exc)


def _bounded(value: str, limit: int = 128) -> str:
    if not value.strip() or len(value) > limit:
        raise ValidationFailedError("Invalid recovery code")
    return value
