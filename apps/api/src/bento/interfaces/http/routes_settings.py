from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bento.adapters.settings import SQLiteSettingsRepository
from bento.application.settings import EditableSettingsService
from bento.domain.errors import DomainError
from bento.domain.settings import SecretReferenceMutation, SettingSource
from bento.domain.settings_registry import SETTINGS_BY_KEY, SETTINGS_REGISTRY, choices_for, is_advanced, is_hidden
from bento.infrastructure.db.clock import SystemClock
from bento.infrastructure.db.engine import create_session_factory, sqlite_url
from bento.ports.models import ModelCatalogPort

LOGGER = logging.getLogger("bento.http.settings")

router = APIRouter()


class SecretReferenceRequest(BaseModel):
    reference: str | None = Field(default=None, max_length=256)
    configured: bool


class SettingsDraftRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    secret_references: dict[str, SecretReferenceRequest] = Field(default_factory=dict)
    run_probes: bool = False


class SettingsPatchRequest(SettingsDraftRequest):
    revision: int = Field(ge=0)


class SettingsImportPreviewRequest(BaseModel):
    content: str = Field(max_length=1024 * 1024)


@router.get("/settings/schema")
async def settings_schema(request: Request) -> dict[str, Any]:
    snapshot = await _service(request).snapshot()
    platform = str(snapshot.values["platform"].value or "auto")
    return {
        "revision": snapshot.revision,
        "platform": platform,
        "fields": [
            {
                "key": definition.key,
                "group": definition.group,
                "label_key": definition.label_key,
                "help_key": definition.help_key,
                "type": definition.value_type.value,
                "default": None if definition.secret else definition.default,
                "constraints": {
                    "choices": list(choices_for(definition.key, platform)),
                    "minimum": definition.minimum,
                    "maximum": definition.maximum,
                },
                "secret": definition.secret,
                "editable": definition.editable,
                "availability": definition.availability.value,
                "apply_mode": definition.apply_mode.value,
                "env_aliases": list(definition.env_aliases),
                "probe": definition.probe,
                "source": snapshot.values[definition.key].source.value,
                "locked": snapshot.values[definition.key].locked,
                "advanced": is_advanced(definition.key),
                "hidden": is_hidden(definition.key, platform),
            }
            for definition in SETTINGS_REGISTRY
        ],
    }


@router.get("/settings/values")
async def settings_values(request: Request) -> dict[str, Any]:
    return _snapshot_response(await _service(request).snapshot())


@router.post("/settings/validate")
async def validate_settings(request: Request, body: SettingsDraftRequest) -> dict[str, Any]:
    result = await _service(request).validate(
        body.values,
        _secret_references(body.secret_references),
        run_probes=body.run_probes,
    )
    return _validation_response(result)


@router.patch("/settings/values", response_model=None)
async def patch_settings(request: Request, body: SettingsPatchRequest) -> dict[str, Any] | JSONResponse:
    try:
        snapshot, restart_plan = await _service(request).apply(
            expected_revision=body.revision,
            values=body.values,
            secret_references=_secret_references(body.secret_references),
        )
        response = _snapshot_response(snapshot)
        response["restart_plan"] = _restart_plan_response(restart_plan)
        return response
    except DomainError as exc:
        return _error_response(request, exc)


@router.post("/settings/import/preview")
async def import_settings_preview(request: Request, body: SettingsImportPreviewRequest) -> dict[str, Any]:
    return await _service(request).import_preview(body.content)


@router.get("/settings/export")
async def export_settings(request: Request) -> dict[str, Any]:
    return await _service(request).export()


def _service(request: Request) -> EditableSettingsService:
    cached = getattr(request.app.state, "editable_settings_service", None)
    if cached is not None:
        return cached
    settings = request.app.state.settings
    database_path = request.app.state.settings_database_path
    repository = SQLiteSettingsRepository(
        create_session_factory(sqlite_url(database_path)),
        SystemClock(),
    )
    effective = settings.effective_snapshot
    environment: dict[str, str] = {}
    policy_values: dict[str, Any] = {}
    if effective is not None:
        for key, item in effective.values.items():
            definition = SETTINGS_BY_KEY[key]
            if item.source == SettingSource.ENVIRONMENT:
                environment[definition.env_aliases[0]] = "configured" if definition.secret else str(item.value)
            elif item.source == SettingSource.POLICY and not definition.secret:
                policy_values[key] = item.value
    service = EditableSettingsService(
        repository=repository,
        environ=environment,
        runtime_mode=settings.runtime_mode,
        policy_values=policy_values,
        bootstrap_values={"data_dir": settings.data_dir} if settings.runtime_mode == "desktop" else {},
        model_catalog=_model_catalog(),
    )
    request.app.state.editable_settings_service = service
    return service


def _model_catalog() -> ModelCatalogPort | None:
    """The packaged manifest, so `smart_search_model`/`embedding_dimensions` validate against it."""
    from bento.infrastructure.models import packaged_model_catalog

    try:
        return packaged_model_catalog()
    except (OSError, ValueError, DomainError) as exc:  # a broken manifest falls back to the registry mirror
        LOGGER.warning("Could not read the packaged model manifest: %s", exc.__class__.__name__)
        return None


def _secret_references(values: dict[str, SecretReferenceRequest]) -> dict[str, SecretReferenceMutation]:
    return {
        key: SecretReferenceMutation(reference=value.reference, configured=value.configured)
        for key, value in values.items()
    }


def _snapshot_response(snapshot: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, item in snapshot.values.items():
        definition = SETTINGS_BY_KEY[key]
        entry: dict[str, Any] = {
            "source": item.source.value,
            "locked": item.locked,
            "apply_mode": definition.apply_mode.value,
        }
        if definition.secret:
            entry["configured"] = bool(item.configured)
        else:
            entry["value"] = item.value
        values[key] = entry
    return {"revision": snapshot.revision, "values": values}


def _validation_response(result: Any) -> dict[str, Any]:
    return {
        "valid": result.valid,
        "errors": [{"key": issue.key, "code": issue.code, "message": issue.message} for issue in result.errors],
        "warnings": [{"key": issue.key, "code": issue.code, "message": issue.message} for issue in result.warnings],
        "probes": [{"key": probe.key, "status": probe.status, "message": probe.message} for probe in result.probes],
        "restart_plan": _restart_plan_response(result.restart_plan),
    }


def _restart_plan_response(plan: Any) -> dict[str, Any]:
    return {
        "mode": plan.mode.value,
        "affected_keys": list(plan.affected_keys),
        "services": list(plan.services),
    }


def _error_response(request: Request, error: DomainError) -> JSONResponse:
    status = 409 if error.code == "settings_revision_conflict" else 400
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "details": error.details,
                "request_id": request_id,
            }
        },
    )
