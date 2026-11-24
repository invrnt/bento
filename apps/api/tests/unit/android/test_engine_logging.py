"""Engine warm-up report and redacted log routing (`bento.interfaces.android.engine` / `.redaction`)."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from bento.interfaces.android import engine, redaction


@pytest.fixture
def clean_redaction() -> Iterator[None]:
    yield
    redaction.uninstall()


def test_warm_up_imports_in_order_and_is_idempotent() -> None:
    first = json.loads(engine.warm_up())
    assert list(first["stages_ms"]) == [label for label, _ in engine.WARM_UP_ORDER]
    assert all(value >= 0 for value in first["stages_ms"].values())
    assert first["real_engine"] is True
    assert first["python"] == sys.version.split()[0]
    assert json.loads(engine.warm_up()) == first


def test_redact_removes_secrets_bearer_tokens_keys_and_phones(tmp_path: Path, clean_redaction: None) -> None:
    redaction.install(tmp_path, mirror=False, secrets=("s3cret-token-value",))
    text = redaction.redact(
        "GET /api/health Authorization: Bearer abc.def-123 token=s3cret-token-value key=" + "A" * 43 + " +573001234567"
    )
    assert "abc.def-123" not in text
    assert "s3cret-token-value" not in text
    assert "A" * 43 not in text
    assert "+573001234567" not in text
    assert "GET /api/health" in text


def test_install_routes_logging_and_stdout_to_a_redacted_file(tmp_path: Path, clean_redaction: None) -> None:
    original_stdout = sys.stdout
    path = redaction.install(tmp_path / "logs", mirror=False, secrets=("hunter2-token",))
    assert redaction.install(tmp_path / "logs", mirror=False) == path  # idempotent
    logging.getLogger("bento.test").warning("token is %s", "hunter2-token")
    print("printed hunter2-token")
    sys.stdout.flush()
    try:
        raise RuntimeError("boom hunter2-token")
    except RuntimeError:
        logging.getLogger("bento.test").exception("crashed")
    for handler in logging.getLogger().handlers:
        handler.flush()
    content = path.read_text(encoding="utf-8")
    assert "hunter2-token" not in content
    assert "token is <redacted>" in content
    assert "printed <redacted>" in content
    assert "RuntimeError: boom <redacted>" in content
    redaction.uninstall()
    assert sys.stdout is original_stdout
    assert not any(isinstance(handler.filters[0] if handler.filters else None, redaction.RedactingFilter)
                   for handler in logging.getLogger().handlers)
