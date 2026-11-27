"""The worker's wiring and the live `embeddings_provider` read by the API and the upload policy follow smart search
activation and removal without a restart (bug 1 of the 2026-11-26 real-model exit check)."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from bento.domain.smart_search import EMBEDDINGS_PROVIDER_CHOICES
from bento.infrastructure.settings import (
    Settings,
    live_embeddings_provider,
    load_effective_settings,
    serialize_setting_value,
    settings_database_path,
)
from bento.interfaces.worker import main as worker_main
from tests.integration.db.support import migrated_session_factory


def _settings(tmp_path: Path, **values: object) -> Settings:
    return Settings(data_dir=str(tmp_path / "data"), storage_backend="local", **values)  # type: ignore[arg-type]


def _save_provider(settings: Settings, value: str) -> None:
    database = settings_database_path(settings)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("embeddings_provider", serialize_setting_value("embeddings_provider", value)),
        )


def _migrated(settings: Settings) -> None:
    database_dir = settings_database_path(settings).parent
    database_dir.mkdir(parents=True)
    migrated_session_factory(database_dir)


def test_a_worker_started_with_smart_search_off_still_owns_an_idle_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker_main, "_WORKER_EMBEDDINGS", {})
    settings = _settings(tmp_path, embeddings_provider="disabled")
    _migrated(settings)

    embedding = worker_main._worker_embedding(settings)

    assert embedding.runtime is not None
    # Status `off`: nothing to serve, so embedding jobs are no-ops and no server starts.
    assert asyncio.run(embedding.provider.is_enabled()) is False
    asyncio.run(embedding.runtime.tick())
    assert embedding.runtime.current_endpoint() is None


@pytest.mark.parametrize(
    "values",
    [
        {"embeddings_provider": "mock"},
        {"embeddings_provider": "disabled", "platform": "android"},
    ],
)
def test_workers_pinned_elsewhere_keep_their_wiring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, values: dict[str, object]
) -> None:
    monkeypatch.setattr(worker_main, "_WORKER_EMBEDDINGS", {})

    assert worker_main._worker_embedding(_settings(tmp_path, **values)).runtime is None


def test_an_environment_lock_on_disabled_keeps_the_worker_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_main, "_WORKER_EMBEDDINGS", {})
    settings = load_effective_settings(
        Settings(data_dir=str(tmp_path / "data")), environ={"EMBEDDINGS_PROVIDER": "disabled"}, persisted=None
    )

    assert worker_main._worker_embedding(settings).runtime is None
    assert live_embeddings_provider(settings)() == "disabled"


def test_the_live_provider_reads_the_saved_value_each_call(tmp_path: Path) -> None:
    settings = _settings(tmp_path, embeddings_provider="disabled")
    read = live_embeddings_provider(settings)
    assert read() == "disabled"  # no database yet: the startup value

    _migrated(settings)
    assert read() == "disabled"  # no row yet
    _save_provider(settings, "managed")  # what activation writes
    assert read() == "managed"
    _save_provider(settings, "disabled")  # what removal writes
    assert read() == "disabled"


def test_the_live_provider_ignores_unknown_values_and_pinned_providers(tmp_path: Path) -> None:
    settings = _settings(tmp_path, embeddings_provider="disabled")
    _migrated(settings)
    with sqlite3.connect(settings_database_path(settings)) as connection:
        connection.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES ('embeddings_provider', '\"jina\"', CURRENT_TIMESTAMP)"
        )
    assert "jina" not in EMBEDDINGS_PROVIDER_CHOICES
    assert live_embeddings_provider(settings)() == "disabled"

    custom = _settings(tmp_path, embeddings_provider="custom")
    assert live_embeddings_provider(custom)() == "custom"  # `custom` keeps its startup wiring


def test_an_environment_lock_on_managed_is_never_overridden_by_a_saved_row(tmp_path: Path) -> None:
    base = Settings(data_dir=str(tmp_path / "data"))
    _migrated(base)
    _save_provider(base, "disabled")
    settings = load_effective_settings(base, environ={"EMBEDDINGS_PROVIDER": "managed"})

    assert settings.embeddings_provider == "managed"
    assert live_embeddings_provider(settings)() == "managed"
