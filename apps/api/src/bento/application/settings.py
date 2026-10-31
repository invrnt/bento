from __future__ import annotations

import os
from collections.abc import Mapping
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
from bento.domain.settings_registry import SETTINGS_BY_ALIAS, SETTINGS_BY_KEY, SETTINGS_REGISTRY
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
    values: dict[str, EffectiveSetting] = {}
    for definition in SETTINGS_REGISTRY:
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
            raw, source, locked = definition.default, SettingSource.DEFAULT, not definition.editable

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
            parsed = definition.default
            source = SettingSource.DEFAULT
            locked = not definition.editable
        values[definition.key] = EffectiveSetting(
            key=definition.key,
            value=parsed,
            source=source,
            locked=locked,
        )
    return EffectiveSettingsSnapshot(revision=persisted.revision, values=values)


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
    ) -> None:
        self._repository = repository
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
            if snapshot.values[key].locked:
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
        errors.extend(_cross_validate(candidate, configured))
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


def _cross_validate(values: Mapping[str, Any], configured: Mapping[str, bool]) -> list[FieldIssue]:
    issues: list[FieldIssue] = []
    if values.get("storage_backend") == "telegram":
        required = (
            "telegram_bot_token",
            "telegram_api_id",
            "telegram_api_hash",
            "telegram_webhook_secret",
            "telegram_raw_chat_id",
            "telegram_thumbs_chat_id",
            "telegram_journal_chat_id",
        )
        missing = [key for key in required if not configured.get(key)]
        if missing:
            issues.append(FieldIssue("storage_backend", "telegram_not_configured", "Telegram secrets are incomplete"))
    if values.get("storage_backend") == "fake" and values.get("environment") == "production":
        issues.append(FieldIssue("storage_backend", "storage_backend_unavailable", "The simulated Telegram is not available"))
    if values.get("embeddings_provider") == "jina" and not str(values.get("jina_model_path") or "").strip():
        issues.append(FieldIssue("jina_model_path", "model_path_required", "A model path is required"))
    data_dir = Path(str(values.get("data_dir") or ""))
    if str(data_dir) and data_dir == Path(data_dir.anchor):
        issues.append(FieldIssue("data_dir", "filesystem_root_forbidden", "The data directory cannot be a filesystem root"))
    server_url = str(values.get("embedding_server_url") or "")
    if server_url and urlparse(server_url).scheme not in {"http", "https"}:
        issues.append(FieldIssue("embedding_server_url", "invalid_url", "Expected an HTTP or HTTPS URL"))
    return issues


def _run_probes(changed: Mapping[str, Any], candidate: Mapping[str, Any]) -> tuple[ProbeResult, ...]:
    results: list[ProbeResult] = []
    if "data_dir" in changed:
        path = Path(str(candidate["data_dir"])).expanduser()
        parent = path if path.exists() else path.parent
        status = "passed" if parent.exists() and os.access(parent, os.W_OK) else "failed"
        results.append(ProbeResult("data_dir", status, None if status == "passed" else "Directory is not writable"))
    if "jina_model_path" in changed and candidate.get("embeddings_provider") == "jina":
        path = Path(str(candidate["jina_model_path"])).expanduser()
        if not path.is_absolute():
            path = (Path(str(candidate["data_dir"])).parent / path).resolve()
        status = "passed" if path.is_file() else "failed"
        results.append(ProbeResult("jina_model_path", status, None if status == "passed" else "Model file was not found"))
    if candidate.get("storage_backend") == "telegram" and (
        "storage_backend" in changed or "telegram_bot_api_url" in changed
    ):
        results.append(
            ProbeResult(
                "storage_backend",
                "requires_desktop",
                "Telegram connectivity must be tested by the desktop one-shot probe",
            )
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
