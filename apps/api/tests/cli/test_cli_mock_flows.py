"""Client-level behavior against `httpx.MockTransport`: uploads, setup, login, pairing, confirmations."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from bento.interfaces.cli.commands import account as account_module
from bento.interfaces.cli.commands import pairing as pairing_module
from tests.cli.conftest import CliResult

Responder = Callable[[httpx.Request], Any]
FOLDER = {"id": "folder_1", "name": "Fotos", "parent_id": None, "created_at": "2024-01-01T00:00:00+00:00", "updated_at": "2024-01-01T00:00:00+00:00"}


def asset(asset_id: str, name: str, *, duplicate: bool = False, folder_id: str | None = "folder_1") -> dict[str, Any]:
    return {"id": asset_id, "kind": "document", "mode": "x", "folder_id": folder_id, "filename": name, "mime_type": "text/plain", "size_bytes": 1, "sha256": "0" * 64, "favorite": False, "processing_state": "indexed", "created_at": "2024-01-01T00:00:00+00:00", "updated_at": "2024-01-01T00:00:00+00:00", "duplicate": duplicate}


class FakeApi:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Responder | list[Responder]] = {}
        self.requests: list[httpx.Request] = []

    def on(self, method: str, path: str, *responses: Any) -> None:
        self.routes[(method, path)] = [response if callable(response) else (lambda _r, value=response: value) for response in responses]

    def calls(self, method: str, path: str) -> list[httpx.Request]:
        return [request for request in self.requests if request.method == method and request.url.path == "/api" + path]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.path.removeprefix("/api"))
        handlers = self.routes.get(key)
        if not handlers:
            return httpx.Response(404, json={"detail": "Not Found"})
        handler = handlers.pop(0) if len(handlers) > 1 else handlers[0]
        result = handler(request)
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json=result)


def error(status: int, code: str, **details: Any) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": code, "details": details, "request_id": "r"}})


def body(request: httpx.Request) -> Any:
    return json.loads(request.content)


@pytest.fixture(autouse=True)
def _fast_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(account_module, "POLL_SECONDS", 0.0)
    monkeypatch.setattr(pairing_module, "POLL_SECONDS", 0.0)


# Upload planning -----------------------------------------------------------------------------


def _local_tree(root: Path) -> Path:
    (root / "Viaje" / "Dia1").mkdir(parents=True)
    (root / "Viaje" / "Dia1" / "existing.txt").write_text("already in bento")
    (root / "Viaje" / "Dia1" / "new.txt").write_text("new content")
    (root / "Viaje" / "top.txt").write_text("top")
    return root / "Viaje"


def test_upload_skips_known_content_and_ensures_each_folder_once_parents_first(mock_cli: Callable[..., CliResult], tmp_path: Path) -> None:
    import hashlib

    viaje = _local_tree(tmp_path)
    known = hashlib.sha256(b"already in bento").hexdigest()
    api = FakeApi()
    api.on("POST", "/assets/lookup", lambda request: {"items": {known: {"asset": asset("asset_old", "existing.txt"), "path": "/Archivo/existing.txt"}} if known in body(request)["sha256"] else {}})
    ensured: list[str] = []

    def ensure(request: httpx.Request) -> Any:
        path = body(request)["path"]
        ensured.append(path)
        return {"folder": {**FOLDER, "id": "folder_" + path.replace("/", "_")}, "path": path, "created": []}

    api.on("POST", "/drive/folders/ensure", ensure)
    uploads: list[tuple[str, str]] = []

    def upload(request: httpx.Request) -> Any:
        text = request.content.decode("latin-1")
        name = text.split('filename="', 1)[1].split('"', 1)[0]
        folder = text.split('name="folder_id"', 1)[1].split("\r\n\r\n", 1)[1].split("\r\n", 1)[0]
        uploads.append((folder, name))
        return asset(f"asset_{name}", name)

    api.on("POST", "/assets/upload", upload)
    result = mock_cli(["upload", str(viaje), "--to", "/Fotos", "--json", "--jobs", "1"], api)
    assert result.code == 0, result.stderr
    summary = result.json
    assert (summary["uploaded"], summary["duplicates"], summary["failed"]) == (2, 1, 0)
    assert ensured == ["/Fotos/Viaje", "/Fotos/Viaje/Dia1"]
    assert sorted(uploads) == [("folder__Fotos_Viaje", "top.txt"), ("folder__Fotos_Viaje_Dia1", "new.txt")]
    duplicate = next(item for item in summary["items"] if item["status"] == "duplicate")
    assert duplicate["path"] == "/Archivo/existing.txt" and duplicate["asset"]["id"] == "asset_old"
    uploaded = {item["path"] for item in summary["items"] if item["status"] == "uploaded"}
    assert uploaded == {"/Fotos/Viaje/top.txt", "/Fotos/Viaje/Dia1/new.txt"}


def test_upload_retries_transient_failures_and_reports_partial(mock_cli: Callable[..., CliResult], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bento.interfaces.cli import transfer

    monkeypatch.setattr(transfer.time, "sleep", lambda _: None)
    (tmp_path / "ok.txt").write_text("ok")
    (tmp_path / "bad.txt").write_text("bad")
    api = FakeApi()
    api.on("POST", "/assets/lookup", {"items": {}})
    attempts: dict[str, int] = {}

    def upload(request: httpx.Request) -> Any:
        name = request.content.decode("latin-1").split('filename="', 1)[1].split('"', 1)[0]
        attempts[name] = attempts.get(name, 0) + 1
        if name == "ok.txt" and attempts[name] < 3:
            return error(503, "storage_unavailable")
        if name == "bad.txt":
            return error(415, "unsupported_media_type")
        return asset("asset_ok", name, folder_id=None)

    api.on("POST", "/assets/upload", upload)
    result = mock_cli(["upload", str(tmp_path / "ok.txt"), str(tmp_path / "bad.txt"), str(tmp_path / "missing.txt"), "--json"], api)
    assert result.code == 7
    statuses = {Path(item["local_path"]).name: item for item in result.json["items"]}
    assert statuses["ok.txt"]["status"] == "uploaded" and statuses["ok.txt"]["path"] == "/ok.txt"
    assert attempts == {"ok.txt": 3, "bad.txt": 1}
    assert statuses["bad.txt"]["error"]["code"] == "unsupported_media_type"
    assert statuses["missing.txt"]["error"]["code"] == "local_not_found"
    assert not api.calls("POST", "/drive/folders/ensure")  # root needs no ensure


def test_no_dedupe_skips_the_lookup_and_reports_api_duplicates(mock_cli: Callable[..., CliResult], tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a")
    api = FakeApi()
    api.on("POST", "/drive/folders/ensure", {"folder": FOLDER, "path": "/Fotos", "created": []})
    api.on("POST", "/assets/upload", asset("asset_a", "a.txt", duplicate=True, folder_id="folder_9"))
    api.on("POST", "/drive/paths", {"paths": {"asset_a": "/Otro/a.txt"}, "missing": []})
    result = mock_cli(["upload", str(tmp_path / "a.txt"), "--to", "/Fotos", "--no-dedupe", "--json"], api)
    assert result.code == 0
    assert not api.calls("POST", "/assets/lookup")
    item = result.json["items"][0]
    assert (item["status"], item["path"]) == ("duplicate", "/Otro/a.txt")


def test_download_never_overwrites(mock_cli: Callable[..., CliResult], tmp_path: Path) -> None:
    target = tmp_path / "out"
    target.mkdir()
    (target / "a.txt").write_text("local copy")
    api = FakeApi()
    api.on("GET", "/drive/resolve", {"kind": "asset", "path": "/a.txt", "folder": None, "asset": asset("asset_a", "a.txt"), "breadcrumbs": []})
    api.on("GET", "/assets/asset_a/download", lambda _r: httpx.Response(200, content=b"remote"))
    first = mock_cli(["download", "/a.txt", "--to", str(target), "--json"], api)
    assert first.code == 0 and first.json["skipped"] == 1
    assert (target / "a.txt").read_text() == "local copy"
    second = mock_cli(["download", "/a.txt", "--to", str(target), "--overwrite", "--json"], api)
    assert second.json["downloaded"] == 1 and (target / "a.txt").read_text() == "remote"


# Requests carry the right headers ------------------------------------------------------------


def test_requests_carry_token_and_client_header_and_verbose_redacts(mock_cli: Callable[..., CliResult]) -> None:
    api = FakeApi()
    api.on("GET", "/drive/items", {"items": [], "next_cursor": None, "breadcrumbs": []})
    result = mock_cli(["api", "GET", "/drive/items", "--query", "limit=5", "--verbose", "--json"], api, env={"BENTO_API_TOKEN": "s3cr3t-token-value"})
    assert result.code == 0
    request = api.requests[0]
    assert request.headers["authorization"] == "Bearer s3cr3t-token-value"
    assert request.headers["x-bento-client"] == "web"
    assert request.headers["user-agent"].startswith("bento-cli/")
    assert request.url.params["limit"] == "5"
    assert "s3cr3t" not in result.stderr and "[redacted]" in result.stderr


def test_flood_wait_exit_code(mock_cli: Callable[..., CliResult]) -> None:
    api = FakeApi()
    api.on("POST", "/sync/now", error(429, "telegram_flood_wait", retry_after_seconds=30))
    result = mock_cli(["sync", "now", "--json"], api)
    assert result.code == 8 and result.error["details"]["retry_after_seconds"] == 30


def test_unreachable_api_is_exit_5(cli_env: dict[str, str]) -> None:
    from tests.cli.conftest import invoke

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    result = invoke(["ls", "--json"], environ={**cli_env, "BENTO_API_URL": "http://127.0.0.1:9"}, transport=httpx.MockTransport(refuse))
    assert result.code == 5 and result.error["code"] == "bento_unreachable"


# Status and setup ----------------------------------------------------------------------------


def _status_api(vault_state: str, *, account_step: str = "authorized") -> FakeApi:
    api = FakeApi()
    api.on("GET", "/health", {"status": "ok", "storage_backend": "telegram", "telegram_configured": True})
    api.on("GET", "/version", {"name": "Bento", "version": "0.3.0", "environment": "local"})
    api.on("GET", "/account", {"step": account_step, "account": {"user_id": 1, "display_name": "Ana", "username": "ana", "phone_masked": "+57 ••• 12", "premium": False} if account_step == "authorized" else None, "qr_url": None, "qr": None, "qr_expires_at": None, "password_hint": None, "error": None})
    api.on("GET", "/vault", {"state": vault_state, "vault_id": None, "created_at": None, "recovery_kit_saved": False, "devices_count": 1, "usage": {"files": 0, "bytes": 0}, "other_vaults": 0})
    api.on("GET", "/sync/status", {"state": "idle", "pending_ops": 0, "last_push_at": None, "last_pull_at": None, "bootstrap": None, "waiting_until": None, "error": None})
    api.on("GET", "/activity", {"summary": "up_to_date", "uploads": {}, "downloads": {}, "attention": []})
    return api


@pytest.mark.parametrize(("state", "next_command"), [("no_vault", "bento setup"), ("locked", "bento join CODE"), ("signed_out", "bento setup")])
def test_status_exits_6_when_setup_is_required(mock_cli: Callable[..., CliResult], state: str, next_command: str) -> None:
    result = mock_cli(["status", "--json"], _status_api(state))
    assert result.code == 6
    assert result.json["setup"] == {"required": True, "reason": state, "next": next_command}
    human = mock_cli(["status", "--lang", "es"], _status_api(state))
    assert human.code == 6 and "Siguiente paso" in human.stdout


def test_status_ready(mock_cli: Callable[..., CliResult]) -> None:
    result = mock_cli(["status", "--lang", "en"], _status_api("ready"))
    assert result.code == 0
    assert "Ana (@ana)" in result.stdout and "Everything is up to date." in result.stdout


def test_setup_without_tty_returns_step_and_next(mock_cli: Callable[..., CliResult]) -> None:
    result = mock_cli(["setup", "--json"], _status_api("locked"))
    assert result.code == 0
    assert result.json["step"] == "join_vault" and result.json["complete"] is False
    assert "bento join CODE" in result.json["next"]
    assert mock_cli(["setup", "--json"], _status_api("no_vault")).json["next"] == ["bento vault create"]
    assert mock_cli(["setup", "--json"], _status_api("signed_out")).json["step"] == "telegram_login"


def test_setup_unlocks_with_the_recovery_code(mock_cli: Callable[..., CliResult]) -> None:
    api = _status_api("locked")
    ready = {"state": "ready", "vault_id": "vlt_1", "created_at": None, "recovery_kit_saved": True, "devices_count": 2, "usage": {"files": 3, "bytes": 10}, "other_vaults": 0}
    api.on("GET", "/vault", api.routes[("GET", "/vault")][0], lambda _r: ready)
    api.on("POST", "/vault/unlock", ready)
    result = mock_cli(["setup", "--recovery-code", "AAAA-BBBB-CCCC", "--json"], api)
    assert result.code == 0 and result.json["complete"] is True and result.json["done"] == ["unlocked"]
    assert body(api.calls("POST", "/vault/unlock")[0]) == {"recovery_code": "AAAA-BBBB-CCCC"}


def test_setup_local_storage_is_already_complete(mock_cli: Callable[..., CliResult]) -> None:
    api = _status_api("local_only")
    api.on("GET", "/health", {"status": "ok", "storage_backend": "local", "telegram_configured": False})
    result = mock_cli(["setup", "--json"], api)
    assert result.json["step"] == "local_only" and result.json["complete"] is True


# Login ---------------------------------------------------------------------------------------


def _account(step: str, **extra: Any) -> dict[str, Any]:
    return {"step": step, "account": None, "qr_url": None, "qr": None, "qr_expires_at": None, "password_hint": None, "error": None, **extra}


def test_qr_login_refreshes_an_expired_code_and_waits(mock_cli: Callable[..., CliResult]) -> None:
    qr = {"size": 1, "rows": ["1"]}
    api = FakeApi()
    api.on(
        "GET",
        "/account",
        _account("signed_out"),
        _account("qr_pending", qr_url="tg://login?token=a", qr=qr, qr_expires_at="2000-01-01T00:00:00+00:00"),
        _account("authorized", account={"user_id": 1, "display_name": "Ana", "username": None, "phone_masked": None, "premium": False}),
    )
    api.on(
        "POST",
        "/account/login/qr",
        _account("qr_pending", qr_url="tg://login?token=a", qr=qr, qr_expires_at="2999-01-01T00:00:00+00:00"),
        _account("qr_pending", qr_url="tg://login?token=b", qr=qr, qr_expires_at="2999-01-01T00:00:00+00:00"),
    )
    result = mock_cli(["login", "--json"], api)
    assert result.code == 0, result.stderr
    assert result.json["step"] == "authorized"
    assert len(api.calls("POST", "/account/login/qr")) == 2  # refreshed once


def test_phone_login_with_code_and_password_from_stdin(mock_cli: Callable[..., CliResult]) -> None:
    api = FakeApi()
    api.on("GET", "/account", _account("signed_out"))
    api.on("POST", "/account/login/phone", _account("code_required"))
    api.on("POST", "/account/login/code", _account("password_required", password_hint="gato"))
    api.on("POST", "/account/login/password", _account("authorized", account={"user_id": 1, "display_name": "Ana", "username": None, "phone_masked": None, "premium": False}))
    result = mock_cli(["login", "--phone", "+573001112233", "--code", "12345", "--password-stdin", "--json"], api, stdin="hunter2\n")
    assert result.code == 0
    assert body(api.calls("POST", "/account/login/password")[0]) == {"password": "hunter2"}
    assert "hunter2" not in result.stdout + result.stderr


def test_phone_login_without_code_off_a_tty_is_a_usage_error(mock_cli: Callable[..., CliResult]) -> None:
    api = FakeApi()
    api.on("GET", "/account", _account("signed_out"))
    api.on("POST", "/account/login/phone", _account("code_required"))
    result = mock_cli(["login", "--phone", "+573001112233", "--json"], api)
    assert result.code == 2 and result.error["details"]["flag"] == "--code"
    resume = FakeApi()
    resume.on("GET", "/account", _account("code_required"))
    resume.on("POST", "/account/login/code", _account("authorized", account={"user_id": 1, "display_name": "Ana", "username": None, "phone_masked": None, "premium": False}))
    assert mock_cli(["login", "--code", "12345", "--json"], resume).code == 0


def test_login_failure_maps_the_error(mock_cli: Callable[..., CliResult]) -> None:
    api = FakeApi()
    api.on("GET", "/account", _account("signed_out"))
    api.on("POST", "/account/login/phone", _account("code_required"))
    api.on("POST", "/account/login/code", _account("failed", error={"code": "telegram_code_invalid", "message": "bad", "details": {}}))
    result = mock_cli(["login", "--phone", "+1", "--code", "1", "--json"], api)
    assert result.error["code"] == "telegram_code_invalid"


# Pairing -------------------------------------------------------------------------------------


def _pairing(state: str, **extra: Any) -> dict[str, Any]:
    return {"id": "pair_1", "role": "host", "transport": "relay", "state": state, "code": "K7Q2-MXR9-T4WA", "link": "bento://join?v=1&c=K7Q2-MXR9-T4WA", "web_link": None, "qr": {"size": 1, "rows": ["1"]}, "expires_at": "2999-01-01T00:00:00+00:00", "peer": None, "sas": None, "telegram_qr": None, "error": None, "vault": None, **extra}


def test_pair_approve_flow_prints_sas_and_approves(mock_cli: Callable[..., CliResult]) -> None:
    api = FakeApi()
    api.on("POST", "/pairing/host", _pairing("waiting"))
    peer = {"device_name": "Servidor", "platform": "linux"}
    api.on("GET", "/pairing/pair_1", _pairing("connected"), _pairing("awaiting_approval", peer=peer, sas=["🐙", "🌵", "🎈", "🚀"]), _pairing("completed", peer=peer))
    api.on("POST", "/pairing/pair_1/approve", _pairing("approving", peer=peer))
    result = mock_cli(["pair", "--approve", "--lang", "es"], api)
    assert result.code == 0, result.stderr
    assert "K7Q2-MXR9-T4WA" in result.stdout and "bento join K7Q2-MXR9-T4WA" in result.stdout
    assert "🐙   🌵   🎈   🚀" in result.stderr
    assert "«Servidor» ya tiene acceso" in result.stdout
    assert len(api.calls("POST", "/pairing/pair_1/approve")) == 1


def test_pair_wait_off_a_tty_asks_for_explicit_approval(mock_cli: Callable[..., CliResult]) -> None:
    api = FakeApi()
    api.on("POST", "/pairing/host", _pairing("waiting"))
    api.on("GET", "/pairing/pair_1", _pairing("awaiting_approval", peer={"device_name": "X", "platform": "linux"}, sas=["🐙", "🌵", "🎈", "🚀"]))
    result = mock_cli(["pair", "--wait", "--json"], api)
    assert result.code == 2
    assert result.error["code"] == "confirmation_required"
    assert result.error["details"]["next"] == "bento pair approve pair_1"
    assert not api.calls("POST", "/pairing/pair_1/approve")


def test_join_shows_sas_telegram_qr_and_completes(mock_cli: Callable[..., CliResult]) -> None:
    api = FakeApi()
    guest = {"role": "guest", "code": None, "link": None, "qr": None}
    api.on("POST", "/pairing/join", _pairing("connected", **guest))
    api.on(
        "GET",
        "/pairing/pair_1",
        _pairing("awaiting_approval", sas=["🐙", "🌵", "🎈", "🚀"], **guest),
        _pairing("needs_telegram_login", telegram_qr={"size": 1, "rows": ["1"]}, **guest),
        _pairing("bootstrapping", **guest),
        _pairing("completed", **guest),
    )
    api.on("GET", "/sync/status", {"state": "bootstrapping", "bootstrap": {"done": 3, "total": 10}})
    result = mock_cli(["join", "K7Q2-MXR9-T4WA", "--lang", "es"], api)
    assert result.code == 0, result.stderr
    assert body(api.calls("POST", "/pairing/join")[0]) == {"code": "K7Q2-MXR9-T4WA"}
    assert "Confirma en tu otro dispositivo" in result.stderr
    assert "Escanea con Telegram" in result.stdout
    assert "3/10" in result.stderr
    assert "Este dispositivo ya está en tu nube" in result.stdout


def test_join_failure_exit_code(mock_cli: Callable[..., CliResult]) -> None:
    api = FakeApi()
    api.on("POST", "/pairing/join", _pairing("connected"))
    api.on("GET", "/pairing/pair_1", _pairing("rejected", error={"code": "pairing_rejected", "message": "no"}))
    result = mock_cli(["join", "K7Q2-MXR9-T4WA", "--json"], api)
    assert result.code == 4 and result.error["code"] == "pairing_rejected"


# Confirmations -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["trash", "empty"],
        ["trash", "purge", "id:asset_1"],
        ["devices", "remove", "dev_2"],
        ["vault", "recovery", "rotate"],
        ["share", "/a.jpg", "--chat", "5"],
        ["logout"],
    ],
)
def test_irreversible_commands_need_yes_off_a_tty(mock_cli: Callable[..., CliResult], args: list[str]) -> None:
    api = FakeApi()
    api.on("GET", "/devices/dev_2/removal-preview", {"recipients": []})
    api.on("GET", "/drive/resolve", {"kind": "asset", "path": "/a.jpg", "folder": None, "asset": asset("asset_1", "a.jpg"), "breadcrumbs": []})
    result = mock_cli([*args, "--json"], api)
    assert result.code == 2 and result.error["code"] == "confirmation_required"
    assert not [request for request in api.requests if request.method in {"POST", "DELETE"}]


def test_devices_remove_with_yes_prints_the_new_recovery_code(mock_cli: Callable[..., CliResult]) -> None:
    api = FakeApi()
    api.on("GET", "/devices/dev_2/removal-preview", {"recipients": [{"id": "dev_1", "name": "Este", "needs_review": False}]})
    api.on("DELETE", "/devices/dev_2", {"device": {"id": "dev_2"}, "telegram_session_closed": True, "recovery_code": "NEW1-NEW2", "recovery_qr": {"size": 1, "rows": ["1"]}, "removed_device_ids": ["dev_2", "dev_3"]})
    result = mock_cli(["devices", "remove", "id:dev_2", "--exclude", "dev_3", "--yes", "--lang", "es"], api)
    assert result.code == 0
    assert body(api.calls("DELETE", "/devices/dev_2")[0]) == {"exclude_device_ids": ["dev_3"]}
    assert "NEW1-NEW2" in result.stdout and "Dispositivos eliminados: 2" in result.stdout


# Settings, backup, trash ---------------------------------------------------------------------


def test_settings_set_validates_then_patches_with_revision(mock_cli: Callable[..., CliResult]) -> None:
    api = FakeApi()
    api.on("GET", "/settings/schema", {"revision": 3, "fields": [{"key": "worker_concurrency", "type": "integer", "secret": False}, {"key": "telegram_api_hash", "type": "secret", "secret": True}]})
    api.on("POST", "/settings/validate", {"valid": True, "errors": [], "warnings": [], "probes": [], "restart_plan": {"mode": "x", "affected_keys": [], "services": ["worker"]}})
    api.on("GET", "/settings/values", {"revision": 3, "values": {}})
    api.on("PATCH", "/settings/values", {"revision": 4, "values": {}, "restart_plan": {"mode": "x", "affected_keys": [], "services": ["worker"]}})
    result = mock_cli(["settings", "set", "worker_concurrency=2", "--json"], api)
    assert result.code == 0
    assert body(api.calls("POST", "/settings/validate")[0]) == {"values": {"worker_concurrency": 2}}
    assert body(api.calls("PATCH", "/settings/values")[0]) == {"values": {"worker_concurrency": 2}, "revision": 3}
    assert mock_cli(["settings", "set", "telegram_api_hash=x", "--json"], api).code == 2
    assert mock_cli(["settings", "set", "nope=1", "--json"], api).code == 3

    invalid = FakeApi()
    invalid.on("GET", "/settings/schema", api.routes[("GET", "/settings/schema")][0])
    invalid.on("POST", "/settings/validate", {"valid": False, "errors": [{"key": "worker_concurrency", "code": "out_of_range", "message": "x"}], "warnings": []})
    rejected = mock_cli(["settings", "set", "worker_concurrency=99", "--json"], invalid)
    assert rejected.code == 2 and rejected.error["details"]["errors"][0]["code"] == "out_of_range"
    assert not invalid.calls("PATCH", "/settings/values")


def test_backup_add_is_idempotent(mock_cli: Callable[..., CliResult], tmp_path: Path) -> None:
    source = {"id": "src_1", "path": str(tmp_path.resolve()), "label": "Docs", "enabled": True, "state": "idle", "files_total": 0, "files_done": 0, "files_pending": 0, "bytes_pending": 0, "last_scan_at": None, "error": None}
    api = FakeApi()
    api.on("GET", "/backup/sources", {"items": [source]})
    result = mock_cli(["backup", "add", str(tmp_path), "--json"], api)
    assert result.code == 0 and result.json["existing"] is True
    assert not api.calls("POST", "/backup/sources")


def test_trash_restore_by_ambiguous_name_lists_candidates(mock_cli: Callable[..., CliResult]) -> None:
    api = FakeApi()
    entry = {"type": "asset", "name": "a.txt", "size_bytes": 1, "deleted_at": "2024-01-01T00:00:00+00:00", "purge_at": "2024-02-01T00:00:00+00:00", "thumbnail_url": None}
    api.on("GET", "/trash", {"items": [{**entry, "id": "asset_1"}, {**entry, "id": "asset_2"}], "next_cursor": None})
    result = mock_cli(["trash", "restore", "a.txt", "--json"], api)
    assert result.code == 4 and len(result.error["details"]["candidates"]) == 2
    api.on("POST", "/trash/restore", {"restored": 1})
    assert mock_cli(["trash", "restore", "id:asset_2", "--json"], api).json == {"restored": 1, "ids": ["asset_2"]}


def test_find_adds_paths(mock_cli: Callable[..., CliResult]) -> None:
    api = FakeApi()
    api.on("GET", "/search", {"items": [{"id": "hit_1", "type": "document", "asset_id": "asset_1", "title": "luz.pdf", "subtitle": None, "thumbnail_url": None, "score": 1.0, "reason": "name", "processing_state": "indexed"}], "facets": [], "next_cursor": None})
    api.on("POST", "/drive/paths", {"paths": {"asset_1": "/Documentos/luz.pdf"}, "missing": []})
    result = mock_cli(["find", "luz", "--json"], api)
    assert result.json["items"][0]["path"] == "/Documentos/luz.pdf"
    assert api.calls("GET", "/search")[0].url.params["q"] == "luz"
