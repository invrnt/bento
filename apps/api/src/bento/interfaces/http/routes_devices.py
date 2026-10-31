"""Device endpoints (`orchestration/api/telegram-first-endpoints.md` § Devices).

`DELETE /devices/{id}` is the only response that carries a secret: the freshly generated recovery
code of the rotated vault (and its kit QR), returned exactly once. `GET /devices/{id}/removal-preview` lists
who would receive the new keys, and the optional `exclude_device_ids` body of the removal leaves unknown
devices out of them (they are removed as well).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bento.application.devices import DeviceService
from bento.domain.devices import Device
from bento.domain.errors import DomainError
from bento.interfaces.http.qr import QrMatrix, qr_matrix
from bento.interfaces.http.routes_pairing import domain_error_response, get_device_service

RECOVERY_QR_PREFIX = "bento-recovery:"

router = APIRouter(tags=["devices"])


class DeviceResponse(BaseModel):
    id: str
    name: str
    platform: str
    added_at: str
    last_seen_at: str | None
    current: bool
    removed_at: str | None
    introduced_by: str | None = None
    """Device whose sync data first introduced this one here; null when it was added on this device."""
    first_seen_at: str | None = None
    needs_review: bool = False


class DevicesResponse(BaseModel):
    items: list[DeviceResponse]


class DeviceRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)


class DeviceRemovalRequest(BaseModel):
    exclude_device_ids: list[str] = Field(default_factory=list, max_length=256)


class DeviceRemovalPreviewResponse(BaseModel):
    recipients: list[DeviceResponse]


class DeviceRemovalResponse(BaseModel):
    device: DeviceResponse
    telegram_session_closed: bool
    recovery_code: str
    recovery_qr: QrMatrix
    removed_device_ids: list[str]
    """The removed device and every excluded one."""


@router.get("/devices", response_model=DevicesResponse)
async def list_devices(
    request: Request, include_removed: bool = False, service: DeviceService = Depends(get_device_service)
) -> DevicesResponse | JSONResponse:
    try:
        devices = await service.list(include_removed=include_removed)
    except DomainError as exc:
        return domain_error_response(request, exc)
    return DevicesResponse(items=[device_response(device) for device in devices])


@router.patch("/devices/{device_id}", response_model=DeviceResponse)
async def rename_device(
    device_id: str, body: DeviceRenameRequest, request: Request, service: DeviceService = Depends(get_device_service)
) -> DeviceResponse | JSONResponse:
    try:
        device = await service.rename(device_id, body.name)
    except DomainError as exc:
        return domain_error_response(request, exc)
    return device_response(device)


@router.get("/devices/{device_id}/removal-preview", response_model=DeviceRemovalPreviewResponse)
async def preview_device_removal(
    device_id: str, request: Request, service: DeviceService = Depends(get_device_service)
) -> DeviceRemovalPreviewResponse | JSONResponse:
    try:
        recipients = await service.removal_preview(device_id)
    except DomainError as exc:
        return domain_error_response(request, exc)
    return DeviceRemovalPreviewResponse(recipients=[device_response(device) for device in recipients])


@router.post("/devices/{device_id}/acknowledge", response_model=DeviceResponse)
async def acknowledge_device(
    device_id: str, request: Request, service: DeviceService = Depends(get_device_service)
) -> DeviceResponse | JSONResponse:
    try:
        device = await service.acknowledge(device_id)
    except DomainError as exc:
        return domain_error_response(request, exc)
    return device_response(device)


@router.delete("/devices/{device_id}", response_model=DeviceRemovalResponse)
async def remove_device(
    device_id: str,
    request: Request,
    body: DeviceRemovalRequest | None = None,
    service: DeviceService = Depends(get_device_service),
) -> DeviceRemovalResponse | JSONResponse:
    try:
        removal = await service.remove(device_id, exclude_device_ids=body.exclude_device_ids if body else ())
    except DomainError as exc:
        return domain_error_response(request, exc)
    return DeviceRemovalResponse(
        device=device_response(removal.device),
        telegram_session_closed=removal.telegram_session_closed,
        recovery_code=removal.recovery_code,
        recovery_qr=qr_matrix(RECOVERY_QR_PREFIX + removal.recovery_code),
        removed_device_ids=[removal.device.id, *(device.id for device in removal.excluded)],
    )


def device_response(device: Device) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        name=device.name,
        platform=device.platform.value,
        added_at=device.added_at.isoformat(),
        last_seen_at=device.last_seen_at.isoformat() if device.last_seen_at is not None else None,
        current=device.current,
        removed_at=device.removed_at.isoformat() if device.removed_at is not None else None,
        introduced_by=device.introduced_by,
        first_seen_at=device.first_seen_at.isoformat() if device.first_seen_at is not None else None,
        needs_review=device.needs_review,
    )
