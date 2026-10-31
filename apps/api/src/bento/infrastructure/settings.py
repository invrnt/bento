from __future__ import annotations

import json
import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import AliasChoices, Field, PrivateAttr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import dotenv_values

from bento.domain.settings import EffectiveSettingsSnapshot, PersistedSettings, SecretReferenceMutation
from bento.domain.settings_registry import SETTINGS_BY_KEY, SETTINGS_REGISTRY


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
    ocr_provider: Literal["disabled", "mock", "rapidocr"] = Field(
        default="disabled", validation_alias=AliasChoices("OCR_PROVIDER", "BENTO_OCR_PROVIDER", "ocr_provider")
    )
    embeddings_provider: Literal["disabled", "mock", "jina"] = Field(
        default="disabled",
        validation_alias=AliasChoices("EMBEDDINGS_PROVIDER", "BENTO_EMBEDDING_PROVIDER", "embeddings_provider"),
    )
    jina_model_path: str = Field(
        default="./data/models/jina-v5-omni-nano.gguf",
        validation_alias=AliasChoices("JINA_MODEL_PATH", "BENTO_EMBEDDING_MODEL_PATH", "jina_model_path"),
    )
    embedding_server_url: str = Field(
        default="http://127.0.0.1:8080/v1/embeddings",
        validation_alias=AliasChoices("BENTO_EMBEDDING_SERVER_URL", "embedding_server_url"),
    )
    embedding_dimensions: int = Field(
        default=768,
        ge=1,
        le=65536,
        validation_alias=AliasChoices("BENTO_EMBEDDING_DIMENSIONS", "embedding_dimensions"),
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
    fake_telegram_dir: str = Field(
        default="", validation_alias=AliasChoices("BENTO_FAKE_TELEGRAM_DIR", "fake_telegram_dir")
    )
    _settings_snapshot: EffectiveSettingsSnapshot | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _fake_backend_is_development_only(self) -> Settings:
        if self.storage_backend == "fake" and self.environment == "production":
            raise ValueError("The fake Telegram backend cannot be used in production")
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


@lru_cache
def get_settings() -> Settings:
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
