from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from bento.domain.indexing import IndexProviderState
from bento.domain.storage import StorageBackend


class WorkerStatus(StrEnum):
    STOPPED = "stopped"
    RUNNING = "running"
    DEGRADED = "degraded"


class SettingValueType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    CHOICE = "choice"
    PATH = "path"
    SECRET = "secret"


class SettingAvailability(StrEnum):
    BOTH = "both"
    DESKTOP = "desktop"
    HEADLESS = "headless"


class SettingApplyMode(StrEnum):
    LIVE = "live"
    RESTART_WORKER = "restart_worker"
    RESTART_SERVICES = "restart_services"
    RESTART_APP = "restart_app"


class SettingSource(StrEnum):
    DEFAULT = "default"
    SAVED = "saved"
    ENVIRONMENT = "environment"
    POLICY = "policy"


@dataclass(frozen=True, slots=True)
class SettingDefinition:
    key: str
    env_aliases: tuple[str, ...]
    group: str
    label_key: str
    help_key: str
    value_type: SettingValueType
    default: Any
    apply_mode: SettingApplyMode = SettingApplyMode.LIVE
    availability: SettingAvailability = SettingAvailability.BOTH
    secret: bool = False
    editable: bool = True
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    probe: str | None = None
    advanced: bool = False
    """Shown only under the "Advanced" disclosure of its group."""


@dataclass(frozen=True, slots=True)
class SecretReferenceMutation:
    reference: str | None
    configured: bool


@dataclass(frozen=True, slots=True)
class PersistedSettings:
    revision: int = 0
    values: dict[str, str] = field(default_factory=dict)
    secret_references: dict[str, SecretReferenceMutation] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EffectiveSetting:
    key: str
    value: Any | None
    source: SettingSource
    locked: bool
    configured: bool | None = None


@dataclass(frozen=True, slots=True)
class EffectiveSettingsSnapshot:
    revision: int
    values: dict[str, EffectiveSetting]

    def plain_values(self) -> dict[str, Any]:
        return {key: item.value for key, item in self.values.items() if item.configured is None}


@dataclass(frozen=True, slots=True)
class FieldIssue:
    key: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ProbeResult:
    key: str
    status: str
    message: str | None = None


@dataclass(frozen=True, slots=True)
class RestartPlan:
    mode: SettingApplyMode
    affected_keys: tuple[str, ...]
    services: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SettingsValidationResult:
    valid: bool
    errors: tuple[FieldIssue, ...]
    warnings: tuple[FieldIssue, ...]
    probes: tuple[ProbeResult, ...]
    restart_plan: RestartPlan


@dataclass(frozen=True, slots=True)
class PublicSettings:
    storage_backend: StorageBackend
    telegram_configured: bool
    ocr_state: IndexProviderState
    embeddings_state: IndexProviderState
    model_available: bool
    worker_status: WorkerStatus
    worker_concurrency: int
    data_paths: dict[str, str]
