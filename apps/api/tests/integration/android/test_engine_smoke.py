"""In-process engine smoke: configure -> migrate -> start_api -> /api/health -> worker -> stop, with fake bridges."""

from __future__ import annotations

import base64
import io
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from bento.infrastructure import process_secrets
from bento.infrastructure.settings import get_settings
from bento.interfaces.android import engine
from tests.unit.android.bridge_fakes import all_bridges


@pytest.fixture
def android(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, object]]:
    for name in ("BENTO_API_TOKEN", "BENTO_DEVICE_WRAPPING_KEY", "STORAGE_BACKEND", "DATA_DIR", "BENTO_PLATFORM"):
        monkeypatch.delenv(name, raising=False)
    environ_before = dict(os.environ)
    bridges = all_bridges(tmp_path / "host")
    config: dict[str, object] = {
        "data_dir": str(tmp_path / "no-backup" / "bento"),
        "no_backup_dir": str(tmp_path / "no-backup"),
        "cache_dir": str(tmp_path / "cache"),
        "platform": "android",
        "environment": "local",
        "storage_backend": "local",
        "wrapping_key": secrets.token_bytes(32),
        "app_version": "0.1.0-test",
        "device_name_default": "Pixel 7a",
        "bridges": bridges,
    }
    yield {"config": config, "bridges": bridges, "environ_before": environ_before}
    engine._reset_for_tests()


def _secret() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


def _get(port: int, path: str, token: str | None, nonce: str | None = None) -> tuple[int, dict[str, object]]:
    status, body, _ = _get_with_headers(port, path, token, nonce)
    return status, body


def _get_with_headers(
    port: int, path: str, token: str | None, nonce: str | None = None
) -> tuple[int, dict[str, object], dict[str, str]]:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    if nonce is not None:
        request.add_header("X-Bento-Nonce", nonce)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read()), {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read()), {k.lower(): v for k, v in exc.headers.items()}


def _upload(port: int, token: str, name: str, content: bytes, mime: str) -> dict[str, object]:
    boundary = "bento-test-boundary"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
        f"Content-Type: {mime}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/assets/upload", data=body, method="POST")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def test_engine_configure_migrate_serve_work_and_stop(android: dict[str, object]) -> None:
    config = android["config"]
    assert isinstance(config, dict)
    token, server_key = _secret(), _secret()

    summary = engine.configure(config)
    assert summary["platform"] == "android"
    assert engine.configure(dict(config)) == summary  # idempotent for an identical config
    with pytest.raises(engine.EngineConfigError):
        engine.configure({**config, "relay_url": "wss://other.example"})

    settings = get_settings()
    assert settings.platform == "android" and settings.backup_wifi_only is True and settings.ocr_provider == "mlkit"
    assert settings.device_name == "Pixel 7a"
    # Secrets live in the process holder only, never in the environment.
    assert process_secrets.get("BENTO_API_TOKEN") is None  # the token arrives with `start_api`
    assert {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"} == {
        k: v for k, v in android["environ_before"].items() if k != "PYTEST_CURRENT_TEST"  # type: ignore[union-attr]
    }
    assert token not in os.environ.values()

    first = engine.migrate()
    assert first["ran"] is True and first["from"] is None and str(first["to"]).startswith("00")
    again = engine.migrate()
    assert again == {"from": first["to"], "to": first["to"], "ran": False, "ms": again["ms"]}
    assert float(again["ms"]) < 50

    port = engine.start_api(token, server_key)
    assert engine.start_api(token, server_key) == port
    assert process_secrets.get("BENTO_API_TOKEN") == token
    assert _get(port, "/api/health", token)[0] == 200
    status, body = _get(port, "/api/health", None)
    assert status == 401 and body["error"]["code"] == "api_token_required"
    assert _get(port, "/openapi.json", token)[0] == 200  # non-production builds keep the schema

    engine.start_worker("drain")
    assert engine.status()["worker"] == "drain"
    from PIL import Image

    image = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 10, 10)).save(image, format="JPEG")
    asset = _upload(port, token, "photo.jpg", image.getvalue(), "image/jpeg")
    result = engine.run_worker_until(int(time.time() * 1000) + 20_000, ["thumbnail"])
    assert result["stopped_reason"] == "idle" and result["ran"] >= 1
    media_tools = android["bridges"]["media_tools"]  # type: ignore[index]
    assert [call[1][2] for call in media_tools.calls if call[0] == "thumbnail"] == [256, 1024, 1600]
    assert _get(port, f"/api/assets/{asset['id']}", token)[1]["processing_state"] in {"thumbnail_ready", "indexed", "ready"}

    assert engine.on_event("conditions", json.dumps({"online": True, "unmetered": False, "metered": True})) is True
    assert engine.on_event("bogus", "{}") is False

    state = engine.status()
    assert state["api_port"] == port and state["worker"] == "drain" and state["last_error"] is None
    assert "token" not in json.dumps(state)
    stopped = engine.stop(10_000)
    assert stopped == {"api_stopped": True, "worker_stopped": True}
    assert engine.status()["api_port"] is None and engine.status()["worker"] == "stopped"


