from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from bento.application.settings import EditableSettingsService
from bento.domain.settings import PersistedSettings, SettingApplyMode, SettingValueType
from bento.domain.settings_registry import SETTINGS_BY_ALIAS, SETTINGS_BY_KEY
from bento.infrastructure.settings import Settings, fake_telegram_directory, load_effective_settings

NEW_SETTINGS = {
    "telegram_parallel_transfers": ("performance", SettingValueType.INTEGER, 1, 1, 4),
    "telegram_part_size_mb": ("advanced", SettingValueType.INTEGER, 512, 64, 1950),
    "relay_url": ("advanced", SettingValueType.STRING, "", None, None),
    "public_site_url": ("advanced", SettingValueType.STRING, "", None, None),
    "inbox_keep_hours": ("telegram", SettingValueType.INTEGER, 24, 0, 720),
    "trash_retention_days": ("storage", SettingValueType.INTEGER, 30, 1, 365),
    "cache_max_gb": ("storage", SettingValueType.NUMBER, 10, 1, 2048),
    "backup_pause_on_battery": ("backup", SettingValueType.BOOLEAN, True, None, None),
    "backup_bandwidth_limit_kbps": ("backup", SettingValueType.INTEGER, 0, 0, 1_000_000),
    "fake_telegram_dir": ("advanced", SettingValueType.PATH, "", None, None),
}


class MemorySettingsRepository:
    async def load(self) -> PersistedSettings:
        return PersistedSettings()


def resolve(environ: dict[str, str], **base: object) -> Settings:
    return load_effective_settings(Settings(**base), environ=environ, persisted=PersistedSettings())


@pytest.mark.parametrize("key", sorted(NEW_SETTINGS))
def test_new_registry_entries_match_settings_model(key: str) -> None:
    group, value_type, default, minimum, maximum = NEW_SETTINGS[key]
    definition = SETTINGS_BY_KEY[key]

    assert (definition.group, definition.value_type, definition.default) == (group, value_type, default)
    assert (definition.minimum, definition.maximum) == (minimum, maximum)
    assert definition.label_key == f"settings.{key}.label"
    assert definition.help_key == f"settings.{key}.help"
    assert not definition.secret and definition.editable
    assert Settings().model_dump()[key] == default


def test_documented_environment_aliases() -> None:
    for alias, key in {
        "BENTO_RELAY_URL": "relay_url",
        "BENTO_PUBLIC_SITE_URL": "public_site_url",
        "BENTO_FAKE_TELEGRAM_DIR": "fake_telegram_dir",
        "STORAGE_BACKEND": "storage_backend",
    }.items():
        assert SETTINGS_BY_ALIAS[alias].key == key

    settings = resolve(
        {
            "BENTO_RELAY_URL": "wss://relay.example",
            "BENTO_TELEGRAM_PART_SIZE_MB": "1024",
            "BENTO_CACHE_MAX_GB": "2.5",
            "BENTO_BACKUP_PAUSE_ON_BATTERY": "false",
            "BENTO_FAKE_TELEGRAM_DIR": "/tmp/fake-cloud",
        }
    )

    assert settings.relay_url == "wss://relay.example"
    assert settings.telegram_part_size_mb == 1024
    assert settings.cache_max_gb == 2.5
    assert settings.backup_pause_on_battery is False
    assert fake_telegram_directory(settings) == Path("/tmp/fake-cloud")


def test_storage_backend_accepts_fake_outside_production_only() -> None:
    assert SETTINGS_BY_KEY["storage_backend"].choices == ("local", "telegram", "fake")
    assert resolve({"STORAGE_BACKEND": "fake"}).storage_backend == "fake"
    with pytest.raises(ValidationError, match="fake Telegram backend"):
        resolve({"STORAGE_BACKEND": "fake", "ENVIRONMENT": "production"})
    assert resolve({"STORAGE_BACKEND": "telegram", "ENVIRONMENT": "production"}).storage_backend == "telegram"


def test_fake_directory_defaults_inside_data_dir() -> None:
    assert fake_telegram_directory(Settings(data_dir="/data/bento")) == Path("/data/bento/fake-telegram")


@pytest.mark.parametrize(
    ("values", "valid"),
    [
        ({"telegram_parallel_transfers": 4, "telegram_part_size_mb": 64, "inbox_keep_hours": 0}, True),
        ({"telegram_parallel_transfers": 5}, False),
        ({"telegram_part_size_mb": 1951}, False),
        ({"trash_retention_days": 0}, False),
        ({"cache_max_gb": 0.5}, False),
        ({"backup_bandwidth_limit_kbps": -1}, False),
        ({"backup_pause_on_battery": "maybe"}, False),
        ({"storage_backend": "fake", "relay_url": "wss://relay.example"}, True),
    ],
)
def test_editable_settings_validation_enforces_constraints(values: dict[str, object], valid: bool) -> None:
    service = EditableSettingsService(repository=MemorySettingsRepository(), environ={}, runtime_mode="desktop")  # type: ignore[arg-type]

    result = asyncio.run(service.validate(values))

    assert result.valid is valid


def test_backup_policy_settings_apply_live() -> None:
    assert SETTINGS_BY_KEY["backup_pause_on_battery"].apply_mode == SettingApplyMode.LIVE
    assert SETTINGS_BY_KEY["backup_bandwidth_limit_kbps"].apply_mode == SettingApplyMode.LIVE
    assert SETTINGS_BY_KEY["fake_telegram_dir"].apply_mode == SettingApplyMode.RESTART_SERVICES
