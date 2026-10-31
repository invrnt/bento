"""Device endpoints: list, rename, remove with the mandatory new recovery kit."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from bento.application.devices import telegram_device_model
from bento.application.pairing import b64url_encode
from bento.domain.devices import Device, DevicePlatform
from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app
from bento.interfaces.http.qr import qr_matrix
from bento.interfaces.http.routes_pairing import get_device_service, get_pairing_service
from tests.integration.pairing.pairing_support import PairingDevice, make_pairing_device

RECOVERY_CODE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{4}(-[0-9A-HJKMNP-TV-Z]{4}){8}$")


def _setup(tmp_path: Path) -> tuple[PairingDevice, PairingDevice, str]:
    host = make_pairing_device(tmp_path, tmp_path / "cloud", "host")
    laptop = make_pairing_device(tmp_path, tmp_path / "cloud", "laptop")

    async def prepare() -> str:
        await host.sign_in()
        recovery_code = await host.vault.create_vault()
        await laptop.sign_in()
        keyring = await host.vault.keyring()
        assert keyring is not None and host.vault.layout is not None
        await laptop.vault.install(host.vault.layout, keyring)
        await host.devices.save(
            Device(
                id=laptop.device_id,
                name="laptop · Linux",
                platform=DevicePlatform.LINUX,
                public_key=b64url_encode(laptop.identity.public_key),
                added_at=datetime(2026, 10, 1, tzinfo=UTC),
            )
        )
        return recovery_code

    return host, laptop, asyncio.run(prepare())


def _client(device: PairingDevice, data_dir: Path) -> TestClient:
    data_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(Settings(data_dir=str(data_dir), storage_backend="fake"))
    app.dependency_overrides[get_device_service] = lambda: device.device_service
    app.dependency_overrides[get_pairing_service] = lambda: device.pairing
    return TestClient(app)


def test_list_and_rename_devices(tmp_path: Path) -> None:
    host, laptop, old_code = _setup(tmp_path)
    with _client(host, tmp_path / "app") as client:
        listed = client.get("/api/devices")
        assert listed.status_code == 200
        items = listed.json()["items"]
        assert [item["id"] for item in items] == [laptop.device_id, host.device_id]
        for item in items:
            assert set(item) == {
                "id",
                "name",
                "platform",
                "added_at",
                "last_seen_at",
                "current",
                "removed_at",
                "introduced_by",
                "first_seen_at",
                "needs_review",
            }
            assert item["needs_review"] is False and item["introduced_by"] is None
        current = [item for item in items if item["current"]]
        assert [item["id"] for item in current] == [host.device_id] and current[0]["last_seen_at"]
        assert items[0]["removed_at"] is None and items[0]["platform"] == "linux"

        renamed = client.patch(f"/api/devices/{laptop.device_id}", json={"name": "  Portátil  de Ana "})
        assert renamed.status_code == 200 and renamed.json()["name"] == "Portátil de Ana"
        for name in ("   ", "\u0007bell", "x" * 65):
            invalid = client.patch(f"/api/devices/{laptop.device_id}", json={"name": name})
            assert invalid.status_code == 400 and invalid.json()["error"]["code"] == "validation_failed"
        assert client.patch(f"/api/devices/{laptop.device_id}", json={}).status_code == 422
        missing = client.patch("/api/devices/dev_missing", json={"name": "x"})
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "device_not_found"
        text = listed.text + renamed.text
        assert old_code not in text and "public_key" not in text


def test_remove_device_returns_a_new_recovery_kit_once(tmp_path: Path) -> None:
    host, laptop, old_code = _setup(tmp_path)
    with _client(host, tmp_path / "app") as client:
        current = client.delete(f"/api/devices/{host.device_id}")
        assert current.status_code == 409 and current.json()["error"]["code"] == "device_is_current"
        missing = client.delete("/api/devices/dev_missing")
        assert missing.status_code == 404

        removed = client.delete(f"/api/devices/{laptop.device_id}")
        assert removed.status_code == 200, removed.text
        body = removed.json()
        assert set(body) == {"device", "telegram_session_closed", "recovery_code", "recovery_qr", "removed_device_ids"}
        assert body["removed_device_ids"] == [laptop.device_id]
        assert body["device"]["id"] == laptop.device_id and body["device"]["removed_at"]
        assert body["telegram_session_closed"] is True
        assert RECOVERY_CODE.match(body["recovery_code"]) and body["recovery_code"] != old_code
        assert body["recovery_qr"] == qr_matrix(f"bento-recovery:{body['recovery_code']}").model_dump()

        active = client.get("/api/devices").json()["items"]
        assert [item["id"] for item in active] == [host.device_id]
        everything = client.get("/api/devices", params={"include_removed": "true"}).json()["items"]
        assert {item["id"] for item in everything} == {host.device_id, laptop.device_id}
        assert body["recovery_code"] not in client.get("/api/devices").text
        renamed_removed = client.patch(f"/api/devices/{laptop.device_id}", json={"name": "x"})
        assert renamed_removed.status_code == 409 and renamed_removed.json()["error"]["code"] == "device_removed"

    assert not asyncio.run(laptop.runtime.account.status()).authorized
    keyring = asyncio.run(host.vault.keyring())
    assert keyring is not None and keyring.current_epoch == 2
    assert telegram_device_model(laptop.device_id).startswith("Bento (")
