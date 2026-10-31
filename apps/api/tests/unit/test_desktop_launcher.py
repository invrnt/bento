from __future__ import annotations

import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from bento.infrastructure import process_secrets
from bento.infrastructure.settings import Settings
from bento.interfaces.desktop import launcher


def test_runtime_probe_is_machine_readable_and_secret_free(monkeypatch, capsys, tmp_path) -> None:
    secret = "must-not-appear"
    monkeypatch.setattr(
        launcher,
        "get_settings",
        lambda: Settings(data_dir=str(tmp_path), telegram_api_hash=secret),
    )

    exit_code = launcher.main(("probe", "runtime"))

    output = capsys.readouterr().out
    assert exit_code == 0
    assert json.loads(output) == {"probe": "runtime", "status": "ok", "version": "0.1.0"}
    assert secret not in output
    assert str(tmp_path) not in output


def test_writable_directory_probe_rejects_filesystem_root(monkeypatch, capsys) -> None:
    monkeypatch.setattr(launcher, "get_settings", lambda: Settings())

    exit_code = launcher.main(("probe", "writable-directory", "--path", "/"))

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out) == {
        "code": "unsafe_path",
        "probe": "writable-directory",
        "status": "failed",
    }


def test_migrate_command_upgrades_the_configured_database(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(launcher, "get_settings", lambda: Settings(data_dir=str(data_dir)))

    assert launcher.main(("migrate",)) == 0

    with sqlite3.connect(data_dir / "db" / "bento.sqlite3") as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() is not None


def test_desktop_api_command_rejects_non_loopback_bind(monkeypatch) -> None:
    monkeypatch.setattr(
        launcher,
        "get_settings",
        lambda: Settings(runtime_mode="desktop", host="0.0.0.0"),
    )

    with pytest.raises(SystemExit, match="loopback"):
        launcher.main(("api",))


@pytest.fixture
def _clean_holder():
    process_secrets.clear()
    yield
    process_secrets.clear()


def test_every_sidecar_command_moves_desktop_secrets_out_of_the_environment(monkeypatch, capsys, tmp_path, _clean_holder) -> None:
    monkeypatch.setattr(launcher, "get_settings", lambda: Settings(data_dir=str(tmp_path)))
    monkeypatch.setenv("BENTO_DESKTOP_API_TOKEN", "per-launch-token-with-more-than-32-chars")
    monkeypatch.setenv("BENTO_DEVICE_WRAPPING_KEY", "AAAA")

    assert launcher.main(("probe", "runtime")) == 0

    capsys.readouterr()
    assert "BENTO_DESKTOP_API_TOKEN" not in os.environ
    assert "BENTO_DEVICE_WRAPPING_KEY" not in os.environ
    assert process_secrets.get("BENTO_DESKTOP_API_TOKEN") == "per-launch-token-with-more-than-32-chars"
    assert process_secrets.get("BENTO_DEVICE_WRAPPING_KEY") == "AAAA"


def test_desktop_api_refuses_a_caller_chosen_port(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "get_settings", lambda: Settings(runtime_mode="desktop", host="127.0.0.1"))

    with pytest.raises(SystemExit, match="ephemeral port"):
        launcher.main(("api", "--port", "43127"))


def test_loopback_listener_is_bound_by_this_process_on_an_os_assigned_port() -> None:
    listener = launcher.bind_loopback_listener("127.0.0.1")
    try:
        host, port = listener.getsockname()[:2]
        assert host == "127.0.0.1"
        assert 0 < port <= 65535
        # Already listening: a client can connect before uvicorn starts accepting.
        with socket.create_connection((host, port), timeout=2):
            pass
    finally:
        listener.close()
    for host in ("0.0.0.0", "localhost", "::"):
        with pytest.raises(ValueError):
            launcher.bind_loopback_listener(host)


def test_readiness_announcement_is_one_structured_line() -> None:
    stream = io.StringIO()

    launcher.announce_ready(43127, stream)

    assert stream.getvalue() == 'BENTO_API_READY {"port":43127}\n'


def test_desktop_api_sidecar_reports_the_port_it_bound_and_requires_the_token(tmp_path) -> None:
    data_dir = tmp_path / "data"
    token = "sidecar-test-token-" + "x" * 32
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "BENTO_RUNTIME_MODE": "desktop",
        "HOST": "127.0.0.1",
        "DATA_DIR": str(data_dir),
        "BENTO_DESKTOP_ORIGIN": "bento://app",
        "BENTO_DESKTOP_API_TOKEN": token,
        "PYTHONPATH": os.pathsep.join(sys.path),
    }
    command = [sys.executable, "-m", "bento.interfaces.desktop"]
    subprocess.run([*command, "migrate"], env=environment, cwd=tmp_path, check=True, capture_output=True, timeout=120)
    api = subprocess.Popen(
        [*command, "api"],
        env=environment,
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert api.stdout is not None
        line = ""
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            line = api.stdout.readline()
            if not line or line.startswith(launcher.READY_PREFIX):
                break
        assert line.startswith(launcher.READY_PREFIX), "the API never announced readiness"
        port = json.loads(line.removeprefix(launcher.READY_PREFIX))["port"]
        base = f"http://127.0.0.1:{port}/api/desktop/readiness"

        assert httpx.get(base, headers={"Origin": "bento://app"}).status_code == 401
        ready = httpx.get(base, headers={"Origin": "bento://app", "Authorization": f"Bearer {token}"})
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"
        if sys.platform == "linux":
            # The token was only ever in the initial environment block, never in argv.
            assert token not in Path(f"/proc/{api.pid}/cmdline").read_text()
    finally:
        api.terminate()
        try:
            api.wait(timeout=15)
        except subprocess.TimeoutExpired:
            api.kill()
            api.wait()


def test_desktop_api_startup_failure_announces_nothing_and_fails_the_process(capsys) -> None:
    async def failing_app(scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            await receive()
            await send({"type": "lifespan.startup.failed", "message": "boom"})

    with pytest.raises(SystemExit) as exited:
        launcher._serve_desktop_api(failing_app, "127.0.0.1")

    assert exited.value.code == 3
    assert launcher.READY_PREFIX not in capsys.readouterr().out
