"""Pairing endpoints (`orchestration/api/telegram-first-endpoints.md` § Pairing) and their composition root.

Responses never include login tokens, keys, or the peer's secrets. The only pairing secret ever
returned is the host's own code (with its link and QR) while its session is live.
"""

from __future__ import annotations

import socket
import sys
import uuid
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import NoReturn, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.pairing import WebSocketPairingRelay
from bento.adapters.repositories.devices import SQLiteDeviceRepository
from bento.adapters.security import verify_commitment
from bento.application.devices import DeviceService
from bento.application.pairing import LocalDeviceInfo, PairingRequestView, PairingService, PairingView
from bento.domain.devices import DevicePlatform
from bento.domain.errors import DomainError, TelegramNotConfiguredError
from bento.infrastructure import services
from bento.infrastructure.db.engine import create_app_session_factory
from bento.infrastructure.runtime import get_telegram_runtime
from bento.infrastructure.settings import Settings
from bento.interfaces.http.qr import QrMatrix, qr_matrix

_live_services: weakref.WeakSet[PairingService] = weakref.WeakSet()


async def _close_pairing_sessions() -> None:
    for service in list(_live_services):
        await service.close()


router = APIRouter(tags=["pairing"], on_shutdown=[_close_pairing_sessions])


# Composition ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PairingComponents:
    pairing: PairingService
    devices: DeviceService


def build_pairing_components(settings: Settings) -> PairingComponents:
    """Wire pairing and device management from the Stage 15 factories. Not available in local-only mode."""
    if settings.storage_backend == "local":
        raise TelegramNotConfiguredError()
    key_store = services.get_key_store(settings)
    runtime = get_telegram_runtime(settings, key_store)
    if runtime is None:
        raise TelegramNotConfiguredError()
    vault = services.get_vault_session(settings)
    vault_crypto = services.get_vault_crypto()
    devices = SQLiteDeviceRepository(device_session_factory(settings))
    pairing = PairingService(
        relay=WebSocketPairingRelay(settings.relay_url),
        crypto=services.get_pairing_crypto(),
        vault_crypto=vault_crypto,
        vault=vault,
        account=runtime.account,
        transport=runtime.transport,
        devices=devices,
        verify_commitment=verify_commitment,
        local_device=local_device_info(settings),
    )
    _live_services.add(pairing)
    return PairingComponents(
        pairing=pairing,
        devices=DeviceService(
            devices=devices,
            vault=vault,
            account=runtime.account,
            transport=runtime.transport,
            crypto=vault_crypto,
        ),
    )


def device_session_factory(settings: Settings) -> sessionmaker[Session]:
    """Session factory for the `devices` table, with sync change capture installed."""
    return create_app_session_factory(settings)


def local_device_info(settings: Settings) -> LocalDeviceInfo:
    platform, label = _platform()
    hostname = socket.gethostname().split(".", 1)[0].strip() or "Bento"
    return LocalDeviceInfo(name=f"{hostname} · {label}"[:64], platform=platform, app_version=settings.app_version)


def _platform() -> tuple[DevicePlatform, str]:
    if sys.platform.startswith("linux"):
        return DevicePlatform.LINUX, "Linux"
    if sys.platform == "darwin":
        return DevicePlatform.MACOS, "macOS"
    if sys.platform == "win32":
        return DevicePlatform.WINDOWS, "Windows"
    return DevicePlatform.OTHER, sys.platform


class _Unavailable:
    """Stands in for a service that cannot exist in this configuration; every call raises `error`.

    Raising inside the route keeps the API error model (a dependency error would become a 500).
    """

    def __init__(self, error: DomainError) -> None:
        self._error = error

    def __getattr__(self, name: str) -> Callable[..., Awaitable[NoReturn]]:
        async def unavailable(*args: object, **kwargs: object) -> NoReturn:
            raise self._error

        return unavailable


async def pairing_components(request: Request) -> PairingComponents:
    state = request.app.state
    components: PairingComponents | None = getattr(state, "pairing_components", None)
    if components is None:
        try:
            components = build_pairing_components(state.settings)
        except DomainError as exc:
            stand_in = _Unavailable(exc)
            return PairingComponents(pairing=cast(PairingService, stand_in), devices=cast(DeviceService, stand_in))
        state.pairing_components = components
    return components


async def get_pairing_service(components: PairingComponents = Depends(pairing_components)) -> PairingService:
    return components.pairing


async def get_device_service(components: PairingComponents = Depends(pairing_components)) -> DeviceService:
    return components.devices


# Schemas --------------------------------------------------------------------------------------


class PairingPeerResponse(BaseModel):
    device_name: str
    platform: str


class PairingErrorResponse(BaseModel):
    code: str
    message: str


class PairingResponse(BaseModel):
    id: str
    role: str
    transport: str
    state: str
    code: str | None
    link: str | None
    web_link: str | None
    qr: QrMatrix | None
    expires_at: str
    peer: PairingPeerResponse | None
    sas: list[str] | None
    telegram_qr: QrMatrix | None
    error: PairingErrorResponse | None


class PairingJoinRequest(BaseModel):
    code: str = Field(min_length=1, max_length=512)


class PairingRequestItem(BaseModel):
    id: str
    device_name: str
    platform: str
    created_at: str


class PairingRequestsResponse(BaseModel):
    items: list[PairingRequestItem]


# Routes ---------------------------------------------------------------------------------------
# `/pairing/requests…` is declared before `/pairing/{pairing_id}` so it is never captured as an id.


@router.get("/pairing/requests", response_model=PairingRequestsResponse)
async def list_pairing_requests(
    request: Request, service: PairingService = Depends(get_pairing_service)
) -> PairingRequestsResponse | JSONResponse:
    try:
        items = await service.list_requests()
    except DomainError as exc:
        return domain_error_response(request, exc)
    return PairingRequestsResponse(items=[_request_item(item) for item in items])


