from __future__ import annotations

import asyncio
import json

from bento.application.settings import EditableSettingsService, resolve_effective_settings
from bento.domain.settings import PersistedSettings, SecretReferenceMutation, SettingSource
from bento.domain.settings_registry import SETTINGS_REGISTRY
from bento.infrastructure.settings import Settings, get_settings, load_effective_settings


class MemorySettingsRepository:
    def __init__(self, persisted: PersistedSettings | None = None) -> None:
        self.persisted = persisted or PersistedSettings()

    async def load(self) -> PersistedSettings:
        return self.persisted

    async def compare_and_set(self, *, expected_revision, values, secret_references):
        assert expected_revision == self.persisted.revision
        merged = dict(self.persisted.values)
        merged.update(values)
        references = dict(self.persisted.secret_references)
        references.update(secret_references)
        self.persisted = PersistedSettings(expected_revision + 1, merged, references)
        return self.persisted


def test_registry_covers_settings_model_and_aliases_are_unique() -> None:
    assert {definition.key for definition in SETTINGS_REGISTRY} == set(Settings.model_fields)
    aliases = [alias for definition in SETTINGS_REGISTRY for alias in definition.env_aliases]
    assert len(aliases) == len(set(aliases))
    assert all(definition.env_aliases for definition in SETTINGS_REGISTRY)


def test_headless_environment_precedes_saved_values_and_is_locked() -> None:
    persisted = PersistedSettings(values={"worker_concurrency": json.dumps(2)})
    headless = resolve_effective_settings(
        persisted=persisted,
        environ={"WORKER_CONCURRENCY": "3"},
        runtime_mode="headless",
    )
    desktop = resolve_effective_settings(
        persisted=persisted,
        environ={"WORKER_CONCURRENCY": "3"},
        runtime_mode="desktop",
    )

    assert headless.values["worker_concurrency"].value == 3
    assert headless.values["worker_concurrency"].source == SettingSource.ENVIRONMENT
    assert headless.values["worker_concurrency"].locked is True
    assert desktop.values["worker_concurrency"].value == 2
    assert desktop.values["worker_concurrency"].source == SettingSource.SAVED


def test_validation_restart_plan_import_redaction_and_safe_export() -> None:
    async def scenario() -> None:
        repository = MemorySettingsRepository()
        service = EditableSettingsService(repository=repository, environ={}, runtime_mode="desktop")

        result = await service.validate({"worker_concurrency": 2, "ocr_provider": "rapidocr"})
        assert result.valid is True
        assert result.restart_plan.mode.value == "restart_worker"
        assert result.restart_plan.services == ("worker",)

        invalid = await service.validate({"worker_concurrency": 0})
        assert invalid.valid is False
        assert invalid.errors[0].key == "worker_concurrency"

        preview = await service.import_preview(
            "WORKER_CONCURRENCY=2\nBENTO_TELEGRAM_API_HASH=top-secret-value\nUNKNOWN_THING=yes"
        )
        secret = next(item for item in preview["items"] if item["key"] == "telegram_api_hash")
        assert secret == {
            "env_key": "BENTO_TELEGRAM_API_HASH",
            "key": "telegram_api_hash",
            "secret": True,
            # Build credentials are never user input, so importing them is refused.
            "locked": True,
            "status": "locked",
            "configured": True,
        }
        assert "top-secret-value" not in repr(preview)
        assert preview["unknown_keys"] == ["UNKNOWN_THING"]

        await service.apply(expected_revision=0, values={"worker_concurrency": 2})
        exported = await service.export()
        assert exported["values"]["worker_concurrency"] == 2
        assert "telegram_api_hash" not in exported["values"]

    asyncio.run(scenario())


def test_secret_snapshot_exposes_presence_never_plaintext() -> None:
    snapshot = resolve_effective_settings(
        persisted=PersistedSettings(
            secret_references={
                "telegram_api_hash": SecretReferenceMutation("secure:telegram-hash", True)
            }
        ),
        environ={},
        runtime_mode="desktop",
    )

    secret = snapshot.values["telegram_api_hash"]
    assert secret.value is None
    assert secret.configured is True
    assert "secure:telegram-hash" not in repr(snapshot)


def test_api_and_worker_settings_snapshots_resolve_identically() -> None:
    persisted = PersistedSettings(
        revision=4,
        values={"worker_concurrency": json.dumps(2), "ocr_provider": json.dumps("mock")},
    )
    environment = {"STORAGE_BACKEND": "local", "WORKER_CONCURRENCY": "3"}

    api_settings = load_effective_settings(
        Settings(_env_file=None),
        environ=environment,
        persisted=persisted,
    )
    worker_settings = load_effective_settings(
        Settings(_env_file=None),
        environ=environment,
        persisted=persisted,
    )

    assert api_settings.model_dump() == worker_settings.model_dump()
    assert api_settings.effective_snapshot == worker_settings.effective_snapshot
    assert api_settings.effective_snapshot is not None
    assert api_settings.effective_snapshot.revision == 4


def test_desktop_does_not_silently_read_legacy_dotenv(monkeypatch, tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "BENTO_RUNTIME_MODE=desktop\nSTORAGE_BACKEND=local\nBENTO_TELEGRAM_API_HASH=must-not-load",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BENTO_RUNTIME_MODE", "desktop")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("BENTO_TELEGRAM_API_HASH", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.storage_backend == "telegram"
        assert settings.telegram_api_hash is None
    finally:
        get_settings.cache_clear()


def test_fake_storage_backend_is_rejected_in_production() -> None:
    from bento.application.settings import _cross_validate

    base = {"storage_backend": "fake", "data_dir": "/tmp/bento-data"}
    issues = _cross_validate({**base, "environment": "production"}, {})

    assert [issue.code for issue in issues] == ["storage_backend_unavailable"]
    assert _cross_validate({**base, "environment": "local"}, {}) == []
