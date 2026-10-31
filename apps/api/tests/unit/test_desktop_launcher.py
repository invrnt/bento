from __future__ import annotations

import json
import sqlite3

import pytest

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
