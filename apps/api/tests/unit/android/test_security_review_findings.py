"""Stage 22 Android security review (`orchestration/execution/android-security-review.md`).

Regression tests for the fixed findings (SEC-01 server side, SEC-02, SEC-06, SEC-07, SEC-12), plus guards for
behavior the review relies on. The engine-level SEC-01 rotation test lives in
`tests/integration/android/test_engine_smoke.py::test_start_api_rotates_credentials_and_proves_the_server`.
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


def test_sec02_android_pillow_has_the_psd_fixes() -> None:
    assert _pinned("pillow") >= (13, 0, 0)  # 12.2 fixed the PSD OOB writes; 13.0 the later advisories


def test_sec07_starlette_has_the_range_fix() -> None:
    assert _pinned("starlette") >= (1, 3, 1)  # 0.49.1 fixed the Range DoS; 1.3.1 the Host/path/form advisories


def _psd(path: Path) -> Path:
    """A minimal valid 2x2 RGB Photoshop file (Pillow opens it when every plugin is enabled)."""
    import struct

    header = b"8BPS" + struct.pack(">H6xHIIHH", 1, 3, 2, 2, 8, 3)
    path.write_bytes(header + struct.pack(">III", 0, 0, 0) + struct.pack(">H", 0) + bytes(3 * 2 * 2))
    return path


def test_sec02_psd_is_never_parsed_by_metadata_or_thumbnails(tmp_path: Path) -> None:
    from PIL import Image, UnidentifiedImageError

    from bento.adapters.media.generator import LocalMediaGenerator
    from bento.adapters.media.image_formats import IMAGE_FORMATS, open_formats
    from bento.adapters.media.metadata import _extract_image_exif

    psd = _psd(tmp_path / "shared.png")  # the share sheet chooses the name and MIME type
    with Image.open(psd) as image:
        assert image.format == "PSD"  # the fixture is a real PSD
    assert "PSD" not in IMAGE_FORMATS
    with pytest.raises(UnidentifiedImageError):
        Image.open(psd, formats=open_formats())
    assert _extract_image_exif(psd) == (None, None)

    class _Asset:
        id = "a1"

    generator = LocalMediaGenerator(tmp_path / "cache")
    with pytest.raises(UnidentifiedImageError):
        generator._generate_image(_Asset(), psd)  # type: ignore[arg-type]
    png = tmp_path / "ok.png"
    Image.new("RGB", (8, 8)).save(png)
    assert len(generator._generate_image(_Asset(), png)) == 3  # type: ignore[arg-type]


def test_sec06_redaction_removes_pairing_codes(tmp_path: Path, clean_redaction: None) -> None:
    redaction.install(tmp_path, mirror=False)
    for text, code in (
        ("pairing join failed for code 7KQ2-M9XA-4TZP", "7KQ2-M9XA-4TZP"),
        ("pairing join failed for 7kq2-m9xa-4tzp", "7kq2-m9xa-4tzp"),
        ("parsed 7KQ2M9XA4TZP from the QR", "7KQ2M9XA4TZP"),
        ("typed 7KQ2 M9XA 4TZP", "7KQ2 M9XA 4TZP"),
        ("open bento://join?v=1&c=7KQ2-M9XA-4TZP&h=x", "7KQ2-M9XA-4TZP"),
        ("open https://bento.app/join#c=ZZZZZZZZZZZZ", "ZZZZZZZZZZZZ"),
        ("join pairing_code=ABCDEFGH1JKM", "ABCDEFGH1JKM"),
    ):
        assert code not in redaction.redact(text), text
    # Words, numbers and error codes stay readable.
    kept = "pairing failed code=relay_closed after 1234 ms for successfully"
    assert redaction.redact(kept) == kept


def test_sec06_redaction_removes_phone_numbers_with_and_without_plus(tmp_path: Path, clean_redaction: None) -> None:
    redaction.install(tmp_path, mirror=False)
    for text, phone in (
        ("send_code_request phone=573001234567", "573001234567"),
        ('payload {"phone": "300 123 4567"}', "300 123 4567"),
        ("phone_number: 3001234567", "3001234567"),
        ("calling +57 300 123 4567", "300 123 4567"),
        ("calling +573001234567", "573001234567"),
    ):
        assert phone not in redaction.redact(text), text


def test_sec06_redaction_removes_login_codes_and_2fa_passwords(tmp_path: Path, clean_redaction: None) -> None:
    redaction.install(tmp_path, mirror=False)
    for text, secret in (
        ("sign_in code=12345", "12345"),
        ("Telegram login code 54321 rejected", "54321"),
        ("the code is 678901", "678901"),
        ("check_password password=hunter2!", "hunter2!"),
        ("{'password': 'correct horse'}", "correct"),
        ("2fa: s3cr3t", "s3cr3t"),
    ):
        assert secret not in redaction.redact(text), text


def test_sec06_registered_secrets_are_redacted_until_unregistered(clean_redaction: None) -> None:
    redaction.register("live-login-secret")
    assert "live-login-secret" not in redaction.redact("value live-login-secret")
    redaction.unregister("live-login-secret")
    assert "live-login-secret" in redaction.redact("value live-login-secret")


def test_sec06_warm_up_logs_are_buffered_and_redacted_before_install(
    tmp_path: Path, clean_redaction: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import logging

    reached_last_resort: list[logging.LogRecord] = []

    class _Recorder(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            reached_last_resort.append(record)

    monkeypatch.setattr(logging, "lastResort", _Recorder())
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    engine.warm_up()  # installs the early buffer even when the report is cached
    logging.getLogger("bento.test").warning("warm-up saw phone=573001234567 and Bearer abcdef")
    assert reached_last_resort == []
    path = redaction.install(tmp_path / "logs", mirror=False)
    for handler in root.handlers:
        handler.flush()
    content = path.read_text(encoding="utf-8")
    assert "warm-up saw" in content
    assert "573001234567" not in content and "abcdef" not in content


def test_sec01_server_proof_signs_nonced_responses_only() -> None:
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from bento.interfaces.android.server_proof import ServerProofMiddleware, server_proof

    key = "k" * 43
    app = ServerProofMiddleware(Starlette(routes=[Route("/", lambda _: PlainTextResponse("ok"))]), key=key, port=4242)
    client = TestClient(app)
    nonce = "n0nce-0123456789abcdef"
    assert client.get("/", headers={"X-Bento-Nonce": nonce}).headers["x-bento-proof"] == server_proof(key, 4242, nonce)
    assert "x-bento-proof" not in client.get("/").headers
    assert "x-bento-proof" not in client.get("/", headers={"X-Bento-Nonce": "short"}).headers
    assert "x-bento-proof" not in client.get("/", headers={"X-Bento-Nonce": "bad nonce with spaces!!"}).headers
    # The port is part of the MAC: a proof relayed from another port does not verify.
    assert server_proof(key, 4242, nonce) != server_proof(key, 4243, nonce)
    with pytest.raises(ValueError):
        ServerProofMiddleware(app, key="short", port=1)


def test_sec01_server_proof_matches_the_kotlin_test_vector() -> None:
    """Same vector as `ServerProofTest` in `core/api` (Kotlin)."""
    from bento.interfaces.android.server_proof import server_proof

    assert server_proof("server-key-0123456789abcdef0123456789", 41000, "nonce-0123456789ab") == (
        "gUIkCMgwLLTTAlQIPwi9Rt5QVQlaB93G7MgR42IWw8g"
    )


def test_sec12_loopback_uvicorn_limits_connections() -> None:
    assert 0 < engine.API_LIMIT_CONCURRENCY <= 128
    assert 0 < engine.API_BACKLOG <= 128
    assert 0 < engine.API_TIMEOUT_KEEP_ALIVE_SECONDS <= 10


def test_guard_release_engine_refuses_the_fake_backend() -> None:
    base = {"data_dir": "/x", "environment": "production"}
    with pytest.raises(engine.EngineConfigError):
        engine._settings_environ({**base, "storage_backend": "fake"})
    with pytest.raises(engine.EngineConfigError):
        engine._settings_environ({**base, "fake_telegram_url": "http://10.0.2.2:8790"})


def test_guard_engine_settings_overrides_are_allow_listed() -> None:
    with pytest.raises(engine.EngineConfigError):
        engine._settings_environ({"data_dir": "/x", "settings": {"HOST": "0.0.0.0"}})
