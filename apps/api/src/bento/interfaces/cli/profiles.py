"""CLI home, profiles, endpoint files, and the desktop endpoint file (`architecture/cli-runtime.md`)."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from bento.interfaces.cli.errors import CliError

DEFAULT_PROFILE = "default"
PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
DATA_DIR_LAYOUT = ("db", "cache", "uploads", "models", "journal", "config")


def cli_home(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    override = env.get("BENTO_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Bento CLI"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Bento CLI"
    xdg = env.get("XDG_DATA_HOME", "").strip()
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / "bento-cli"


def desktop_user_data(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    override = env.get("BENTO_DESKTOP_USER_DATA", "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = env.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Bento"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Bento"
    xdg = env.get("XDG_CONFIG_HOME", "").strip()
    return (Path(xdg) if xdg else Path.home() / ".config") / "Bento"


def desktop_endpoint_path(environ: Mapping[str, str] | None = None) -> Path:
    return desktop_user_data(environ) / "bento-desktop" / "cli-endpoint.json"


def validate_profile_name(name: str) -> str:
    if not PROFILE_NAME.match(name):
        raise CliError(
            "usage_error",
            "Profile names use letters, digits, '.', '_' or '-' (max 64)",
            {"profile": name},
            exit_code=2,
        )
    return name


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    root: Path

    @classmethod
    def load(cls, name: str, home: Path | None = None) -> Profile:
        base = home if home is not None else cli_home()
        return cls(name=validate_profile_name(name), root=base / "profiles" / name)

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def endpoint_file(self) -> Path:
        return self.root / "endpoint.json"

    @property
    def pid_file(self) -> Path:
        return self.root / "daemon.pid"

    @property
    def lock_file(self) -> Path:
        return self.root / "daemon.lock"

    @property
    def config_file(self) -> Path:
        return self.root / "config.json"

    def log_file(self, name: str) -> Path:
        return self.logs_dir / f"{name}.log"

    def ensure(self) -> None:
        for directory in (self.root.parent.parent, self.root.parent, self.root, self.logs_dir, self.data_dir):
            make_private_dir(directory)
        for child in DATA_DIR_LAYOUT:
            make_private_dir(self.data_dir / child)

    def config(self) -> dict[str, Any]:
        data = read_json(self.config_file)
        return data if isinstance(data, dict) else {}


def make_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_private_json(path: Path, data: Any) -> None:
    """Atomic temp + rename, `0600` on POSIX (the endpoint file holds a bearer token)."""
    make_private_dir(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        if os.name == "posix":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


@dataclass(frozen=True, slots=True)
class Endpoint:
    kind: str
    url: str
    token: str | None
    pid: int | None
    app_version: str | None = None
    started_at: str | None = None
    profile: str | None = None

    def public(self) -> dict[str, Any]:
        """Everything except the token."""
        return {
            "kind": self.kind,
            "url": self.url,
            "pid": self.pid,
            "app_version": self.app_version,
            "started_at": self.started_at,
            "profile": self.profile,
        }


def read_endpoint(path: Path) -> Endpoint | None:
    data = read_json(path)
    if not isinstance(data, dict):
        return None
    url = data.get("url")
    if not isinstance(url, str) or not is_loopback_url(url):
        return None
    token = data.get("token")
    pid = data.get("pid")
    return Endpoint(
        kind=str(data.get("kind") or "daemon"),
        url=url.rstrip("/"),
        token=token if isinstance(token, str) and token else None,
        pid=pid if isinstance(pid, int) and pid > 0 else None,
        app_version=data.get("app_version") if isinstance(data.get("app_version"), str) else None,
        started_at=data.get("started_at") if isinstance(data.get("started_at"), str) else None,
        profile=data.get("profile") if isinstance(data.get("profile"), str) else None,
    )


def is_loopback_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme == "http" and (parts.hostname or "") in _LOOPBACK


def pid_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_pid_alive(pid)
    try:
        # A daemon this process started and that already exited is a zombie until reaped.
        reaped, _ = os.waitpid(pid, os.WNOHANG)
        if reaped == pid:
            return False
    except ChildProcessError:
        pass
    except OSError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_pid_alive(pid: int) -> bool:  # pragma: no cover - exercised on Windows CI only
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    process_query_limited_information = 0x1000
    still_active = 259
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)
