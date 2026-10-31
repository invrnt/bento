"""Pairing HTTP endpoints across two apps (host and guest) on the fake cloud and the relay double."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bento.application.pairing import b64url_encode
from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app
from bento.interfaces.http.routes_pairing import get_device_service, get_pairing_service
from tests.integration.pairing.pairing_support import PairingDevice, make_pairing_device
from tests.integration.pairing.relay_double import RelayDouble, relay_in_thread

SITE = "https://bento.example"


@pytest.fixture
def relay() -> Iterator[RelayDouble]:
    with relay_in_thread() as running:
        yield running


def _app(device: PairingDevice, data_dir: Path, *, site_url: str = SITE) -> FastAPI:
    data_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(Settings(data_dir=str(data_dir), storage_backend="fake", public_site_url=site_url))
    app.dependency_overrides[get_pairing_service] = lambda: device.pairing
    app.dependency_overrides[get_device_service] = lambda: device.device_service
    return app


def _setup(tmp_path: Path, relay_url: str, *, guest_signed_in: bool = False) -> tuple[PairingDevice, PairingDevice]:
    host = make_pairing_device(tmp_path, tmp_path / "cloud", "host", relay_url=relay_url)
    guest = make_pairing_device(tmp_path, tmp_path / "cloud", "guest", relay_url=relay_url)

    async def prepare() -> None:
        await host.sign_in()
        await host.vault.create_vault()
        if guest_signed_in:
            await guest.sign_in()

    asyncio.run(prepare())
    return host, guest


class Recorder:
    """Keeps every response body so the test can assert that no secret ever leaves the API."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.bodies: list[str] = []

    def call(self, method: str, path: str, *, status: int = 200, **kwargs: Any) -> dict[str, Any]:
        response = self.client.request(method, path, **kwargs)
        self.bodies.append(response.text)
        assert response.status_code == status, response.text
        result: dict[str, Any] = response.json()
        return result

    def until(self, pairing_id: str, *states: str, timeout: float = 15.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            body = self.call("GET", f"/api/pairing/{pairing_id}")
            if body["state"] in states:
                return body
            assert body["state"] not in {"completed", "rejected", "failed", "expired", "cancelled"}, body
            assert time.monotonic() < deadline, body
            time.sleep(0.02)


def _secrets(*devices: PairingDevice) -> list[str]:
    values: list[str] = []
    for device in devices:
        values.append(b64url_encode(device.identity.private_key))
        values.append(device.identity.private_key.hex())
        values.extend(b64url_encode(token) for token in device.account.accepted_tokens)
        keyring = asyncio.run(device.vault.keyring())
        if keyring is not None:
            values.extend(b64url_encode(key) for key in keyring.keys.values())
    return values


def _assert_no_secrets(bodies: list[str], secrets: list[str]) -> None:
    text = "\n".join(bodies)
    for secret in secrets:
        assert secret not in text
    assert "tg://login" not in text
    assert "login_token" not in text and "sealed_keyring" not in text and "private" not in text


def test_relay_pairing_over_http(tmp_path: Path, relay: RelayDouble) -> None:
    host, guest = _setup(tmp_path, relay.url)
    with TestClient(_app(host, tmp_path / "host-app")) as host_client, TestClient(_app(guest, tmp_path / "guest-app")) as guest_client:
        hosting, joining = Recorder(host_client), Recorder(guest_client)
        hosted = hosting.call("POST", "/api/pairing/host")
        assert hosted["role"] == "host" and hosted["transport"] == "relay" and hosted["state"] == "waiting"
        code = hosted["code"]
        assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}", code)
        assert hosted["link"] == f"bento://join?v=1&c={code}"
        assert hosted["web_link"] == f"{SITE}/join#v=1&c={code}"
        assert hosted["qr"]["size"] == len(hosted["qr"]["rows"]) > 20
        assert hosted["sas"] is None and hosted["peer"] is None and hosted["error"] is None
        assert hosted["telegram_qr"] is None and hosted["expires_at"]

        joined = joining.call("POST", "/api/pairing/join", json={"code": hosted["web_link"]})
        assert joined["role"] == "guest" and joined["code"] is None and joined["link"] is None and joined["qr"] is None

        host_waiting = hosting.until(hosted["id"], "awaiting_approval")
        guest_waiting = joining.until(joined["id"], "awaiting_approval")
        assert host_waiting["sas"] == guest_waiting["sas"] and len(host_waiting["sas"]) == 4
        assert host_waiting["peer"] == {"device_name": "guest · Linux", "platform": "linux"}
        assert host_waiting["code"] == code, "the host keeps showing its live code"

        approving = hosting.call("POST", f"/api/pairing/{hosted['id']}/approve")
        assert approving["state"] == "approving"
        completed = hosting.until(hosted["id"], "completed")
        assert completed["code"] is None and completed["qr"] is None and completed["sas"] is None
        guest_done = joining.until(joined["id"], "completed")
        assert guest_done["error"] is None

        hosting.call("POST", f"/api/pairing/{hosted['id']}/approve", status=409)
        assert hosting.call("DELETE", f"/api/pairing/{hosted['id']}")["state"] == "completed"
        devices = hosting.call("GET", "/api/devices")["items"]
        assert {item["name"] for item in devices} == {"host · Linux", "guest · Linux"}
        _assert_no_secrets(hosting.bodies + joining.bodies, _secrets(host, guest))
    assert host.account.accepted_tokens, "the guest was signed in by the host"


