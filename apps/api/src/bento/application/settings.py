from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import replace
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bento.domain.errors import SettingsSourceLockedError, ValidationFailedError
from bento.domain.settings import (
    EffectiveSetting,
    EffectiveSettingsSnapshot,
    FieldIssue,
    PersistedSettings,
    ProbeResult,
    PublicSettings,
    RestartPlan,
    SecretReferenceMutation,
    SettingApplyMode,
    SettingSource,
    SettingValueType,
    SettingsValidationResult,
)
from bento.domain.settings_registry import (
    LEGACY_CUSTOM_MODEL_PATH,
    MANAGED_MODEL_DIMS,
    SETTINGS_BY_ALIAS,
    SETTINGS_BY_KEY,
    SETTINGS_REGISTRY,
    embeddings_provider_choices,
    platform_default,
)
from bento.domain.smart_search import EMBEDDINGS_PROVIDER_CHOICES, InvalidModelSpecError, migrate_embeddings_provider
from bento.ports.models import ModelCatalogPort
from bento.ports.settings import SettingsRepositoryPort


_APPLY_RANK = {
    SettingApplyMode.LIVE: 0,
    SettingApplyMode.RESTART_WORKER: 1,
    SettingApplyMode.RESTART_SERVICES: 2,
    SettingApplyMode.RESTART_APP: 3,
}


def resolve_effective_settings(
    *,
    persisted: PersistedSettings,
    environ: Mapping[str, str],
    runtime_mode: str,
    policy_values: Mapping[str, Any] | None = None,
) -> EffectiveSettingsSnapshot:
    policy = policy_values or {}
    platform = str(policy.get("platform") or _environment_value(("BENTO_PLATFORM",), environ) or "auto")
    values: dict[str, EffectiveSetting] = {}
    for definition in SETTINGS_REGISTRY:
        default = platform_default(definition.key, platform)
        environment_value = _environment_value(definition.env_aliases, environ)
        saved = persisted.values.get(definition.key)
        secret_reference = persisted.secret_references.get(definition.key)

        if definition.key in policy:
            raw, source, locked = policy[definition.key], SettingSource.POLICY, True
        elif runtime_mode == "headless" and environment_value is not None:
            raw, source, locked = environment_value, SettingSource.ENVIRONMENT, True
        elif saved is not None and not definition.secret:
            raw, source, locked = _deserialize(saved), SettingSource.SAVED, False
        else:
            raw, source, locked = default, SettingSource.DEFAULT, not definition.editable

        if definition.secret:
            environment_configured = environment_value is not None and environment_value.strip() != ""
            configured = environment_configured or bool(secret_reference and secret_reference.configured)
            if environment_configured:
                source = SettingSource.ENVIRONMENT
                locked = runtime_mode == "headless"
            elif secret_reference and secret_reference.configured:
                source = SettingSource.SAVED
                locked = False
            values[definition.key] = EffectiveSetting(
                key=definition.key,
                value=None,
                source=source,
                locked=locked,
                configured=configured,
            )
            continue

        try:
            parsed = _coerce(definition.value_type, raw)
        except (TypeError, ValueError):
            parsed = default
            source = SettingSource.DEFAULT
            locked = not definition.editable
        values[definition.key] = EffectiveSetting(
            key=definition.key,
            value=parsed,
            source=source,
            locked=locked,
        )
    _normalize_smart_search(values, platform)
    return EffectiveSettingsSnapshot(revision=persisted.revision, values=values)


