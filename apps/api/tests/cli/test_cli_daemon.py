"""The profile daemon as real processes: `daemon run` supervisor, `daemon start/stop`, the PID lock."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from bento.interfaces.cli.daemon import daemon_environment, is_desktop_data_dir, service_file, stop_daemon
from bento.interfaces.cli.errors import CliError
from bento.interfaces.cli.profiles import Profile, read_endpoint
from tests.cli.conftest import invoke

_SETTING_ENV = {"DATA_DIR", "API_PORT", "HOST", "STORAGE_BACKEND", "ENVIRONMENT", "BENTO_RUNTIME_MODE"}


def base_environ(tmp_path: Path, **values: str) -> dict[str, str]:
    environ = {key: value for key, value in os.environ.items() if not key.startswith("BENTO_") and key not in _SETTING_ENV}
    environ.update(
        {
            "BENTO_HOME": str(tmp_path / "home"),
            "BENTO_DESKTOP_USER_DATA": str(tmp_path / "no-desktop"),
            "BENTO_LANG": "en",
            "STORAGE_BACKEND": "local",
            "OCR_PROVIDER": "disabled",
            "EMBEDDINGS_PROVIDER": "disabled",
            **values,
        }
    )
    return environ


def wait_for(probe, timeout: float = 60.0):  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = probe()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError("timed out")


def test_daemon_run_writes_the_endpoint_serves_with_token_and_cleans_up(tmp_path: Path) -> None:
    environ = base_environ(tmp_path)
    profile = Profile.load("default", tmp_path / "home")
    supervisor = subprocess.Popen(
        [sys.executable, "-m", "bento.interfaces.cli", "daemon", "run"],
        env=environ,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        endpoint = wait_for(lambda: read_endpoint(profile.endpoint_file))
        assert endpoint.kind == "daemon" and endpoint.pid == supervisor.pid and endpoint.token
        assert len(endpoint.token) >= 32
        if os.name == "posix":
            assert (profile.endpoint_file.stat().st_mode & 0o777) == 0o600
        health = httpx.get(endpoint.url + "/api/health", headers={"Authorization": f"Bearer {endpoint.token}"}, timeout=5)
        assert health.status_code == 200 and health.json()["storage_backend"] == "local"
        # The token never reaches the logs.
        logs = "".join(path.read_text(errors="replace") for path in profile.logs_dir.glob("*.log"))
        assert endpoint.token not in logs

        second = subprocess.run(
            [sys.executable, "-m", "bento.interfaces.cli", "daemon", "run", "--json"],
            env=environ,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert second.returncode == 4 and "daemon_already_running" in second.stderr

        status = invoke(["daemon", "status", "--json"], environ=environ)
        assert status.json["running"] is True and status.json["healthy"] is True
        # Authenticated requests through the endpoint file (`trash` exists on every backend version).
        listing = invoke(["trash", "--json"], environ=environ)
        assert listing.code == 0 and listing.json["items"] == []
    finally:
        stopped = stop_daemon(profile, timeout=30)
        supervisor.wait(timeout=30)
    assert stopped is True
    assert supervisor.returncode == 0
    assert not profile.endpoint_file.exists() and not profile.pid_file.exists()


def test_daemon_start_auto_start_and_stop(tmp_path: Path) -> None:
    environ = base_environ(tmp_path)
    no_start = invoke(["--profile", "work", "ls", "--no-start", "--json"], environ=environ)
    assert no_start.code == 5 and no_start.error["code"] == "daemon_not_running"
    try:
        # Any command starts the profile daemon when nothing is running.
        made = invoke(["--profile", "work", "mkdir", "-p", "/Fotos", "--json"], environ=environ)
        assert made.code in {0, 1}, made.stderr  # 1 only if the CLI-support endpoints are missing
        status = invoke(["--profile", "work", "status", "--json"], environ=environ)
        assert status.code == 0, status.stderr
        assert status.json["target"]["kind"] == "daemon" and status.json["target"]["profile"] == "work"
        again = invoke(["--profile", "work", "daemon", "start", "--json"], environ=environ)
        assert again.code == 0 and again.json["running"] is True
    finally:
        stop = invoke(["--profile", "work", "daemon", "stop", "--json"], environ=environ)
    assert stop.code == 0 and stop.json["stopped"] is True
    assert invoke(["--profile", "work", "daemon", "status", "--json"], environ=environ).json["running"] is False
    assert invoke(["--profile", "work", "daemon", "stop", "--json"], environ=environ).json["stopped"] is False


def test_daemon_refuses_the_desktop_data_directory(tmp_path: Path) -> None:
    desktop = tmp_path / "Bento"
    (desktop / "bento-desktop").mkdir(parents=True)
    (desktop / "bento-desktop" / "bootstrap.json").write_text("{}")
    assert is_desktop_data_dir(desktop / "bento-data", {"BENTO_DESKTOP_USER_DATA": str(desktop)})
    assert is_desktop_data_dir(tmp_path / "other", {"BENTO_DESKTOP_USER_DATA": str(desktop)}) is False
    marked = tmp_path / "marked"
    marked.mkdir()
    (marked / "bootstrap.json").write_text("{}")
    assert is_desktop_data_dir(marked, {})


def test_daemon_environment_is_headless_and_strips_foreign_secrets(tmp_path: Path) -> None:
    profile = Profile.load("default", tmp_path)
    env = daemon_environment(profile, {"BENTO_DESKTOP_CLI_TOKEN": "x" * 40, "BENTO_API_TOKEN": "y" * 40, "BENTO_DEVICE_WRAPPING_KEY": "k", "PATH": "/bin"})
    assert env["DATA_DIR"] == str(profile.data_dir)
    assert env["BENTO_RUNTIME_MODE"] == "headless" and env["HOST"] == "127.0.0.1"
    assert env["STORAGE_BACKEND"] == "telegram"
    assert not {"BENTO_DESKTOP_CLI_TOKEN", "BENTO_API_TOKEN", "BENTO_DEVICE_WRAPPING_KEY"} & set(env)
    assert daemon_environment(profile, {"STORAGE_BACKEND": "fake"})["STORAGE_BACKEND"] == "fake"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="systemd unit on Linux")
def test_systemd_user_unit(tmp_path: Path) -> None:
    service = service_file(Profile.load("work", tmp_path), {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "BENTO_HOME": str(tmp_path)})
    assert service.path == tmp_path / "cfg" / "systemd" / "user" / "bento@work.service"
    assert "daemon run --profile work" in service.content
    assert f"Environment=BENTO_HOME={tmp_path}" in service.content
    assert "systemctl --user enable --now bento@work.service" in service.commands
    assert "loginctl enable-linger $USER" in service.commands
    default = service_file(Profile.load("default", tmp_path), {"XDG_CONFIG_HOME": str(tmp_path / "cfg")})
    assert default.path.name == "bento.service"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="writes under XDG_CONFIG_HOME only on Linux")
def test_service_install_and_uninstall_commands(tmp_path: Path) -> None:
    environ = base_environ(tmp_path, XDG_CONFIG_HOME=str(tmp_path / "cfg"))
    installed = invoke(["daemon", "install-service", "--json"], environ=environ)
    assert installed.code == 0
    assert Path(installed.json["path"]).is_file()
    removed = invoke(["daemon", "uninstall-service", "--json"], environ=environ)
    assert removed.json["removed"] is True and not Path(installed.json["path"]).exists()


def test_service_file_rejects_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from bento.interfaces.cli import daemon

    monkeypatch.setattr(daemon.sys, "platform", "win32")
    with pytest.raises(CliError) as caught:
        daemon.service_file(Profile.load("default", tmp_path), {})
    assert caught.value.code == "service_not_supported"
