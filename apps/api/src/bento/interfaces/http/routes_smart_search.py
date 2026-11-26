"""Smart search (search by meaning) endpoints: `orchestration/api/smart-search-contract.md` §Endpoints.

Every endpoint that changes state answers with the `SmartSearchStatus` body. Business rules live in
`application/smart_search/activation.py`; this module only validates input, maps errors and wires adapters.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from bento.application.settings import EditableSettingsService
from bento.application.smart_search.activation import (
    PROVIDER_SETTING,
    SmartSearchActivationService,
    SmartSearchStatusView,
)
from bento.domain.errors import DomainError, SettingsRevisionConflictError
from bento.interfaces.http.routes_content import error_response

if TYPE_CHECKING:
    from bento.interfaces.http.host_resources import HostResources

router = APIRouter()

_STATUS_CODES = {
    "smart_search_state_conflict": 409,
    "smart_search_no_space": 409,
    "settings_source_locked": 409,
    "invalid_model_spec": 400,
    "invalid_embedding_space": 400,
    "validation_failed": 400,
}


class SmartSearchActivateRequest(BaseModel):
    model_id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    dims: int | None = Field(default=None, ge=1, le=65536)


class SmartSearchDownloadResponse(BaseModel):
    bytes_done: int
    bytes_total: int


class SmartSearchIndexingResponse(BaseModel):
    done: int
    total: int


class SmartSearchModelResponse(BaseModel):
    model_id: str
    display_name: str
    license_spdx: str
    license_url: str
    size_bytes: int
    download_host: str
    dims: int


class SmartSearchUpdateProgressResponse(BaseModel):
    bytes_done: int
    bytes_total: int
    state: str
    """`downloading | verifying | installed | error` (the status itself stays `ready` during an update)."""


class SmartSearchUpdateResponse(BaseModel):
    revision: str
    size_bytes: int
    progress: SmartSearchUpdateProgressResponse | None
    """`null` until the update action started downloading the newer revision."""


class SmartSearchStatusResponse(BaseModel):
    state: str
    """`off | downloading | paused | verifying | starting | indexing | ready | error`."""
    waiting_network: bool
    error_code: str | None
    """`download | checksum | space | runtime`, set exactly when `state` is `error`."""
    failed_step: str | None
    space_id: str | None
    download: SmartSearchDownloadResponse
    indexing: SmartSearchIndexingResponse
    model: SmartSearchModelResponse
    free_bytes: int
    update_available: SmartSearchUpdateResponse | None
    locked: bool
    search_available: bool
    can_use_now: bool
    """A re-embed into a newer space is pending; `POST /api/smart-search/use-now` switches search to it."""
    suggest_in_onboarding: bool
    """D8: `off`, not Android, and this machine has at least 4 cores and 8 GiB of RAM."""


@router.get("/smart-search", response_model=SmartSearchStatusResponse)
async def smart_search_status(request: Request) -> SmartSearchStatusResponse | JSONResponse:
    try:
        return _response(await activation_service(request).status())
    except DomainError as exc:
        return _error(request, exc)


@router.post("/smart-search/activate", response_model=SmartSearchStatusResponse)
async def activate_smart_search(
    request: Request, body: SmartSearchActivateRequest | None = None
) -> SmartSearchStatusResponse | JSONResponse:
    request_body = body or SmartSearchActivateRequest()
    try:
        view = await activation_service(request).activate(request_body.model_id, request_body.dims)
        return _response(view)
    except DomainError as exc:
        return _error(request, exc)


@router.post("/smart-search/pause", response_model=SmartSearchStatusResponse)
async def pause_smart_search(request: Request) -> SmartSearchStatusResponse | JSONResponse:
    try:
        return _response(await activation_service(request).pause())
    except DomainError as exc:
        return _error(request, exc)


@router.post("/smart-search/resume", response_model=SmartSearchStatusResponse)
async def resume_smart_search(request: Request) -> SmartSearchStatusResponse | JSONResponse:
    try:
        return _response(await activation_service(request).resume())
    except DomainError as exc:
        return _error(request, exc)


@router.post("/smart-search/retry", response_model=SmartSearchStatusResponse)
async def retry_smart_search(request: Request) -> SmartSearchStatusResponse | JSONResponse:
    try:
        return _response(await activation_service(request).retry())
    except DomainError as exc:
        return _error(request, exc)


@router.post("/smart-search/cancel", response_model=SmartSearchStatusResponse)
async def cancel_smart_search(request: Request) -> SmartSearchStatusResponse | JSONResponse:
    try:
        return _response(await activation_service(request).cancel())
    except DomainError as exc:
        return _error(request, exc)


@router.post("/smart-search/update", response_model=SmartSearchStatusResponse)
async def update_smart_search_model(request: Request) -> SmartSearchStatusResponse | JSONResponse:
    try:
        return _response(await activation_service(request).update())
    except DomainError as exc:
        return _error(request, exc)


@router.post("/smart-search/use-now", response_model=SmartSearchStatusResponse)
async def use_smart_search_space_now(request: Request) -> SmartSearchStatusResponse | JSONResponse:
    """"Usar ya": search switches to the space being re-embedded before it reaches 100 %."""
    try:
        return _response(await activation_service(request).use_now())
    except DomainError as exc:
        return _error(request, exc)


@router.delete("/smart-search/model", response_model=SmartSearchStatusResponse)
async def remove_smart_search_model(request: Request) -> SmartSearchStatusResponse | JSONResponse:
    try:
        view, _ = await activation_service(request).remove()
        return _response(view)
    except DomainError as exc:
        return _error(request, exc)


@router.get("/smart-search/license", response_class=PlainTextResponse)
async def smart_search_license(request: Request) -> PlainTextResponse:
    from bento.infrastructure.models import license_text

    view = await activation_service(request).status()
    try:
        text = license_text(view.spec.license_spdx)
    except FileNotFoundError:
        return PlainTextResponse("License text not available", status_code=404)
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")


# ------------------------------------------------------------------------------------------


def _response(view: SmartSearchStatusView) -> SmartSearchStatusResponse:
    return SmartSearchStatusResponse.model_validate(view.body())


def _error(request: Request, error: DomainError) -> JSONResponse:
    response = error_response(request, error)
    response.status_code = _STATUS_CODES.get(error.code, response.status_code)
    return response


def activation_service(request: Request) -> SmartSearchActivationService:
    cached = getattr(request.app.state, "smart_search_activation", None)
    if cached is not None:
        return cached

    from bento.adapters.jobs.sqlite_queue import SQLiteJobQueue
    from bento.adapters.models.sqlite_status import SQLiteSmartSearchStatusRepository
    from bento.adapters.repositories import SQLiteAssetRepository
    from bento.adapters.search.sqlite_vec import SQLiteVecSearchIndex
    from bento.application.smart_search.activation import NoopSmartSearchHooks
    from bento.application.smart_search.reembed import ReembedService
    from bento.infrastructure.db.clock import SystemClock
    from bento.infrastructure.db.engine import create_session_factory, sqlite_url
    from bento.infrastructure.models import model_store, packaged_model_catalog
    from bento.interfaces.http.host_resources import host_resources
    from bento.interfaces.http.routes_settings import _service as settings_service

    settings = request.app.state.settings
    clock = SystemClock()
    session_factory = create_session_factory(sqlite_url(request.app.state.settings_database_path))
    jobs = SQLiteJobQueue(session_factory, clock)
    vectors = SQLiteVecSearchIndex(session_factory, clock)
    # The API only flips spaces ("Usar ya"); the worker runs the `reembed` jobs. The activation service
    # moves the status and deletes old model files itself, so this needs no observer, catalog or store.
    reembed = ReembedService(
        assets=SQLiteAssetRepository(session_factory),
        spaces=vectors,
        vectors=vectors,
        jobs=jobs,
        active=jobs,
        clock=clock,
    )
    service = SmartSearchActivationService(
        catalog=packaged_model_catalog(),
        store=model_store(settings.data_dir),
        repository=SQLiteSmartSearchStatusRepository(session_factory, clock),
        jobs=jobs,
        provider_switch=SettingsProviderSwitch(settings_service(request)),
        hooks=getattr(request.app.state, "smart_search_hooks", None) or NoopSmartSearchHooks(),
        spaces=vectors,
        reembed=reembed,
        platform=str(getattr(settings, "platform", "auto")),
        host_resources=_host_resources(host_resources),
    )
    request.app.state.smart_search_activation = service
    return service


def _host_resources(probe: Callable[[], HostResources]) -> Callable[[], tuple[int, int]]:
    def read() -> tuple[int, int]:
        resources = probe()
        return resources.cpu_cores, resources.ram_bytes

    return read


class SettingsProviderSwitch:
    """`embeddings_provider` through the editable settings service (the env/policy lock comes from there)."""

    def __init__(self, service: EditableSettingsService) -> None:
        self._service = service

    async def locked(self) -> bool:
        snapshot = await self._service.snapshot()
        item = snapshot.values.get(PROVIDER_SETTING)
        return item is not None and item.locked

    async def enable(self) -> None:
        await self._set("managed", only_from=None)

    async def disable(self) -> None:
        await self._set("disabled", only_from="managed")

    async def _set(self, value: str, *, only_from: str | None) -> None:
        for _ in range(2):
            snapshot = await self._service.snapshot()
            item = snapshot.values.get(PROVIDER_SETTING)
            current: Any = item.value if item is not None else None
            if current == value or (only_from is not None and current != only_from):
                return
            if item is not None and item.locked and only_from is not None:
                return  # turning off never fights an environment lock
            try:
                await self._service.apply(expected_revision=snapshot.revision, values={PROVIDER_SETTING: value})
                return
            except SettingsRevisionConflictError:
                continue