@router.post("/pairing/requests/{request_id}/review", response_model=PairingResponse)
async def review_pairing_request(
    request_id: str, request: Request, service: PairingService = Depends(get_pairing_service)
) -> PairingResponse | JSONResponse:
    return await _respond(request, service.review_request(request_id))


@router.post("/pairing/requests/{request_id}/approve", response_model=PairingResponse)
async def approve_pairing_request(
    request_id: str, request: Request, service: PairingService = Depends(get_pairing_service)
) -> PairingResponse | JSONResponse:
    return await _respond(request, service.approve_request(request_id))


@router.post("/pairing/requests/{request_id}/reject", response_model=PairingResponse)
async def reject_pairing_request(
    request_id: str, request: Request, service: PairingService = Depends(get_pairing_service)
) -> PairingResponse | JSONResponse:
    return await _respond(request, service.reject_request(request_id))


@router.post("/pairing/host", response_model=PairingResponse)
async def host_pairing(request: Request, service: PairingService = Depends(get_pairing_service)) -> PairingResponse | JSONResponse:
    return await _respond(request, service.host())


@router.post("/pairing/join", response_model=PairingResponse)
async def join_pairing(
    body: PairingJoinRequest, request: Request, service: PairingService = Depends(get_pairing_service)
) -> PairingResponse | JSONResponse:
    return await _respond(request, service.join(body.code))


@router.post("/pairing/request", response_model=PairingResponse)
async def request_pairing(request: Request, service: PairingService = Depends(get_pairing_service)) -> PairingResponse | JSONResponse:
    return await _respond(request, service.request_access())


@router.get("/pairing/{pairing_id}", response_model=PairingResponse)
async def get_pairing(
    pairing_id: str, request: Request, service: PairingService = Depends(get_pairing_service)
) -> PairingResponse | JSONResponse:
    return await _respond(request, service.get(pairing_id))


@router.post("/pairing/{pairing_id}/approve", response_model=PairingResponse)
async def approve_pairing(
    pairing_id: str, request: Request, service: PairingService = Depends(get_pairing_service)
) -> PairingResponse | JSONResponse:
    return await _respond(request, service.approve(pairing_id))


@router.post("/pairing/{pairing_id}/reject", response_model=PairingResponse)
async def reject_pairing(
    pairing_id: str, request: Request, service: PairingService = Depends(get_pairing_service)
) -> PairingResponse | JSONResponse:
    return await _respond(request, service.reject(pairing_id))


@router.delete("/pairing/{pairing_id}", response_model=PairingResponse)
async def cancel_pairing(
    pairing_id: str, request: Request, service: PairingService = Depends(get_pairing_service)
) -> PairingResponse | JSONResponse:
    return await _respond(request, service.cancel(pairing_id))


# Mapping --------------------------------------------------------------------------------------


async def _respond(request: Request, call: Awaitable[PairingView]) -> PairingResponse | JSONResponse:
    try:
        view: PairingView = await call
    except DomainError as exc:
        return domain_error_response(request, exc)
    return pairing_response(view, site_url=request.app.state.settings.public_site_url)


def pairing_response(view: PairingView, *, site_url: str = "") -> PairingResponse:
    session = view.session
    code = session.code
    return PairingResponse(
        id=session.id,
        role=session.role.value,
        transport=session.transport.value,
        state=session.state.value,
        code=code.format() if code is not None else None,
        link=code.link() if code is not None else None,
        web_link=code.web_link(site_url) if code is not None and site_url.strip() else None,
        qr=qr_matrix(code.link()) if code is not None else None,
        expires_at=session.expires_at.isoformat(),
        peer=PairingPeerResponse(device_name=session.peer.device_name, platform=session.peer.platform)
        if session.peer is not None
        else None,
        sas=list(session.sas) if session.sas is not None else None,
        telegram_qr=qr_matrix(view.telegram_login_url) if view.telegram_login_url else None,
        error=PairingErrorResponse(code=session.error_code, message=view.error_message or "Pairing failed")
        if session.error_code is not None
        else None,
    )


def _request_item(item: PairingRequestView) -> PairingRequestItem:
    return PairingRequestItem(
        id=item.id, device_name=item.device_name, platform=item.platform.value, created_at=item.created_at.isoformat()
    )


_NOT_FOUND = frozenset({"pairing_not_found", "pairing_request_not_found", "pairing_room_not_found", "device_not_found"})
_CONFLICT = frozenset(
    {
        "pairing_state_conflict",
        "pairing_already_paired",
        "pairing_room_full",
        "pairing_nameplate_taken",
        "pairing_expired",
        "pairing_request_expired",
        "vault_locked",
        "vault_not_found",
        "telegram_not_authorized",
        "device_is_current",
        "device_removed",
    }
)
_TOO_MANY = frozenset({"pairing_rate_limited", "telegram_flood_wait"})
_UNAVAILABLE = frozenset(
    {
        "pairing_relay_unavailable",
        "telegram_not_configured",
        "telegram_not_available",
        "telegram_network",
        "storage_unavailable",
        "device_rotation_incomplete",
    }
)


def domain_error_response(request: Request, error: DomainError) -> JSONResponse:
    """Error model of `api/error-model.md` for pairing and device routes."""
    if error.code in _NOT_FOUND:
        status = 404
    elif error.code in _CONFLICT:
        status = 409
    elif error.code in _TOO_MANY:
        status = 429
    elif error.code in _UNAVAILABLE:
        status = 503
    else:
        status = 400
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "details": error.details,
                "request_id": request.headers.get("x-request-id") or uuid.uuid4().hex,
            }
        },
    )
