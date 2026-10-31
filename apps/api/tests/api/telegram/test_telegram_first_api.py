from __future__ import annotations

import asyncio
import base64
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bento.adapters.fake_telegram import FAKE_LOGIN_CODE, FAKE_PASSWORD, FAKE_USER
from bento.infrastructure.mtproto import wiring
from bento.infrastructure.runtime import reset_telegram_runtime
from bento.infrastructure.services import reset_services
from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app
from bento.ports.key_store import DEVICE_IDENTITY, TELEGRAM_SESSION, VAULT_KEYRING
from tests.integration.db.support import migrated_session_factory

CARLOS = 777000002


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("BENTO_FAKE_TELEGRAM_MANUAL_LOGIN", "1")
    monkeypatch.delenv("BENTO_FAKE_TELEGRAM_2FA", raising=False)
    reset_telegram_runtime()
    reset_services()
    yield
    reset_telegram_runtime()
    reset_services()


class Recorder:
    """A client that keeps every response body, to prove secrets never leave the backend."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = TestClient(create_app(settings))
        self.bodies: list[bytes] = []

    def request(self, method: str, path: str, **kwargs: object):  # type: ignore[no-untyped-def]
        response = self.client.request(method, f"/api{path}", **kwargs)  # type: ignore[arg-type]
        self.bodies.append(response.content)
        return response

    def secrets(self) -> list[bytes]:
        store = wiring.key_store(self.settings)
        values = [asyncio.run(store.get(name)) for name in (TELEGRAM_SESSION, VAULT_KEYRING, DEVICE_IDENTITY)]
        found: list[bytes] = []
        for value in values:
            if value:
                found.append(value)
                found.extend(part.encode() for part in value.decode("utf-8", "replace").replace('"', " ").split() if len(part) > 20)
        keyring = values[1]
        if keyring:
            keys = wiring.vault_crypto().keyring_from_bytes(keyring).keys.values()
            found.extend(base64.urlsafe_b64encode(key).rstrip(b"=") for key in keys)
        return found

    def assert_no_secrets(self) -> None:
        secrets = self.secrets()
        assert secrets
        for body in self.bodies:
            for secret in secrets:
                assert secret not in body
            assert b"qr_token" not in body and b"session" not in body.lower()


def _settings(tmp_path: Path, name: str, *, cloud: Path | None = None, backend: str = "fake") -> Settings:
    data_dir = tmp_path / name
    (data_dir / "db").mkdir(parents=True)
    migrated_session_factory(data_dir / "db")
    return Settings(
        data_dir=str(data_dir), storage_backend=backend, fake_telegram_dir=str(cloud or tmp_path / "cloud")  # type: ignore[arg-type]
    )


def _sign_in_with_phone(api: Recorder) -> None:
    assert api.request("POST", "/account/login/phone", json={"phone": "+57 300 000 0001"}).json()["step"] == "code_required"
    assert api.request("POST", "/account/login/code", json={"code": FAKE_LOGIN_CODE}).json()["step"] == "authorized"


def test_account_qr_login_avatar_and_logout(tmp_path: Path) -> None:
    api = Recorder(_settings(tmp_path, "desk"))

    signed_out = api.request("GET", "/account").json()
    assert signed_out == {
        "step": "signed_out", "account": None, "qr_url": None, "qr": None, "qr_expires_at": None,
        "password_hint": None, "error": None,
    }
    assert api.request("GET", "/account/avatar").status_code == 404

    pending = api.request("POST", "/account/login/qr").json()
    assert pending["step"] == "qr_pending" and pending["qr_url"].startswith("tg://login?token=")
    assert pending["qr"]["size"] == len(pending["qr"]["rows"]) and set("".join(pending["qr"]["rows"])) <= {"0", "1"}
    assert pending["qr_expires_at"]
    assert api.request("POST", "/dev/fake-telegram/approve-login").json() == {"approved": 1}

    authorized = api.request("GET", "/account").json()
    assert authorized["step"] == "authorized" and authorized["qr"] is None
    assert authorized["account"] == {
        "user_id": FAKE_USER.user_id, "display_name": "Ana Demo", "username": "anademo",
        "phone_masked": FAKE_USER.phone_masked, "premium": False,
    }
    avatar = api.request("GET", "/account/avatar")
    assert avatar.status_code == 200 and avatar.headers["content-type"] == "image/jpeg"
    api.assert_no_secrets()

    assert api.request("POST", "/account/logout").json()["step"] == "signed_out"
    assert api.request("GET", "/account").json()["step"] == "signed_out"


def test_account_phone_code_and_password_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BENTO_FAKE_TELEGRAM_2FA", "1")
    api = Recorder(_settings(tmp_path, "desk"))

    expired = api.request("POST", "/account/login/code", json={"code": "12345"})
    assert expired.status_code == 409 and expired.json()["error"]["code"] == "telegram_login_expired"
    assert api.request("POST", "/account/login/phone", json={"phone": "+57 300 000 0001"}).json()["step"] == "code_required"
    wrong = api.request("POST", "/account/login/code", json={"code": "99999"}).json()
    assert wrong["step"] == "code_required" and wrong["error"]["code"] == "telegram_code_invalid"
    password = api.request("POST", "/account/login/code", json={"code": FAKE_LOGIN_CODE}).json()
    assert password["step"] == "password_required" and password["password_hint"] == "demo"
    bad = api.request("POST", "/account/login/password", json={"password": "hunter2-hunter2"})
    assert bad.json()["error"]["code"] == "telegram_password_invalid"
    assert b"hunter2" not in bad.content
    too_long = api.request("POST", "/account/login/password", json={"password": "p" * 300})
    assert too_long.status_code == 400 and b"ppppp" not in too_long.content

    assert api.request("POST", "/account/login/password", json={"password": FAKE_PASSWORD}).json()["step"] == "authorized"
    for body in api.bodies:
        assert FAKE_PASSWORD.encode() not in body and FAKE_LOGIN_CODE.encode() not in body


def test_vault_create_recovery_kit_and_unlock_on_a_second_device(tmp_path: Path) -> None:
    desk = Recorder(_settings(tmp_path, "desk"))
    assert desk.request("GET", "/vault").json()["state"] == "signed_out"
    assert desk.request("POST", "/vault").status_code == 409  # not signed in
    _sign_in_with_phone(desk)
    assert desk.request("GET", "/vault").json()["state"] == "no_vault"

    created = desk.request("POST", "/vault")
    assert created.status_code == 200 and created.headers["cache-control"] == "no-store"
    body = created.json()
    code = body["recovery_code"]
    assert len(code) == 44 and body["recovery_qr"]["size"] == len(body["recovery_qr"]["rows"])
    assert body["vault"]["state"] == "ready" and body["vault"]["devices_count"] == 1
    assert body["vault"]["recovery_kit_saved"] is False and body["vault"]["usage"] == {"files": 0, "bytes": 0}
    again = desk.request("POST", "/vault")
    assert again.status_code == 409 and again.json()["error"]["code"] == "vault_already_exists"
    status = desk.request("GET", "/vault").json()
    assert code.encode() not in desk.bodies[-1]
    assert status["vault_id"] == body["vault"]["vault_id"] and status["created_at"]

    mismatch = desk.request("POST", "/vault/recovery-code/confirm", json={"last_group": "ZZZZ"})
    assert mismatch.status_code == 400 and mismatch.json()["error"]["code"] == "recovery_group_mismatch"
    confirmed = desk.request("POST", "/vault/recovery-code/confirm", json={"last_group": code[-4:]})
    assert confirmed.json()["recovery_kit_saved"] is True
    assert desk.request("POST", "/vault/recovery-code/verify", json={"recovery_code": code}).json() == {"valid": True}
    rotated = desk.request("POST", "/vault/recovery-code").json()
    new_code = rotated["recovery_code"]
    assert new_code != code and rotated["recovery_qr"]["rows"]
    assert desk.request("POST", "/vault/recovery-code/verify", json={"recovery_code": code}).json() == {"valid": False}
    assert desk.request("POST", "/vault/recovery-code/verify", json={"recovery_code": "garbage"}).json() == {"valid": False}
    desk.assert_no_secrets()

    reset_telegram_runtime()
    laptop = Recorder(_settings(tmp_path, "laptop"))
    _sign_in_with_phone(laptop)
    locked = laptop.request("GET", "/vault").json()
    assert locked["state"] == "locked" and locked["vault_id"] == status["vault_id"]
    wrong = laptop.request("POST", "/vault/unlock", json={"recovery_code": code})
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "recovery_code_invalid"
    unlocked = laptop.request("POST", "/vault/unlock", json={"recovery_code": new_code})
    assert unlocked.status_code == 200 and unlocked.json()["state"] == "bootstrapping"
    laptop.assert_no_secrets()


def test_local_mode_and_missing_credentials(tmp_path: Path) -> None:
    local = Recorder(_settings(tmp_path, "local", backend="local"))
    assert local.request("GET", "/vault").json()["state"] == "local_only"
    assert local.request("GET", "/telegram/chats").json()["error"]["code"] == "storage_unavailable"

    no_build = Recorder(_settings(tmp_path, "nobuild", backend="telegram"))
    response = no_build.request("POST", "/account/login/qr")
    assert response.status_code == 503 and response.json()["error"]["code"] == "telegram_not_available"
    assert no_build.request("GET", "/account").json()["error"]["code"] == "telegram_not_available"
    assert no_build.request("GET", "/vault").json()["state"] == "signed_out"
    # The library keeps working locally.
    upload = no_build.request("POST", "/assets/upload", files={"file": ("nota.txt", b"hola", "text/plain")})
    assert upload.status_code == 200


def test_chats_import_and_share(tmp_path: Path) -> None:
    api = Recorder(_settings(tmp_path, "desk"))
    _sign_in_with_phone(api)
    assert api.request("POST", "/vault").status_code == 200

    chats = api.request("GET", "/telegram/chats").json()["items"]
    assert chats[0] == {"id": FAKE_USER.user_id, "title": "Saved Messages", "kind": "saved"}
    assert not [chat for chat in chats if chat["title"].startswith("Bento")]
    assert [chat["title"] for chat in api.request("GET", "/telegram/chats", params={"query": "carl"}).json()["items"]] == ["Carlos Ruiz"]

    media = api.request("GET", "/telegram/import/media", params={"chat_id": FAKE_USER.user_id}).json()
    assert [item["filename"] for item in media["items"]] == ["atardecer.jpg", "recibo-cafe.pdf"]
    assert media["next_cursor"] is None and set(media["items"][0]) == {"message_id", "kind", "filename", "size_bytes", "date"}
    bad_kind = api.request("GET", "/telegram/import/media", params={"chat_id": FAKE_USER.user_id, "kind": "sticker"})
    assert bad_kind.status_code == 400
    queued = api.request("POST", "/telegram/import", json={"chat_id": FAKE_USER.user_id, "all": True}).json()
    assert queued["queued"] == 2 and queued["job_id"]
    selected = api.request("POST", "/telegram/import", json={"chat_id": FAKE_USER.user_id, "message_ids": [media["items"][1]["message_id"]]})
    assert selected.json()["queued"] == 1
    assert api.request("POST", "/telegram/import", json={"chat_id": FAKE_USER.user_id}).status_code == 400

    upload = api.request("POST", "/assets/upload", files={"file": ("informe.txt", b"informe anual", "text/plain")}).json()
    shared = api.request("POST", f"/assets/{upload['id']}/share/telegram", json={"chat_id": CARLOS, "caption": "Hola"})
    assert shared.status_code == 200 and shared.json() == {"sent": True}
    missing = api.request("POST", "/assets/asset_missing/share/telegram", json={"chat_id": CARLOS})
    assert missing.status_code == 404
    from bento.adapters.fake_telegram import FakeTelegramCloud

    message = FakeTelegramCloud(tmp_path / "cloud").read_chat(CARLOS)[1][-1]
    assert message.media is not None and message.media.filename == "informe.txt" and message.text == "Hola"
    api.assert_no_secrets()
