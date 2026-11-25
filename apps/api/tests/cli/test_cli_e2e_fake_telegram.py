"""End-to-end CLI journey on the fake Telegram cloud with two profile daemons (two Bento devices).

setup/status/login → vault create (recovery code once) → upload → second profile signs in, is `locked`,
joins with the pairing code shown by the first (relay double) → it sees the first device's files.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from tests.cli.conftest import CliResult, invoke
from tests.cli.test_cli_daemon import base_environ


def wait_for(probe, timeout: float = 90.0, interval: float = 0.5):  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = probe()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"timed out; last={last!r}")


def test_two_devices_setup_pair_by_code_and_share_files(tmp_path: Path) -> None:
    pytest.importorskip("websockets")
    from tests.integration.pairing.relay_double import relay_in_thread

    with relay_in_thread() as relay:
        environ = base_environ(
            tmp_path,
            STORAGE_BACKEND="fake",
            ENVIRONMENT="local",
            BENTO_FAKE_TELEGRAM_DIR=str(tmp_path / "cloud"),
            BENTO_RELAY_URL=relay.url,
        )

        def cli(profile: str, *args: str) -> CliResult:
            return invoke(["--profile", profile, *args, "--json", "--timeout", "90"], environ=environ)

        try:
            # Device A: first contact auto-starts the daemon and reports what is missing.
            first = cli("laptop", "status")
            assert first.code == 6, first.stderr
            assert first.json["setup"]["reason"] == "signed_out"
            plan = cli("laptop", "setup")
            assert plan.code == 0 and plan.json["step"] == "telegram_login"

            login = cli("laptop", "login")  # the fake phone approves the QR after ~2 s
            assert login.code == 0, login.stderr
            assert login.json["step"] == "authorized"
            assert cli("laptop", "status").json["setup"]["reason"] == "no_vault"

            created = cli("laptop", "vault", "create")
            assert created.code == 0, created.stderr
            assert created.json["recovery_code"]
            assert cli("laptop", "status").code == 0

            document = tmp_path / "factura.txt"
            document.write_text("factura de agua")
            uploaded = cli("laptop", "upload", str(document), "--to", "/Documentos")
            assert uploaded.code == 0 and uploaded.json["uploaded"] == 1, uploaded.stdout + uploaded.stderr

            # Device B: signs in to the same account, the vault exists but B has no keys yet.
            assert cli("desktop", "login").code == 0
            locked = cli("desktop", "status")
            assert locked.code == 6 and locked.json["setup"]["reason"] == "locked"
            assert cli("desktop", "setup").json["step"] == "join_vault"

            host = cli("laptop", "pair")
            assert host.code == 0, host.stderr
            code, pairing_id = host.json["code"], host.json["id"]
            joined: dict[str, CliResult] = {}
            guest = threading.Thread(target=lambda: joined.setdefault("result", cli("desktop", "join", code)))
            guest.start()
            waiting = wait_for(lambda: (lambda state: state if state.json.get("state") == "awaiting_approval" else None)(cli("laptop", "pair", "status", pairing_id)))
            assert len(waiting.json["sas"]) == 4
            approved = cli("laptop", "pair", "approve", pairing_id)
            assert approved.code == 0, approved.stderr
            guest.join(timeout=120)
            result = joined["result"]
            assert result.code == 0, result.stdout + result.stderr
            assert result.json["state"] == "completed"

            # B now sees A's file through the encrypted sync log.
            wait_for(lambda: cli("desktop", "status").code == 0)

            def synced() -> bool:
                cli("desktop", "sync", "now")
                listing = cli("desktop", "ls", "/Documentos")
                return listing.code == 0 and [item["name"] for item in listing.json["items"]] == ["factura.txt"]

            wait_for(synced)
        finally:
            for profile in ("laptop", "desktop"):
                invoke(["--profile", profile, "daemon", "stop", "--json"], environ=environ)
