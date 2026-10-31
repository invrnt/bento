from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bento.infrastructure import process_secrets
from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app
from tests.integration.db.support import migrated_session_factory

TOKEN = "desktop-test-token-with-more-than-32-characters"
ORIGIN = "bento://app"
ENVIRON = {
    "BENTO_DESKTOP_API_TOKEN": TOKEN,
    "BENTO_DESKTOP_ORIGIN": ORIGIN,
}


def _desktop_client(tmp_path) -> TestClient:
    data_dir = tmp_path / "data"
    (data_dir / "db").mkdir(parents=True)
    migrated_session_factory(data_dir / "db")
    app = create_app(
        Settings(data_dir=str(data_dir), runtime_mode="desktop"),
        desktop_environ=ENVIRON,
    )
    return TestClient(app)


def test_desktop_mode_refuses_to_start_without_per_launch_credentials(tmp_path) -> None:
    settings = Settings(data_dir=str(tmp_path), runtime_mode="desktop")

    with pytest.raises(RuntimeError, match="BENTO_DESKTOP_API_TOKEN"):
        create_app(settings, desktop_environ={})


def test_desktop_api_requires_exact_origin_and_bearer_on_every_route(tmp_path) -> None:
    client = _desktop_client(tmp_path)

    assert client.get("/api/health").status_code == 403
    assert client.get("/api/health", headers={"Origin": ORIGIN}).status_code == 401
    assert client.get(
        "/api/health",
        headers={"Origin": "bento://hostile", "Authorization": f"Bearer {TOKEN}"},
    ).status_code == 403
    assert client.get(
        "/api/health",
        headers={"Origin": ORIGIN, "Authorization": "Bearer incorrect"},
    ).status_code == 401

    response = client.get(
        "/api/health",
        headers={"Origin": ORIGIN, "Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200


def test_desktop_preflight_accepts_only_the_configured_origin(tmp_path) -> None:
    client = _desktop_client(tmp_path)
    headers = {
        "Origin": ORIGIN,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    }

    response = client.options("/api/health", headers=headers)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert client.options("/api/health", headers={**headers, "Origin": "bento://hostile"}).status_code == 400


def test_authenticated_readiness_reports_only_fixed_runtime_metadata(tmp_path) -> None:
    client = _desktop_client(tmp_path)

    response = client.get(
        "/api/desktop/readiness",
        headers={"Origin": ORIGIN, "Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "version": "0.1.0"}
    assert str(tmp_path) not in response.text
    assert TOKEN not in response.text


def test_readiness_stays_unavailable_until_database_is_migrated(tmp_path) -> None:
    data_dir = tmp_path / "data"
    client = TestClient(
        create_app(
            Settings(data_dir=str(data_dir), runtime_mode="desktop"),
            desktop_environ=ENVIRON,
        )
    )

    response = client.get(
        "/api/desktop/readiness",
        headers={"Origin": ORIGIN, "Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 503
    assert response.json() == {"status": "starting", "code": "database_not_migrated"}


def test_headless_mode_keeps_existing_unauthenticated_contract(tmp_path) -> None:
    client = TestClient(create_app(Settings(data_dir=str(tmp_path), runtime_mode="headless")))

    response = client.get("/api/health")

    assert response.status_code == 200


def test_desktop_token_is_read_from_the_process_private_holder(tmp_path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "db").mkdir(parents=True)
    migrated_session_factory(data_dir / "db")
    process_secrets.clear()
    process_secrets.adopt_environment_secrets(("BENTO_DESKTOP_API_TOKEN",), {"BENTO_DESKTOP_API_TOKEN": TOKEN})
    try:
        app = create_app(
            Settings(data_dir=str(data_dir), runtime_mode="desktop"),
            desktop_environ={"BENTO_DESKTOP_ORIGIN": ORIGIN},
        )
    finally:
        process_secrets.clear()
    client = TestClient(app)

    assert client.get("/api/health", headers={"Origin": ORIGIN}).status_code == 401
    assert client.get("/api/health", headers={"Origin": ORIGIN, "Authorization": f"Bearer {TOKEN}"}).status_code == 200
