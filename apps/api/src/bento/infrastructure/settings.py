from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import AliasChoices, Field, PrivateAttr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import dotenv_values

from bento.domain.settings import EffectiveSettingsSnapshot, PersistedSettings, SecretReferenceMutation
from bento.domain.settings_registry import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_SMART_SEARCH_MODEL_ID,
    LEGACY_CUSTOM_MODEL_PATH,
    SETTINGS_BY_KEY,
    SETTINGS_REGISTRY,
    embeddings_provider_choices,
)
from bento.domain.smart_search import EMBEDDINGS_PROVIDER_CHOICES, follows_smart_search_status, migrate_embeddings_provider

_PROVIDER_KEYS_LOWER = frozenset({"embeddings_provider", "bento_embedding_provider"})
_CUSTOM_MODEL_PATH_KEYS = (
    "custom_model_path",
    "jina_model_path",
    "BENTO_CUSTOM_MODEL_PATH",
    "JINA_MODEL_PATH",
    "BENTO_EMBEDDING_MODEL_PATH",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Bento"
    app_version: str = "0.1.0"
    environment: str = "local"
    runtime_mode: Literal["headless", "desktop"] = Field(
        default="headless", validation_alias=AliasChoices("BENTO_RUNTIME_MODE", "runtime_mode")
    )
    platform: Literal["auto", "android"] = Field(
        default="auto", validation_alias=AliasChoices("BENTO_PLATFORM", "platform")
    )
    device_name: str = Field(default="", validation_alias=AliasChoices("BENTO_DEVICE_NAME", "device_name"))
    storage_backend: Literal["local", "telegram", "fake"] = "telegram"
    host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    web_port: int = Field(default=5173, ge=1, le=65535)
    worker_concurrency: int = Field(default=1, ge=1, le=8)
    telegram_api_id: str | None = Field(
        default=None, repr=False, validation_alias=AliasChoices("BENTO_TELEGRAM_API_ID", "telegram_api_id")
    )
    telegram_api_hash: str | None = Field(
        default=None, repr=False, validation_alias=AliasChoices("BENTO_TELEGRAM_API_HASH", "telegram_api_hash")
    )
    ocr_provider: Literal["disabled", "mock", "rapidocr", "mlkit"] = Field(
        default="disabled", validation_alias=AliasChoices("OCR_PROVIDER", "BENTO_OCR_PROVIDER", "ocr_provider")
    )
    embeddings_provider: Literal["disabled", "managed", "custom", "mock"] = Field(
        default="disabled",
        validation_alias=AliasChoices("EMBEDDINGS_PROVIDER", "BENTO_EMBEDDING_PROVIDER", "embeddings_provider"),
    )
    smart_search_model: str = Field(
        default=DEFAULT_SMART_SEARCH_MODEL_ID,
        validation_alias=AliasChoices("BENTO_SMART_SEARCH_MODEL", "smart_search_model"),
    )
    custom_model_path: str = Field(
        default="",
        validation_alias=AliasChoices(
            "BENTO_CUSTOM_MODEL_PATH", "JINA_MODEL_PATH", "BENTO_EMBEDDING_MODEL_PATH", "custom_model_path", "jina_model_path"
        ),
    )
    custom_mmproj_path: str = Field(
        default="", validation_alias=AliasChoices("BENTO_CUSTOM_MMPROJ_PATH", "custom_mmproj_path")
    )
    custom_query_prefix: str = Field(
        default="", validation_alias=AliasChoices("BENTO_CUSTOM_QUERY_PREFIX", "custom_query_prefix")
    )
    custom_document_prefix: str = Field(
        default="", validation_alias=AliasChoices("BENTO_CUSTOM_DOCUMENT_PREFIX", "custom_document_prefix")
    )
    custom_pooling: Literal["auto", "mean", "last", "cls"] = Field(
        default="auto", validation_alias=AliasChoices("BENTO_CUSTOM_POOLING", "custom_pooling")
    )
    embedding_dimensions: int = Field(
        default=DEFAULT_EMBEDDING_DIMENSIONS,
        ge=1,
        le=65536,
        validation_alias=AliasChoices("BENTO_EMBEDDING_DIMENSIONS", "embedding_dimensions"),
    )
    llama_server_path: str = Field(
        default="", validation_alias=AliasChoices("BENTO_LLAMA_SERVER_BINARY", "llama_server_path")
    )
    # External server; when set, Bento spawns no llama-server of its own.
    embedding_server_url: str = Field(
        default="",
        validation_alias=AliasChoices("BENTO_EMBEDDING_SERVER_URL", "embedding_server_url"),
    )
    embedding_threads: int = Field(
        default=SETTINGS_BY_KEY["embedding_threads"].default,
        ge=1,
        le=64,
        validation_alias=AliasChoices("BENTO_EMBEDDING_THREADS", "embedding_threads"),
    )
    data_dir: str = "/app/data"
    telegram_parallel_transfers: int = Field(
        default=1,
        ge=1,
        le=4,
        validation_alias=AliasChoices("BENTO_TELEGRAM_PARALLEL_TRANSFERS", "telegram_parallel_transfers"),
    )
    telegram_part_size_mb: int = Field(
        default=512,
        ge=64,
        le=1950,
        validation_alias=AliasChoices("BENTO_TELEGRAM_PART_SIZE_MB", "telegram_part_size_mb"),
    )
    relay_url: str = Field(default="", validation_alias=AliasChoices("BENTO_RELAY_URL", "relay_url"))
    public_site_url: str = Field(default="", validation_alias=AliasChoices("BENTO_PUBLIC_SITE_URL", "public_site_url"))
    inbox_keep_hours: int = Field(
        default=24, ge=0, le=720, validation_alias=AliasChoices("BENTO_INBOX_KEEP_HOURS", "inbox_keep_hours")
    )
    trash_retention_days: int = Field(
        default=30, ge=1, le=365, validation_alias=AliasChoices("BENTO_TRASH_RETENTION_DAYS", "trash_retention_days")
    )
    cache_max_gb: float = Field(
        default=10, ge=1, le=2048, validation_alias=AliasChoices("BENTO_CACHE_MAX_GB", "cache_max_gb")
    )
    backup_pause_on_battery: bool = Field(
        default=True, validation_alias=AliasChoices("BENTO_BACKUP_PAUSE_ON_BATTERY", "backup_pause_on_battery")
    )
    backup_bandwidth_limit_kbps: int = Field(
        default=0,
        ge=0,
        le=1_000_000,
        validation_alias=AliasChoices("BENTO_BACKUP_BANDWIDTH_LIMIT_KBPS", "backup_bandwidth_limit_kbps"),
    )
    backup_wifi_only: bool = Field(
        default=False, validation_alias=AliasChoices("BENTO_BACKUP_WIFI_ONLY", "backup_wifi_only")
    )
    backup_videos_on_metered: bool = Field(
        default=False, validation_alias=AliasChoices("BENTO_BACKUP_VIDEOS_ON_METERED", "backup_videos_on_metered")
    )
    backup_only_charging: bool = Field(
        default=False, validation_alias=AliasChoices("BENTO_BACKUP_ONLY_CHARGING", "backup_only_charging")
    )
    ocr_requires_charging: bool = Field(
        default=False, validation_alias=AliasChoices("BENTO_OCR_REQUIRES_CHARGING", "ocr_requires_charging")
    )
    fake_telegram_dir: str = Field(
        default="", validation_alias=AliasChoices("BENTO_FAKE_TELEGRAM_DIR", "fake_telegram_dir")
    )
    fake_telegram_url: str = Field(
        default="", validation_alias=AliasChoices("BENTO_FAKE_TELEGRAM_URL", "fake_telegram_url")
    )
    _settings_snapshot: EffectiveSettingsSnapshot | None = PrivateAttr(default=None)

    @model_validator(mode="before")
    @classmethod
    def _legacy_embeddings_provider(cls, data: Any) -> Any:
        """A leftover `jina` (an old `.env` or environment) follows the `0009` rule: `custom` when its model
        file exists, otherwise `disabled`. The settings resolver applies the same rule to saved rows."""
        if not isinstance(data, dict):
            return data
        # Environment sources may hand over the alias in any case.
        by_name = {str(name).lower(): name for name in data}
        provider_keys = [name for name in data if str(name).lower() in _PROVIDER_KEYS_LOWER]
        legacy = [name for name in provider_keys if data[name] not in EMBEDDINGS_PROVIDER_CHOICES]
        if not legacy:
            return data
        configured = ""
        for name in _CUSTOM_MODEL_PATH_KEYS:
            original = by_name.get(name.lower())
            if original is not None and str(data[original] or "").strip():
                configured = str(data[original]).strip()
                break
        candidate = Path(configured or LEGACY_CUSTOM_MODEL_PATH).expanduser()
        if not candidate.is_absolute():
            data_dir = data.get(by_name["data_dir"]) if "data_dir" in by_name else None
            candidate = (Path(str(data_dir or "/app/data")).parent / candidate).resolve()
        exists = candidate.is_file()
        normalized = dict(data)
        for name in legacy:
            normalized[name] = migrate_embeddings_provider(str(data[name] or ""), exists)
        if exists and not configured:
            normalized["custom_model_path"] = LEGACY_CUSTOM_MODEL_PATH
        return normalized

    @field_validator("smart_search_model")
    @classmethod
    def _known_smart_search_model(cls, value: str) -> str:
        choices = SETTINGS_BY_KEY["smart_search_model"].choices
        return value if value in choices else DEFAULT_SMART_SEARCH_MODEL_ID

    @model_validator(mode="after")
    def _fake_backend_is_development_only(self) -> Settings:
        if self.storage_backend == "fake" and self.environment == "production":
            raise ValueError("The fake Telegram backend cannot be used in production")
        if self.fake_telegram_url.strip() and self.environment == "production":
            raise ValueError("The remote fake Telegram cloud cannot be used in production")
        return self

    @property
    def telegram_credentials_present(self) -> bool:
        """Bento's own Telegram application credentials (build configuration) are available."""
        return all(value is not None and str(value).strip() for value in (self.telegram_api_id, self.telegram_api_hash))

    @property
    def telegram_configured(self) -> bool:
        """The configured backend can reach a Telegram account: the simulator, or MTProto with build credentials."""
        if self.storage_backend == "fake":
            return True
        return self.storage_backend == "telegram" and self.telegram_credentials_present

    @property
    def effective_snapshot(self) -> EffectiveSettingsSnapshot | None:
        return self._settings_snapshot

    @property
    def jina_model_path(self) -> str:
        """Deprecated read-only alias of `custom_model_path` for code written before Stage 24."""
        return self.custom_model_path


def fake_telegram_directory(settings: Settings) -> Path:
    """`fake_telegram_dir`, or `<data_dir>/fake-telegram` when empty."""
    configured = settings.fake_telegram_dir.strip()
    return Path(configured).expanduser() if configured else Path(settings.data_dir) / "fake-telegram"


def settings_database_path(settings: Settings) -> Path:
    return Path(settings.data_dir) / "db" / "bento.sqlite3"


def load_persisted_settings(database_path: Path) -> PersistedSettings:
    if not database_path.is_file():
        return PersistedSettings()
    try:
        connection = sqlite3.connect(database_path)
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if "settings" not in tables:
            return PersistedSettings()
        values = dict(connection.execute("SELECT key, value FROM settings"))
        revision = 0
        if "settings_meta" in tables:
            row = connection.execute("SELECT revision FROM settings_meta WHERE id = 1").fetchone()
            revision = int(row[0]) if row is not None else 0
        references: dict[str, SecretReferenceMutation] = {}
        if "setting_secret_references" in tables:
            for key, reference, configured in connection.execute(
                "SELECT key, reference, configured FROM setting_secret_references"
            ):
                references[key] = SecretReferenceMutation(reference=reference, configured=bool(configured))
        return PersistedSettings(revision=revision, values=values, secret_references=references)
    except sqlite3.Error:
        return PersistedSettings()
    finally:
        if "connection" in locals():
            connection.close()


def setting_locked(settings: Settings, key: str) -> bool:
    """The environment or a policy pins `key` (from the snapshot taken at startup; locks never change at run time)."""
    snapshot = settings.effective_snapshot
    item = snapshot.values.get(key) if snapshot is not None else None
    return item is not None and item.locked


def load_persisted_setting(database_path: Path, key: str) -> str | None:
    """The raw saved value of one setting, or None (no database, no table or no row). One indexed read."""
    if not database_path.is_file():
        return None
    try:
        connection = sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    return str(row[0]) if row is not None else None


def live_embeddings_provider(settings: Settings) -> Callable[[], str]:
    """`embeddings_provider` as in effect now, for processes that outlive a change to it: the smart search
    activation writes `managed` and removal writes `disabled` without restarting the API or the worker.

    Only where the worker follows the smart search status too (`follows_smart_search_status`); elsewhere, and
    for a locked value, it is the startup value. Otherwise the saved row wins, and an unknown or missing row falls
    back to the startup value. Cheap enough to call per request (one indexed SQLite read)."""
    startup = str(settings.embeddings_provider)
    locked = setting_locked(settings, "embeddings_provider")
    if locked or not follows_smart_search_status(
        startup, locked=locked, offered=embeddings_provider_choices(str(settings.platform))
    ):
        return lambda: startup
    database_path = settings_database_path(settings)

    def read() -> str:
        raw = load_persisted_setting(database_path, "embeddings_provider")
        if raw is None:
            return startup
        value = deserialize_setting_value("embeddings_provider", raw)
        return value if isinstance(value, str) and value in EMBEDDINGS_PROVIDER_CHOICES else startup

    return read


def load_effective_settings(
    base: Settings | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    persisted: PersistedSettings | None = None,
) -> Settings:
    from bento.application.settings import resolve_effective_settings

    initial = base or Settings()
    saved = persisted if persisted is not None else load_persisted_settings(settings_database_path(initial))
    if initial.runtime_mode == "desktop":
        saved = PersistedSettings(
            revision=saved.revision,
            values={**saved.values, "data_dir": serialize_setting_value("data_dir", initial.data_dir)},
            secret_references=saved.secret_references,
        )
    policy_values: dict[str, Any] = {"runtime_mode": initial.runtime_mode}
    if initial.runtime_mode == "desktop":
        policy_values.update(
            {
                "host": initial.host,
                "api_port": initial.api_port,
                "web_port": initial.web_port,
            }
        )
    snapshot = resolve_effective_settings(
        persisted=saved,
        environ=environ if environ is not None else os.environ,
        runtime_mode=initial.runtime_mode,
        policy_values=policy_values,
    )
    values = snapshot.plain_values()
    # Secret material can only enter the process through inherited environment.
    for definition in SETTINGS_REGISTRY:
        if not definition.secret:
            continue
        for alias in definition.env_aliases:
            raw = (environ if environ is not None else os.environ).get(alias)
            if raw:
                values[definition.key] = raw
                break
    resolved = Settings(**values)
    resolved._settings_snapshot = snapshot
    return resolved


def serialize_setting_value(key: str, value: Any) -> str:
    if key not in SETTINGS_BY_KEY:
        raise KeyError(key)
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def deserialize_setting_value(key: str, value: str) -> Any:
    if key not in SETTINGS_BY_KEY:
        raise KeyError(key)
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


_installed: Settings | None = None


def install_settings(settings: Settings | None) -> None:
    """Make `get_settings()` return `settings` for the whole process (embedded hosts such as the Android engine
    build `Settings` explicitly: no environment, no `.env`). `None` restores environment-based loading."""
    global _installed
    _installed = settings
    get_settings.cache_clear()


@lru_cache
def get_settings() -> Settings:
    if _installed is not None:
        return _installed
    dotenv = {key: value for key, value in dotenv_values(".env").items() if value is not None}
    runtime_mode = os.environ.get("BENTO_RUNTIME_MODE", dotenv.get("BENTO_RUNTIME_MODE", "headless"))
    # Desktop imports legacy files deliberately through the preview/apply contract.
    environment = dict(os.environ) if runtime_mode == "desktop" else {**dotenv, **os.environ}
    bootstrap: dict[str, Any] = {}
    if "DATA_DIR" in environment:
        bootstrap["data_dir"] = environment["DATA_DIR"]
    bootstrap["runtime_mode"] = runtime_mode
    if "HOST" in environment:
        bootstrap["host"] = environment["HOST"]
    if "API_PORT" in environment:
        bootstrap["api_port"] = environment["API_PORT"]
    if "WEB_PORT" in environment:
        bootstrap["web_port"] = environment["WEB_PORT"]
    return load_effective_settings(Settings(_env_file=None, **bootstrap), environ=environment)
