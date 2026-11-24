"""The guided flows on a (simulated) terminal: prompts, confirmations, recovery kit, backups."""

from __future__ import annotations

import io
from typing import Any

import httpx
import pytest

from bento.interfaces.cli.app import run
from bento.interfaces.cli.commands import pairing as pairing_module
from tests.cli.test_cli_mock_flows import FakeApi, _pairing, _status_api, body


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def run_tty(args: list[str], api: FakeApi, answers: str, cli_env: dict[str, str]) -> tuple[int, str, str]:
    stdout, stderr = Tty(), Tty()
    code = run(
        [*args, "--lang", "es"],
        stdout=stdout,
        stderr=stderr,
        stdin=Tty(answers),
        environ={**cli_env, "BENTO_API_URL": "http://127.0.0.1:9", "NO_COLOR": "1"},
        transport=httpx.MockTransport(api),
    )
    return code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture(autouse=True)
def _fast_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pairing_module, "POLL_SECONDS", 0.0)


READY = {"state": "ready", "vault_id": "vlt_1", "created_at": None, "recovery_kit_saved": True, "devices_count": 1, "usage": {"files": 0, "bytes": 0}, "other_vaults": 0}


def test_setup_creates_the_vault_confirms_the_kit_and_offers_backups(cli_env: dict[str, str]) -> None:
    api = _status_api("no_vault")
    api.on("GET", "/vault", api.routes[("GET", "/vault")][0], lambda _r: READY)
    api.on("POST", "/vault", {"vault": {**READY, "recovery_kit_saved": False}, "recovery_code": "ABCD-EFGH-JKLM", "recovery_qr": {"size": 1, "rows": ["1"]}})
    api.on("POST", "/vault/recovery-code/confirm", READY)
    api.on("GET", "/backup/sources", {"items": []})
    api.on("GET", "/backup/suggestions", {"items": [{"path": "/home/ana/Imágenes", "label": "Imágenes", "kind": "pictures"}, {"path": "/home/ana/Descargas", "label": "Descargas", "kind": "downloads"}]})
    api.on("POST", "/backup/sources", lambda request: {"id": "src_1", **body(request)})
    # create? (Enter = yes) · last group: wrong, then right · back up Imágenes: s · Descargas: n
    code, stdout, stderr = run_tty(["setup"], api, "\nXXXX\njklm\ns\nn\n", cli_env)
    assert code == 0, stderr
    assert "ABCD-EFGH-JKLM" in stdout and "no se volverá a mostrar" in stdout
    assert "No coincide" in stderr
    assert body(api.calls("POST", "/vault/recovery-code/confirm")[0]) == {"last_group": "JKLM"}
    assert [body(request) for request in api.calls("POST", "/backup/sources")] == [{"path": "/home/ana/Imágenes", "label": "Imágenes"}]
    assert "Tu nube Bento está lista" in stdout


def test_setup_on_a_locked_device_joins_with_a_typed_code(cli_env: dict[str, str]) -> None:
    api = _status_api("locked")
    locked = api.routes[("GET", "/vault")][0]
    api.on("GET", "/vault", locked, locked, lambda _r: READY)
    guest: dict[str, Any] = {"role": "guest", "code": None, "link": None, "qr": None}
    api.on("POST", "/pairing/join", _pairing("connected", **guest))
    api.on("GET", "/pairing/pair_1", _pairing("completed", **guest))
    api.on("GET", "/backup/sources", {"items": []})
    api.on("GET", "/backup/suggestions", {"items": []})
    code, stdout, stderr = run_tty(["setup"], api, "4\n1\nK7Q2-MXR9-T4WA\n", cli_env)
    assert code == 0, stderr
    assert "1) Tengo un código" in stdout
    assert body(api.calls("POST", "/pairing/join")[0]) == {"code": "K7Q2-MXR9-T4WA"}


def test_host_rejects_when_the_emojis_do_not_match(cli_env: dict[str, str]) -> None:
    api = FakeApi()
    api.on("POST", "/pairing/host", _pairing("waiting"))
    api.on("GET", "/pairing/pair_1", _pairing("awaiting_approval", peer={"device_name": "Raro", "platform": "linux"}, sas=["🐙", "🌵", "🎈", "🚀"]))
    api.on("POST", "/pairing/pair_1/reject", _pairing("rejected", error={"code": "pairing_rejected", "message": "rejected"}))
    code, stdout, stderr = run_tty(["pair", "--wait"], api, "n\n", cli_env)
    assert code == 4
    assert "¿Coinciden los emojis?" in stderr
    assert not api.calls("POST", "/pairing/pair_1/approve")


def test_trash_empty_asks_on_a_terminal(cli_env: dict[str, str]) -> None:
    api = FakeApi()
    api.on("POST", "/trash/empty", {"purged": 3, "deferred": []})
    declined, _, _ = run_tty(["trash", "empty"], api, "\n", cli_env)
    assert declined == 1 and not api.calls("POST", "/trash/empty")
    accepted, stdout, _ = run_tty(["trash", "empty"], api, "s\n", cli_env)
    assert accepted == 0 and "Eliminados para siempre: 3" in stdout
