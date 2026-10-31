from __future__ import annotations

import asyncio
import sqlite3

import pytest

from bento.adapters.settings import SQLiteSettingsRepository
from bento.domain.errors import SettingsRevisionConflictError, ValidationFailedError
from bento.domain.settings import SecretReferenceMutation
from tests.integration.db.support import FixedClock, migrated_session_factory


def test_settings_compare_and_set_is_versioned_and_secret_safe(tmp_path) -> None:
    async def scenario() -> None:
        repository = SQLiteSettingsRepository(migrated_session_factory(tmp_path), FixedClock())
        first = await repository.compare_and_set(
            expected_revision=0,
            values={"worker_concurrency": "2"},
            secret_references={
                "telegram_api_hash": SecretReferenceMutation("secure:telegram-token", True)
            },
        )
        assert first.revision == 1
        assert first.values == {"worker_concurrency": "2"}
        assert first.secret_references["telegram_api_hash"].configured is True

        with pytest.raises(SettingsRevisionConflictError):
            await repository.compare_and_set(
                expected_revision=0,
                values={"worker_concurrency": "3"},
                secret_references={},
            )
        with pytest.raises(ValidationFailedError):
            await repository.compare_and_set(
                expected_revision=1,
                values={"telegram_api_hash": "top-secret-value"},
                secret_references={},
            )

    asyncio.run(scenario())

    database = sqlite3.connect(tmp_path / "bento.sqlite3")
    try:
        dump = "\n".join(database.iterdump())
    finally:
        database.close()
    assert "top-secret-value" not in dump
    assert "secure:telegram-token" in dump