def _normalize_smart_search(values: dict[str, EffectiveSetting], platform: str) -> None:
    """Values older builds may still hold (a `.env`, a row the `0009` migration has not rewritten yet).

    `jina` (or any unknown provider) follows the migration rule: `custom` when its model file exists,
    otherwise `disabled`. An unknown managed model falls back to the recommended one.
    """
    provider = values["embeddings_provider"]
    if provider.value not in EMBEDDINGS_PROVIDER_CHOICES:
        model = values["custom_model_path"]
        configured_path = str(model.value or "").strip()
        candidate_path = configured_path or LEGACY_CUSTOM_MODEL_PATH
        data_dir = str(values["data_dir"].value or "")
        exists = resolve_model_path(candidate_path, data_dir).is_file()
        values["embeddings_provider"] = replace(
            provider, value=migrate_embeddings_provider(str(provider.value or ""), exists)
        )
        if exists and not configured_path:
            values["custom_model_path"] = replace(model, value=candidate_path)
    if values["embeddings_provider"].value not in embeddings_provider_choices(platform):
        values["embeddings_provider"] = replace(values["embeddings_provider"], value="disabled")
    model_choice = values["smart_search_model"]
    if model_choice.value not in SETTINGS_BY_KEY["smart_search_model"].choices:
        values["smart_search_model"] = replace(
            model_choice, value=platform_default("smart_search_model", platform)
        )


def resolve_model_path(path: str, data_dir: str) -> Path:
    """A model or binary path as the runtime reads it: relative paths are relative to `data_dir`'s parent."""
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return (Path(data_dir).parent / candidate).resolve()


class GetSettingsUseCase:
    def __init__(self, *, settings: SettingsRepositoryPort) -> None:
        self._settings = settings

    async def execute(self) -> PublicSettings:
        return await self._settings.get_public_settings()


