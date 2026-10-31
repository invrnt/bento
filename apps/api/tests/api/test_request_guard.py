"""Headless API guard: loopback `Host` only (DNS rebinding) and `X-Bento-Client: web` on unsafe methods (CSRF)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app
from bento.interfaces.http.request_guard import allowed_hosts_from_environ, host_name
from tests.integration.db.support import migrated_session_factory

WEB_ORIGIN = "http://127.0.0.1:5173"
POST_PATH = "/api/pairing/host"  # local mode answers 503 `telegram_not_configured` once past the guard


def _client(tmp_path: Path, *, base_url: str = "http://127.0.0.1:8000", headers: dict[str, str] | None = None) -> TestClient:
    app = create_app(Settings(data_dir=str(tmp_path), storage_backend="local"))
    return TestClient(app, base_url=base_url, headers=headers or {})


def test_unsafe_methods_need_the_web_client_header(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = client.request(method, POST_PATH)
        assert response.status_code == 403, method
        error = response.json()["error"]
        assert error["code"] == "csrf_header_missing" and error["request_id"]
    assert client.post(POST_PATH, headers={"X-Bento-Client": "other"}).status_code == 403
    allowed = client.post(POST_PATH, headers={"X-Bento-Client": "web"})
    assert allowed.status_code == 503 and allowed.json()["error"]["code"] == "telegram_not_configured"
    assert client.get("/api/health").status_code == 200
    assert client.head("/api/health").status_code in {200, 405}


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:5173", "LOCALHOST", "[::1]:8000", "[::1]", "127.0.0.1"])
def test_loopback_hosts_are_allowed(tmp_path: Path, host: str) -> None:
    client = _client(tmp_path, headers={"X-Bento-Client": "web", "Host": host})
    assert client.get("/api/health").status_code == 200
    assert client.post(POST_PATH).status_code == 503


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "127.0.0.1.evil.example", "localhost.", "0.0.0.0:8000"])
def test_other_hosts_are_rejected_even_for_reads(tmp_path: Path, host: str) -> None:
    client = _client(tmp_path, headers={"X-Bento-Client": "web"})
    for method in ("GET", "POST"):
        response = client.request(method, "/api/health" if method == "GET" else POST_PATH, headers={"Host": host})
        assert response.status_code == 400, (method, host)
        assert response.json()["error"]["code"] == "host_not_allowed"


def test_extra_hosts_come_from_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BENTO_ALLOWED_HOSTS", " nas.local , Bento.Home:8000,,")
    for host in ("nas.local", "nas.local:8000", "bento.home:9000"):
        client = _client(tmp_path, base_url=f"http://{host}", headers={"X-Bento-Client": "web"})
        assert client.get("/api/health").status_code == 200, host
    assert _client(tmp_path, base_url="http://other.local").get("/api/health").status_code == 400


def test_rejections_keep_cors_headers_for_the_web_origin(tmp_path: Path) -> None:
    client = _client(tmp_path)
    preflight = client.options(
        POST_PATH,
        headers={
            "Origin": WEB_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-bento-client",
        },
    )
    assert preflight.status_code == 200
    assert "x-bento-client" in preflight.headers["access-control-allow-headers"].lower()
    rejected = client.post(POST_PATH, headers={"Origin": WEB_ORIGIN})
    assert rejected.status_code == 403 and rejected.headers["access-control-allow-origin"] == WEB_ORIGIN
    foreign = client.options(
        POST_PATH,
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-bento-client"},
    )
    assert "access-control-allow-origin" not in foreign.headers


def test_desktop_mode_keeps_its_own_protection(tmp_path: Path) -> None:
    token = "desktop-test-token-with-more-than-32-characters"
    origin = "bento://app"
    data_dir = tmp_path / "data"
    (data_dir / "db").mkdir(parents=True)
    migrated_session_factory(data_dir / "db")
    app = create_app(
        Settings(data_dir=str(data_dir), runtime_mode="desktop", storage_backend="local"),
        desktop_environ={"BENTO_DESKTOP_API_TOKEN": token, "BENTO_DESKTOP_ORIGIN": origin},
    )
    client = TestClient(app, base_url="http://testserver", headers={})
    auth = {"Origin": origin, "Authorization": f"Bearer {token}"}
    for headers in (auth, {**auth, "X-Bento-Client": "web"}):
        response = client.post(POST_PATH, headers=headers)
        assert response.status_code == 503, response.text
    assert client.post(POST_PATH, headers={"X-Bento-Client": "web"}).status_code == 403


def test_host_parsing() -> None:
    assert host_name("LocalHost:8000") == "localhost"
    assert host_name("[::1]:8000") == "[::1]" and host_name("[::1]") == "[::1]"
    for malformed in ("", ":8000", "localhost:", "localhost:80a", "localhost:８０", "[::1", "::1", "[::1]x", "a:1:2"):
        assert host_name(malformed) is None, malformed
    assert allowed_hosts_from_environ({}) == {"127.0.0.1", "localhost", "[::1]"}
    assert allowed_hosts_from_environ({"BENTO_ALLOWED_HOSTS": "[fe80::1]:80, ::bad"}) == {
        "127.0.0.1",
        "localhost",
        "[::1]",
        "[fe80::1]",
    }
