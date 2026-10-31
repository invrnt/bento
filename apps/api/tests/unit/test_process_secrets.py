from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from bento.adapters.media import generator
from bento.infrastructure import process_secrets
from bento.infrastructure.child_processes import child_environment, resolve_executable


@pytest.fixture(autouse=True)
def _empty_holder() -> Iterator[None]:
    process_secrets.clear()
    yield
    process_secrets.clear()


def test_adopted_secrets_leave_the_environment_and_stay_in_process() -> None:
    environ = {"BENTO_DESKTOP_API_TOKEN": "per-launch-token", "BENTO_DEVICE_WRAPPING_KEY": "   ", "PATH": "/usr/bin"}

    adopted = process_secrets.adopt_environment_secrets(
        ("BENTO_DESKTOP_API_TOKEN", "BENTO_DEVICE_WRAPPING_KEY", "BENTO_ABSENT"), environ
    )

    assert adopted == ("BENTO_DESKTOP_API_TOKEN",)
    assert environ == {"PATH": "/usr/bin"}
    assert process_secrets.get("BENTO_DESKTOP_API_TOKEN") == "per-launch-token"
    # Blank values count as absent, exactly like an unset variable.
    assert process_secrets.get("BENTO_DEVICE_WRAPPING_KEY") is None
    process_secrets.clear()
    assert process_secrets.get("BENTO_DESKTOP_API_TOKEN") is None


def test_adoption_defaults_to_the_real_process_environment(monkeypatch) -> None:
    monkeypatch.setenv("BENTO_TEST_PROCESS_SECRET", "must-not-be-inherited")

    process_secrets.adopt_environment_secrets(("BENTO_TEST_PROCESS_SECRET",))

    assert "BENTO_TEST_PROCESS_SECRET" not in os.environ
    assert process_secrets.get("BENTO_TEST_PROCESS_SECRET") == "must-not-be-inherited"
    inherited = subprocess.run(
        [sys.executable, "-I", "-c", "import os; print(os.environ.get('BENTO_TEST_PROCESS_SECRET', 'absent'))"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert inherited.stdout.strip() == "absent"


def test_child_environment_is_an_allowlist() -> None:
    environ = {
        "PATH": "/usr/bin",
        "HOME": "/home/bento",
        "LANG": "es_CO.UTF-8",
        "LC_ALL": "es_CO.UTF-8",
        "TMPDIR": "/tmp",
        "BENTO_DESKTOP_API_TOKEN": "token",
        "BENTO_DEVICE_WRAPPING_KEY": "key",
        "BENTO_TELEGRAM_API_HASH": "hash",
        "LD_PRELOAD": "/tmp/evil.so",
        "SYSTEMROOT": "C:\\Windows",
    }

    assert child_environment(environ, windows=False) == {
        "PATH": "/usr/bin",
        "HOME": "/home/bento",
        "LANG": "es_CO.UTF-8",
        "LC_ALL": "es_CO.UTF-8",
        "TMPDIR": "/tmp",
    }
    windows = child_environment({**environ, "windir": "C:\\Windows", "Temp": "C:\\Temp"}, windows=True)
    assert windows["SYSTEMROOT"] == "C:\\Windows"
    assert windows["windir"] == "C:\\Windows"
    assert windows["Temp"] == "C:\\Temp"
    assert not {"BENTO_DESKTOP_API_TOKEN", "BENTO_DEVICE_WRAPPING_KEY", "LD_PRELOAD"} & windows.keys()


def _tool(directory: Path, name: str, *, executable: bool = True) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755 if executable else 0o644)
    return path


@pytest.mark.skipif(os.name != "posix", reason="POSIX executable bits")
def test_executables_resolve_from_absolute_path_entries_outside_the_working_directory(tmp_path, monkeypatch) -> None:
    planted = _tool(tmp_path / "downloads", "ffmpeg")
    not_executable = _tool(tmp_path / "plain", "ffmpeg", executable=False)
    real = _tool(tmp_path / "system", "ffmpeg")
    monkeypatch.chdir(planted.parent)
    search = os.pathsep.join(["", ".", "downloads", str(planted.parent), str(not_executable.parent), str(real.parent)])

    assert resolve_executable("ffmpeg", environ={"PATH": search}, windows=False) == str(real)
    assert resolve_executable("ffmpeg", environ={"PATH": "."}, windows=False) is None
    assert resolve_executable("ffmpeg", environ={}, windows=False) is None
    for name in ("", "./ffmpeg", "bin/ffmpeg", str(real)):
        with pytest.raises(ValueError):
            resolve_executable(name, environ={"PATH": search})


@pytest.mark.skipif(os.name != "posix", reason="POSIX executable bits")
def test_windows_resolution_requires_an_exe(tmp_path) -> None:
    _tool(tmp_path / "bin", "ffmpeg.bat")
    exe = _tool(tmp_path / "bin", "ffmpeg.exe")

    assert resolve_executable("ffmpeg", environ={"PATH": f'"{exe.parent}"'}, windows=True) == str(exe)
    (exe).unlink()
    assert resolve_executable("ffmpeg", environ={"PATH": str(exe.parent)}, windows=True) is None


def test_media_tools_run_with_the_scrubbed_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BENTO_DESKTOP_API_TOKEN", "must-not-reach-ffmpeg")
    monkeypatch.setenv("BENTO_DEVICE_WRAPPING_KEY", "must-not-reach-ffmpeg")
    calls: list[dict[str, object]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout='{"format":{"duration":"2.5"}}', stderr="")

    monkeypatch.setattr(generator.subprocess, "run", fake_run)

    assert generator._video_duration_seconds("/usr/bin/ffprobe", tmp_path / "clip.mp4", tmp_path) == 2.5

    environment = calls[0]["env"]
    assert isinstance(environment, dict)
    assert "BENTO_DESKTOP_API_TOKEN" not in environment
    assert "BENTO_DEVICE_WRAPPING_KEY" not in environment
    assert "must-not-reach-ffmpeg" not in environment.values()
    assert calls[0]["cwd"] == tmp_path
    assert calls[0]["stdin"] == subprocess.DEVNULL