class EditableSettingsService:
    def __init__(
        self,
        *,
        repository: SettingsRepositoryPort,
        environ: Mapping[str, str] | None = None,
        runtime_mode: str = "headless",
        policy_values: Mapping[str, Any] | None = None,
        bootstrap_values: Mapping[str, Any] | None = None,
        model_catalog: ModelCatalogPort | None = None,
    ) -> None:
        self._repository = repository
        self._model_catalog = model_catalog
        self._environ = dict(environ if environ is not None else os.environ)
        self._runtime_mode = runtime_mode
        self._policy_values = dict(policy_values or {})
        self._bootstrap_values = dict(bootstrap_values or {})

    async def snapshot(self) -> EffectiveSettingsSnapshot:
        persisted = await self._repository.load()
        if self._bootstrap_values:
            persisted = PersistedSettings(
                revision=persisted.revision,
                values={
                    **{key: _serialize(value) for key, value in self._bootstrap_values.items()},
                    **persisted.values,
                },
                secret_references=persisted.secret_references,
            )
        return resolve_effective_settings(
            persisted=persisted,
            environ=self._environ,
            runtime_mode=self._runtime_mode,
            policy_values=self._policy_values,
        )

    async def validate(
        self,
        values: Mapping[str, Any],
        secret_references: Mapping[str, SecretReferenceMutation] | None = None,
        *,
        run_probes: bool = False,
    ) -> SettingsValidationResult:
        snapshot = await self.snapshot()
        references = secret_references or {}
        errors: list[FieldIssue] = []
        warnings: list[FieldIssue] = []
        normalized: dict[str, Any] = {}
        for key, raw in values.items():
            definition = SETTINGS_BY_KEY.get(key)
            if definition is None:
                errors.append(FieldIssue(key, "unknown_setting", "Unknown setting"))
                continue
            if definition.secret:
                errors.append(FieldIssue(key, "secret_plaintext_forbidden", "Secret values are not accepted by this API"))
                continue
            if snapshot.values[key].locked or not definition.editable:
                errors.append(FieldIssue(key, "settings_source_locked", "Setting is controlled by its source"))
                continue
            try:
                value = _coerce(definition.value_type, raw)
                _validate_constraints(definition, value)
                normalized[key] = value
            except (TypeError, ValueError) as exc:
                errors.append(FieldIssue(key, "invalid_value", str(exc)))

        for key, mutation in references.items():
            definition = SETTINGS_BY_KEY.get(key)
            if definition is None or not definition.secret:
                errors.append(FieldIssue(key, "invalid_secret_reference", "Setting is not a secret field"))
                continue
            if snapshot.values[key].locked or not definition.editable:
                errors.append(FieldIssue(key, "settings_source_locked", "Secret is controlled by its source"))
                continue
            if mutation.configured and not _valid_secret_reference(mutation.reference):
                errors.append(FieldIssue(key, "invalid_secret_reference", "Configured secrets require an opaque reference"))
            if not mutation.configured and mutation.reference is not None:
                errors.append(FieldIssue(key, "invalid_secret_reference", "Missing secrets cannot retain a reference"))

        candidate = {key: item.value for key, item in snapshot.values.items() if item.configured is None}
        candidate.update(normalized)
        configured = {
            key: bool(item.configured)
            for key, item in snapshot.values.items()
            if item.configured is not None
        }
        configured.update({key: mutation.configured for key, mutation in references.items()})
        errors.extend(_cross_validate(candidate, configured, model_catalog=self._model_catalog))
        warnings.extend(_cross_warnings(candidate, configured))
        probes = _run_probes(normalized, candidate) if run_probes and not errors else ()
        errors.extend(
            FieldIssue(probe.key, "settings_probe_failed", probe.message or "Probe failed")
            for probe in probes
            if probe.status == "failed"
        )
        restart_plan = _restart_plan(snapshot, normalized, references)
        return SettingsValidationResult(
            valid=not errors,
            errors=tuple(errors),
            warnings=tuple(warnings),
            probes=tuple(probes),
            restart_plan=restart_plan,
        )

    async def apply(
        self,
        *,
        expected_revision: int,
        values: Mapping[str, Any],
        secret_references: Mapping[str, SecretReferenceMutation] | None = None,
    ) -> tuple[EffectiveSettingsSnapshot, RestartPlan]:
        references = dict(secret_references or {})
        result = await self.validate(values, references)
        if not result.valid:
            locked = [issue.key for issue in result.errors if issue.code == "settings_source_locked"]
            if locked:
                raise SettingsSourceLockedError(locked)
            raise ValidationFailedError(
                "Settings validation failed",
                {"fields": [{"key": issue.key, "code": issue.code, "message": issue.message} for issue in result.errors]},
            )
        serialized = {key: _serialize(_coerce(SETTINGS_BY_KEY[key].value_type, value)) for key, value in values.items()}
        await self._repository.compare_and_set(
            expected_revision=expected_revision,
            values=serialized,
            secret_references=references,
        )
        return await self.snapshot(), result.restart_plan

    async def import_preview(self, content: str) -> dict[str, Any]:
        snapshot = await self.snapshot()
        items: list[dict[str, Any]] = []
        unknown: list[str] = []
        for alias, raw in _parse_dotenv(content):
            definition = SETTINGS_BY_ALIAS.get(alias)
            if definition is None:
                unknown.append(alias)
                continue
            effective = snapshot.values[definition.key]
            item: dict[str, Any] = {
                "env_key": alias,
                "key": definition.key,
                "secret": definition.secret,
                "locked": effective.locked,
                "status": "locked" if effective.locked else "ready",
            }
            if definition.secret:
                item["configured"] = bool(raw.strip())
            else:
                try:
                    item["value"] = _coerce(definition.value_type, raw)
                except (TypeError, ValueError):
                    item["status"] = "invalid"
            items.append(item)
        return {"revision": snapshot.revision, "items": items, "unknown_keys": sorted(set(unknown))}

    async def export(self) -> dict[str, Any]:
        snapshot = await self.snapshot()
        return {
            "format": "bento-settings",
            "version": 1,
            "revision": snapshot.revision,
            "values": {
                key: item.value
                for key, item in snapshot.values.items()
                if not SETTINGS_BY_KEY[key].secret and SETTINGS_BY_KEY[key].editable
            },
        }


