from __future__ import annotations

import base64
from pathlib import Path

import pytest
from pydantic import ValidationError

from bento.infrastructure.settings import Settings
from main import (
    _check_key_store,
    _check_settings_registry,
    _check_storage_mode,
    _check_telegram,
    _load_settings,
    _redact_secrets,
    _validation_detail,
)


def test_load_settings_uses_registry_aliases_and_process_precedence(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(
        "DATA_DIR=./data\nEMBEDDINGS_PROVIDER=disabled\n",
        encoding="utf-8",
    )

    settings = _load_settings(
        tmp_path,
        environ={"BENTO_EMBEDDING_PROVIDER": "mock"},
    )

    assert settings.embeddings_provider == "mock"
    assert settings.data_dir == "./data"
    assert _check_settings_registry(settings).status == "pass"


def test_telegram_credentials_are_reported_without_echoing_secret_values() -> None:
    secret = "do-not-print-this-secret"
    settings = Settings(storage_backend="telegram", telegram_api_id="123", telegram_api_hash=secret)

    check = _check_telegram(settings)

    assert check.status == "pass"
    assert secret not in check.detail


def test_telegram_mode_without_build_credentials_names_the_aliases() -> None:
    check = _check_telegram(Settings(storage_backend="telegram"))

    assert check.status == "fail"
    assert "BENTO_TELEGRAM_API_ID" in check.detail and "BENTO_TELEGRAM_API_HASH" in check.detail


def test_local_mode_reports_credentials_without_requiring_them() -> None:
    check = _check_telegram(Settings(storage_backend="local"))

    assert check.status == "pass"
    assert "missing BENTO_TELEGRAM_API_ID" in check.detail
    assert _check_storage_mode(Settings(storage_backend="fake")).detail.startswith("fake")


def test_non_numeric_api_id_fails() -> None:
    assert _check_telegram(Settings(storage_backend="telegram", telegram_api_id="abc", telegram_api_hash="x")).status == "fail"


def test_key_store_mode_warns_for_file_based_wrapping_keys(tmp_path: Path) -> None:
    key = base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")

    assert _check_key_store(tmp_path, {"BENTO_DEVICE_WRAPPING_KEY": key}).status == "pass"
    assert _check_key_store(tmp_path, {"BENTO_DEVICE_WRAPPING_KEY": "short"}).status == "fail"
    assert _check_key_store(tmp_path, {}).status == "warn"
    (tmp_path / "secure").mkdir()
    (tmp_path / "secure" / "wrapping.key").write_text(key, encoding="utf-8")
    check = _check_key_store(tmp_path, {})
    assert check.status == "warn"
    assert "protect this folder" in check.detail
    assert key not in check.detail


def test_validation_and_external_diagnostics_redact_secret_values() -> None:
    secret = "do-not-print-this-secret"
    with pytest.raises(ValidationError) as raised:
        Settings(telegram_api_hash=secret, worker_concurrency=99)

    assert _validation_detail(raised.value) == "invalid fields: worker_concurrency"
    assert secret not in _validation_detail(raised.value)
    assert _redact_secrets(f"compose failed near {secret}", Settings(telegram_api_hash=secret)) == (
        "compose failed near [REDACTED]"
    )