def test_configure_rejects_bad_input(android: dict[str, object]) -> None:
    config = android["config"]
    assert isinstance(config, dict)
    with pytest.raises(engine.EngineConfigError):
        engine.configure({**config, "platform": "linux"})
    with pytest.raises(engine.EngineConfigError):
        engine.configure({**config, "api_token": _secret()})  # tokens are per API start, not configuration
    with pytest.raises(engine.EngineConfigError):
        engine.configure({**config, "wrapping_key": b"too-short"})
    with pytest.raises(engine.EngineConfigError):
        engine.configure({**config, "surprise": 1})
    with pytest.raises(engine.EngineConfigError):
        engine.configure({**config, "environment": "production", "storage_backend": "fake"})
    with pytest.raises(engine.EngineStateError):
        engine.migrate()
    # Java byte[] arrives as signed bytes.
    signed = [byte - 256 if byte > 127 else byte for byte in secrets.token_bytes(32)]
    assert engine.configure({**config, "wrapping_key": _SignedBytes(signed)})["platform"] == "android"


class _SignedBytes(list):  # bytes(list_with_negatives) raises ValueError, like a jbyte jarray
    pass


def test_start_api_rotates_credentials_and_proves_the_server(android: dict[str, object]) -> None:
    """SEC-01: every API start has its own token and server key; a dead server's token never works again."""
    from bento.interfaces.android.server_proof import server_proof

    config = android["config"]
    assert isinstance(config, dict)
    engine.configure(config)
    engine.migrate()
    first_token, first_key = _secret(), _secret()
    with pytest.raises(engine.EngineConfigError):
        engine.start_api("short", first_key)
    with pytest.raises(engine.EngineConfigError):
        engine.start_api(first_token, first_token)  # the proof key must be a separate secret
    first = engine.start_api(first_token, first_key)
    nonce = _secret()
    status, _, headers = _get_with_headers(first, "/api/health", first_token, nonce)
    assert status == 200 and headers["x-bento-proof"] == server_proof(first_key, first, nonce)
    # Rejections are signed too (the proof says who answered); no nonce, no proof.
    status, _, headers = _get_with_headers(first, "/api/health", None, nonce)
    assert status == 401 and headers["x-bento-proof"] == server_proof(first_key, first, nonce)
    assert "x-bento-proof" not in {key.lower() for key in _get_with_headers(first, "/api/health", first_token)[2]}

    second_token, second_key = _secret(), _secret()
    second = engine.start_api(second_token, second_key)  # new credentials replace the running server
    assert second != first
    assert _get(second, "/api/health", first_token)[0] == 401
    assert _get(second, "/api/health", second_token)[0] == 200
    with pytest.raises(OSError):
        _get(first, "/api/health", first_token)

    engine.stop(10_000)
    third_token = _secret()
    third = engine.start_api(third_token, _secret())
    assert _get(third, "/api/health", second_token)[0] == 401
    assert _get(third, "/api/health", third_token)[0] == 200