def _environment_value(aliases: tuple[str, ...], environ: Mapping[str, str]) -> str | None:
    for alias in aliases:
        if alias in environ:
            return environ[alias]
    return None


def _coerce(value_type: SettingValueType, raw: Any) -> Any:
    if raw is None:
        return None
    if value_type == SettingValueType.INTEGER:
        if isinstance(raw, bool):
            raise ValueError("Expected an integer")
        return int(raw)
    if value_type == SettingValueType.NUMBER:
        if isinstance(raw, bool):
            raise ValueError("Expected a number")
        return float(raw)
    if value_type == SettingValueType.BOOLEAN:
        if isinstance(raw, bool):
            return raw
        normalized = str(raw).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError("Expected a boolean")
    return str(raw).strip() if raw is not None else None


def _validate_constraints(definition: Any, value: Any) -> None:
    if definition.choices and value not in definition.choices:
        raise ValueError(f"Expected one of: {', '.join(definition.choices)}")
    if definition.minimum is not None and value < definition.minimum:
        raise ValueError(f"Must be at least {definition.minimum:g}")
    if definition.maximum is not None and value > definition.maximum:
        raise ValueError(f"Must be at most {definition.maximum:g}")


def _cross_warnings(values: Mapping[str, Any], configured: Mapping[str, bool]) -> list[FieldIssue]:
    """Telegram mode without build credentials stays valid: the library keeps working locally."""
    warnings: list[FieldIssue] = []
    if values.get("storage_backend") == "telegram" and not all(
        configured.get(key) for key in ("telegram_api_id", "telegram_api_hash")
    ):
        warnings.append(FieldIssue("storage_backend", "telegram_not_available", "This build has no Telegram application credentials"))
    server_url = str(values.get("embedding_server_url") or "").strip()
    if server_url and urlparse(server_url).scheme in {"http", "https"} and not _is_loopback_url(server_url):
        # File text is sent to this server to be embedded; outside this device it leaves unencrypted.
        warnings.append(FieldIssue("embedding_server_url", "embedding_server_not_local", "The embedding server is not on this device"))
    return warnings