def test_fallback_pairing_over_http(tmp_path: Path) -> None:
    host, guest = _setup(tmp_path, "", guest_signed_in=True)
    with TestClient(_app(host, tmp_path / "host-app")) as host_client, TestClient(_app(guest, tmp_path / "guest-app")) as guest_client:
        hosting, joining = Recorder(host_client), Recorder(guest_client)
        requested = joining.call("POST", "/api/pairing/request")
        assert requested["transport"] == "telegram" and requested["role"] == "guest" and requested["state"] == "waiting"

        [item] = hosting.call("GET", "/api/pairing/requests")["items"]
        assert set(item) == {"id", "device_name", "platform", "created_at"}
        assert item["device_name"] == "guest · Linux" and item["platform"] == "linux"

        reviewed = hosting.call("POST", f"/api/pairing/requests/{item['id']}/review")
        assert reviewed["state"] == "awaiting_approval" and reviewed["transport"] == "telegram"
        assert reviewed["code"] is None and reviewed["qr"] is None
        guest_view = joining.until(requested["id"], "awaiting_approval")
        assert guest_view["sas"] == reviewed["sas"] and len(reviewed["sas"]) == 4

        hosting.call("POST", f"/api/pairing/requests/{item['id']}/approve")
        hosting.until(reviewed["id"], "completed")
        joining.until(requested["id"], "completed")
        assert hosting.call("GET", "/api/pairing/requests")["items"] == []
        hosting.call("POST", f"/api/pairing/requests/{item['id']}/review", status=404)
        _assert_no_secrets(hosting.bodies + joining.bodies, _secrets(host, guest))
    assert asyncio.run(guest.vault.keyring()) == asyncio.run(host.vault.keyring())


def test_pairing_errors(tmp_path: Path, relay: RelayDouble) -> None:
    host, guest = _setup(tmp_path, relay.url, guest_signed_in=True)
    with TestClient(_app(host, tmp_path / "host-app")) as host_client, TestClient(_app(guest, tmp_path / "guest-app")) as guest_client:
        invalid = guest_client.post("/api/pairing/join", json={"code": "not-a-code"})
        assert invalid.status_code == 400 and invalid.json()["error"]["code"] == "pairing_code_invalid"
        assert invalid.json()["error"]["request_id"]
        assert guest_client.post("/api/pairing/join", json={}).status_code == 422
        assert guest_client.post("/api/pairing/join", json={"code": "x" * 600}).status_code == 422
        missing_room = guest_client.post("/api/pairing/join", json={"code": "ZZZZ-ZZZZ-ZZZZ"})
        assert missing_room.status_code == 404 and missing_room.json()["error"]["code"] == "pairing_room_not_found"
        for method, path in (
            ("GET", "/api/pairing/pair_missing"),
            ("POST", "/api/pairing/pair_missing/approve"),
            ("POST", "/api/pairing/pair_missing/reject"),
            ("DELETE", "/api/pairing/pair_missing"),
            ("POST", "/api/pairing/requests/missing/approve"),
        ):
            response = host_client.request(method, path)
            assert response.status_code == 404, (method, path, response.text)
            assert response.json()["error"]["code"] in {"pairing_not_found", "pairing_request_not_found"}

        locked = guest_client.post("/api/pairing/host")
        assert locked.status_code == 409 and locked.json()["error"]["code"] == "vault_locked"
        assert guest_client.get("/api/pairing/requests").json()["error"]["code"] == "vault_locked"
        paired = host_client.post("/api/pairing/request")
        assert paired.status_code == 409 and paired.json()["error"]["code"] == "pairing_already_paired"

        hosted = host_client.post("/api/pairing/host").json()
        conflict = host_client.post(f"/api/pairing/{hosted['id']}/approve")
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "pairing_state_conflict"
        cancelled = host_client.delete(f"/api/pairing/{hosted['id']}").json()
        assert cancelled["state"] == "cancelled" and cancelled["code"] is None and cancelled["error"] is None


