"""Stage 22 Android security review (`orchestration/execution/android-security-review.md`).

`xfail(strict=True)` tests demonstrate open findings: they fail today, and turn into an XPASS (a failure) once fixed,
so whoever fixes a finding removes its marker. Unmarked tests are guards for behavior the review relies on.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from bento.interfaces.android import engine, redaction

REQUIREMENTS = Path(__file__).resolve().parents[4] / "android" / "python-wheels" / "requirements-android.txt"


@pytest.fixture
def clean_redaction() -> Iterator[None]:
    yield
    redaction.uninstall()


def _pinned(name: str) -> tuple[int, ...]:
    match = re.search(rf"^{re.escape(name)}==([0-9.]+)", REQUIREMENTS.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"{name} is not pinned in {REQUIREMENTS.name}"
    return tuple(int(part) for part in match.group(1).split("."))


@pytest.mark.xfail(strict=True, reason="SEC-02: Pillow 11.0.0 has the PSD OOB writes (CVE-2026-25990, CVE-2026-42311)")
def test_sec02_android_pillow_has_the_psd_fixes() -> None:
    assert _pinned("pillow") >= (12, 2, 0)


@pytest.mark.xfail(strict=True, reason="SEC-07: starlette 0.46.2 is affected by CVE-2025-62727 (Range header DoS)")
def test_sec07_starlette_has_the_range_fix() -> None:
    assert _pinned("starlette") >= (0, 49, 1)


@pytest.mark.xfail(strict=True, reason="SEC-06: pattern redaction does not cover pairing codes (NNNN-SSSS-SSSS)")
def test_sec06_redaction_removes_pairing_codes(tmp_path: Path, clean_redaction: None) -> None:
    redaction.install(tmp_path, mirror=False)
    assert "7KQ2-M9XA-4TZP" not in redaction.redact("pairing join failed for code 7KQ2-M9XA-4TZP")


@pytest.mark.xfail(strict=True, reason="SEC-06: pattern redaction does not cover phone numbers without a leading +")
def test_sec06_redaction_removes_phone_numbers_without_plus(tmp_path: Path, clean_redaction: None) -> None:
    redaction.install(tmp_path, mirror=False)
    assert "573001234567" not in redaction.redact("send_code_request phone=573001234567")


def test_guard_release_engine_refuses_the_fake_backend() -> None:
    base = {"data_dir": "/x", "environment": "production"}
    with pytest.raises(engine.EngineConfigError):
        engine._settings_environ({**base, "storage_backend": "fake"})
    with pytest.raises(engine.EngineConfigError):
        engine._settings_environ({**base, "fake_telegram_url": "http://10.0.2.2:8790"})


def test_guard_engine_settings_overrides_are_allow_listed() -> None:
    with pytest.raises(engine.EngineConfigError):
        engine._settings_environ({"data_dir": "/x", "settings": {"HOST": "0.0.0.0"}})