def _is_loopback_url(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return False
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _cross_validate(
    values: Mapping[str, Any],
    configured: Mapping[str, bool],
    *,
    model_catalog: ModelCatalogPort | None = None,
) -> list[FieldIssue]:
    issues: list[FieldIssue] = []
    if values.get("storage_backend") == "fake" and values.get("environment") == "production":
        issues.append(FieldIssue("storage_backend", "storage_backend_unavailable", "The simulated Telegram is not available"))
    data_dir = Path(str(values.get("data_dir") or ""))
    if str(data_dir) and data_dir == Path(data_dir.anchor):
        issues.append(FieldIssue("data_dir", "filesystem_root_forbidden", "The data directory cannot be a filesystem root"))
    server_url = str(values.get("embedding_server_url") or "").strip()
    if server_url and urlparse(server_url).scheme not in {"http", "https"}:
        issues.append(FieldIssue("embedding_server_url", "invalid_url", "Expected an HTTP or HTTPS URL"))
    issues.extend(_smart_search_issues(values, server_url, model_catalog))
    return issues


def _smart_search_issues(
    values: Mapping[str, Any],
    server_url: str,
    model_catalog: ModelCatalogPort | None,
) -> list[FieldIssue]:
    provider = values.get("embeddings_provider")
    platform = str(values.get("platform") or "auto")
    if provider is not None and provider not in embeddings_provider_choices(platform):
        return [FieldIssue("embeddings_provider", "smart_search_unavailable", "Search by meaning is not available on this device")]
    if provider == "custom" and not server_url and not str(values.get("custom_model_path") or "").strip():
        # An external server (`embedding_server_url`) brings its own model.
        return [FieldIssue("custom_model_path", "model_path_required", "A model path is required")]
    if provider != "managed":
        return []
    model_id = str(values.get("smart_search_model") or "")
    dims = values.get("embedding_dimensions")
    spec = model_catalog.get(model_id) if model_catalog is not None else None
    if spec is not None:
        try:
            spec.validate_dims(int(dims) if dims is not None else spec.default_dims)
        except InvalidModelSpecError as exc:
            return [FieldIssue("embedding_dimensions", exc.code, _dims_message(exc.details.get("allowed", ())))]
        return []
    allowed = MANAGED_MODEL_DIMS.get(model_id)
    if allowed is None or model_catalog is not None:
        return [FieldIssue("smart_search_model", "invalid_model_spec", "Unknown smart search model")]
    if dims is not None and dims not in allowed:
        return [FieldIssue("embedding_dimensions", "invalid_model_spec", _dims_message(allowed))]
    return []


def _dims_message(allowed: Any) -> str:
    return f"Expected one of: {', '.join(str(value) for value in allowed)}"


def _run_probes(changed: Mapping[str, Any], candidate: Mapping[str, Any]) -> tuple[ProbeResult, ...]:
    results: list[ProbeResult] = []
    if "data_dir" in changed:
        path = Path(str(candidate["data_dir"])).expanduser()
        parent = path if path.exists() else path.parent
        status = "passed" if parent.exists() and os.access(parent, os.W_OK) else "failed"
        results.append(ProbeResult("data_dir", status, None if status == "passed" else "Directory is not writable"))
    data_dir = str(candidate.get("data_dir") or "")
    if candidate.get("embeddings_provider") == "custom":
        for key in ("custom_model_path", "custom_mmproj_path"):
            configured_path = str(candidate.get(key) or "").strip()
            if key not in changed or not configured_path:
                continue
            status = "passed" if resolve_model_path(configured_path, data_dir).is_file() else "failed"
            results.append(ProbeResult(key, status, None if status == "passed" else "Model file was not found"))
    server_path = str(candidate.get("llama_server_path") or "").strip()
    if "llama_server_path" in changed and server_path:
        path = resolve_model_path(server_path, data_dir)
        status = "passed" if path.is_file() and os.access(path, os.X_OK) else "failed"
        results.append(
            ProbeResult("llama_server_path", status, None if status == "passed" else "The llama-server program was not found")
        )
    return tuple(results)


def _restart_plan(
    snapshot: EffectiveSettingsSnapshot,
    values: Mapping[str, Any],
    references: Mapping[str, SecretReferenceMutation],
) -> RestartPlan:
    changed = [
        key
        for key, value in values.items()
        if key in snapshot.values and snapshot.values[key].value != _coerce(SETTINGS_BY_KEY[key].value_type, value)
    ]
    # Supplying a secret mutation also covers rotation, where presence remains true.
    changed.extend(key for key in references if key in snapshot.values)
    changed = sorted(set(changed))
    mode = max((SETTINGS_BY_KEY[key].apply_mode for key in changed), key=_APPLY_RANK.get, default=SettingApplyMode.LIVE)
    services = {
        SettingApplyMode.LIVE: (),
        SettingApplyMode.RESTART_WORKER: ("worker",),
        SettingApplyMode.RESTART_SERVICES: ("api", "worker"),
        SettingApplyMode.RESTART_APP: ("desktop", "api", "worker"),
    }[mode]
    return RestartPlan(mode=mode, affected_keys=tuple(changed), services=services)


def _valid_secret_reference(reference: str | None) -> bool:
    if reference is None or not 8 <= len(reference) <= 256:
        return False
    if not reference.startswith(("secure:", "desktop-secret:")):
        return False
    return all(character.isalnum() or character in "-_:/." for character in reference)


def _parse_dotenv(content: str) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, raw = stripped.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
            raw = raw[1:-1]
        if key:
            result.append((key, raw))
    return tuple(result)


def _serialize(value: Any) -> str:
    import json

    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _deserialize(value: str) -> Any:
    import json

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