def test_unavailable_relay_answers_503(tmp_path: Path) -> None:
    host, guest = _setup(tmp_path, "")
    with TestClient(_app(host, tmp_path / "host-app", site_url="")) as host_client, TestClient(
        _app(guest, tmp_path / "guest-app")
    ) as guest_client:
        for client, path, body in (
            (host_client, "/api/pairing/host", None),
            (guest_client, "/api/pairing/join", {"code": "K7Q2-MXR9-T4WA"}),
        ):
            response = client.post(path, json=body)
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "pairing_relay_unavailable"
    unreachable = make_pairing_device(tmp_path, tmp_path / "cloud", "far", relay_url="ws://127.0.0.1:9")
    asyncio.run(unreachable.sign_in())
    with TestClient(_app(unreachable, tmp_path / "far-app")) as client:
        response = client.post("/api/pairing/join", json={"code": "K7Q2-MXR9-T4WA"})
        assert response.status_code == 503 and response.json()["error"]["code"] == "pairing_relay_unavailable"


def test_local_only_mode_has_no_pairing(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(data_dir=str(tmp_path)))) as client:
        for method, path in (("POST", "/api/pairing/host"), ("GET", "/api/pairing/requests"), ("GET", "/api/devices")):
            response = client.request(method, path)
            assert response.status_code == 503, response.text
            assert response.json()["error"]["code"] == "telegram_not_configured"


def test_composition_root_wires_the_stage_15_factories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bento.adapters.security import InMemoryKeyStore, PairingCryptoFactory, VaultCrypto
    from bento.infrastructure import services
    from bento.infrastructure.runtime import get_telegram_runtime, reset_telegram_runtime
    from bento.interfaces.http.routes_pairing import PairingComponents
    from tests.integration.db.support import migrated_session_factory
    from tests.integration.pairing.pairing_support import FakeVaultSession

    data_dir = tmp_path / "data"
    (data_dir / "db").mkdir(parents=True)
    migrated_session_factory(data_dir / "db")
    settings = Settings(data_dir=str(data_dir), storage_backend="fake", relay_url="")
    key_store, crypto = InMemoryKeyStore(), VaultCrypto()
    reset_telegram_runtime()
    runtime = get_telegram_runtime(settings, key_store)
    assert runtime is not None
    vault = FakeVaultSession(runtime, key_store, crypto, None, name="x")  # type: ignore[arg-type]
    monkeypatch.setattr(services, "get_key_store", lambda _settings: key_store)
    monkeypatch.setattr(services, "get_vault_session", lambda _settings: vault)
    monkeypatch.setattr(services, "get_vault_crypto", lambda: crypto)
    monkeypatch.setattr(services, "get_pairing_crypto", lambda: PairingCryptoFactory())
    try:
        app = create_app(settings)
        with TestClient(app) as client:
            assert client.get("/api/devices").json() == {"items": []}
            components = app.state.pairing_components
            assert isinstance(components, PairingComponents)
            assert client.get("/api/devices").status_code == 200 and app.state.pairing_components is components
            not_signed_in = client.post("/api/pairing/host")
            assert not_signed_in.status_code == 409
            assert not_signed_in.json()["error"]["code"] == "telegram_not_authorized"
    finally:
        reset_telegram_runtime()
