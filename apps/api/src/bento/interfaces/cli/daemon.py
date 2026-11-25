"""Profile daemon: supervises the API and worker sidecars for headless machines (`architecture/cli-runtime.md` § Daemon).

`run` is the foreground supervisor (used by services and by `start`); `start` spawns it detached and waits
for `endpoint.json` plus a healthy `/api/health`. The per-run API token reaches the API child only through
its environment and `endpoint.json` (0600); it is never logged.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import secrets
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from bento.interfaces.cli import cli_version
from bento.interfaces.cli.errors import EXIT_CONFLICT, EXIT_UNREACHABLE, CliError
from bento.interfaces.cli.profiles import (
    Endpoint,
    Profile,
    desktop_user_data,
    pid_alive,
    read_json,
    write_private_json,
)
from bento.interfaces.cli.target import health_ok, live_endpoint

READY_PREFIX = "BENTO_API_READY "
API_TOKEN_ENV = "BENTO_API_TOKEN"
STOP_FILE = "stop.request"
BUILD_CONFIG_FILE = "build-config.json"
BUILD_CONFIG_KEYS = ("BENTO_TELEGRAM_API_ID", "BENTO_TELEGRAM_API_HASH", "BENTO_RELAY_URL", "BENTO_PUBLIC_SITE_URL")
# Never inherited by the daemon or its children: per-launch secrets of other processes and CLI targeting.
STRIPPED_ENV = (
    API_TOKEN_ENV,
    "BENTO_API_URL",
    "BENTO_DESKTOP_API_TOKEN",
    "BENTO_DESKTOP_CLI_TOKEN",
    "BENTO_DEVICE_WRAPPING_KEY",
)
GRACEFUL_STOP_SECONDS = 10.0
BACKOFF_START = 1.0
BACKOFF_MAX = 30.0
STABLE_AFTER_SECONDS = 60.0
_WINDOWS = sys.platform == "win32"


# Commands ------------------------------------------------------------------------------------


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def cli_argv(*args: str) -> list[str]:
    """How to run this same CLI again (frozen binary or `python -m`)."""
    if frozen():
        return [sys.executable, *args]
    return [sys.executable, "-m", "bento.interfaces.cli", *args]


def sidecar_argv(*args: str) -> list[str]:
    return cli_argv("_sidecar", *args)


def service_exec_argv(profile: Profile) -> list[str]:
    import shutil

    if frozen():
        base = [sys.executable]
    else:
        found = shutil.which("bento")
        base = [str(Path(found).resolve())] if found else [sys.executable, "-m", "bento.interfaces.cli"]
    return [*base, "daemon", "run", "--profile", profile.name]


# Environment ---------------------------------------------------------------------------------


def build_config(executable: str | None = None) -> dict[str, str]:
    """Telegram build credentials and service URLs bundled next to a frozen binary."""
    if executable is None:
        if not frozen():
            return {}
        executable = sys.executable
    data = read_json(Path(executable).resolve().parent / BUILD_CONFIG_FILE)
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if key in BUILD_CONFIG_KEYS and isinstance(value, str) and value}


def daemon_environment(profile: Profile, base: Mapping[str, str]) -> dict[str, str]:
    env = {key: value for key, value in base.items() if key not in STRIPPED_ENV}
    env["DATA_DIR"] = str(profile.data_dir)
    env["BENTO_RUNTIME_MODE"] = "headless"
    env["HOST"] = "127.0.0.1"
    env.setdefault("STORAGE_BACKEND", "telegram")
    for key, value in build_config().items():
        env.setdefault(key, value)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def child_environment(base: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in base.items() if key not in STRIPPED_ENV}


def is_desktop_data_dir(data_dir: Path, environ: Mapping[str, str] | None = None) -> bool:
    if (data_dir / "bootstrap.json").exists():
        return True
    if data_dir.name == "bento-data" and (data_dir.parent / "bento-desktop" / "bootstrap.json").exists():
        return True
    try:
        desktop_default = (desktop_user_data(environ) / "bento-data").resolve()
        return data_dir.resolve() == desktop_default
    except OSError:
        return False


# Profile lock ---------------------------------------------------------------------------------


class ProfileLock:
    """Exclusive, non-blocking lock so a profile has at most one supervisor."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: IO[bytes] | None = None

    def acquire(self) -> bool:
        handle = self._path.open("a+b")
        try:
            if _WINDOWS:
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        with contextlib.suppress(OSError):
            if _WINDOWS:
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


# Children ------------------------------------------------------------------------------------


def _popen_kwargs() -> dict[str, Any]:
    if _WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]
    return {}


@dataclass
class Child:
    name: str
    log_path: Path
    env: dict[str, str]
    process: subprocess.Popen[bytes] | None = None
    started_at: float = 0.0
    backoff: float = BACKOFF_START
    restart_at: float | None = None
    _log: IO[bytes] | None = field(default=None, repr=False)

    def log_handle(self) -> IO[bytes]:
        if self._log is None or self._log.closed:
            self._log = self.log_path.open("ab")
        return self._log

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self, timeout: float = GRACEFUL_STOP_SECONDS) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            self._close_log()
            return
        with contextlib.suppress(OSError):
            if _WINDOWS:
                process.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)
        self._close_log()

    def _close_log(self) -> None:
        if self._log is not None and not self._log.closed:
            self._log.close()


class ApiChild(Child):
    """The API sidecar: `api --ephemeral` binds an OS-chosen loopback port and announces it."""

    port: int | None = None

    def start(self) -> None:
        self.port = None
        args = ["api", "--ephemeral"]
        log = self.log_handle()
        self.process = subprocess.Popen(
            sidecar_argv(*args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=log,
            env=self.env,
            close_fds=True,
            **_popen_kwargs(),
        )
        self.started_at = time.monotonic()
        self._ready: queue.Queue[int] = queue.Queue()
        threading.Thread(target=self._pump, args=(self.process, log), daemon=True).start()

    def _pump(self, process: subprocess.Popen[bytes], log: IO[bytes]) -> None:
        assert process.stdout is not None
        for raw in iter(process.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith(READY_PREFIX):
                with contextlib.suppress(ValueError, TypeError, KeyError):
                    self._ready.put(int(json.loads(line[len(READY_PREFIX) :])["port"]))
                    continue
            with contextlib.suppress(ValueError, OSError):
                log.write(raw)
                log.flush()

    def wait_ready(self, token: str, timeout: float) -> int:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process is None or self.process.poll() is not None:
                code = None if self.process is None else self.process.returncode
                raise CliError(
                    "daemon_start_failed",
                    "The Bento API process exited during startup",
                    {"exit_code": code, "next": "bento daemon logs"},
                    EXIT_UNREACHABLE,
                )
            if self.port is None:
                try:
                    self.port = self._ready.get(timeout=0.2)
                except queue.Empty:
                    continue
            if health_ok(self.url, token, timeout=2.0):
                return self.port
            time.sleep(0.2)
        raise CliError(
            "daemon_start_failed",
            "The Bento API did not become ready in time",
            {"timeout_seconds": timeout, "next": "bento daemon logs"},
            EXIT_UNREACHABLE,
        )

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


class WorkerChild(Child):
    def start(self) -> None:
        log = self.log_handle()
        self.process = subprocess.Popen(
            sidecar_argv("worker"),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            env=self.env,
            close_fds=True,
            **_popen_kwargs(),
        )
        self.started_at = time.monotonic()


# Supervisor ----------------------------------------------------------------------------------


class Supervisor:
    def __init__(self, profile: Profile, environ: Mapping[str, str], *, ready_timeout: float = 60.0) -> None:
        self.profile = profile
        self.env = daemon_environment(profile, environ)
        self.ready_timeout = ready_timeout
        self.token = secrets.token_urlsafe(32)
        self._stop = threading.Event()
        self._log = profile.log_file("daemon")
        api_env = dict(self.env)
        api_env[API_TOKEN_ENV] = self.token
        self.api = ApiChild(name="api", log_path=profile.log_file("api"), env=api_env)
        self.worker = WorkerChild(name="worker", log_path=profile.log_file("worker"), env=dict(self.env))

    def log(self, message: str) -> None:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        with contextlib.suppress(OSError), self._log.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {message}\n")

    def request_stop(self, *_: object) -> None:
        self._stop.set()

    def migrate(self) -> None:
        with self._log.open("ab") as log:
            completed = subprocess.run(
                sidecar_argv("migrate"),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                env=self.env,
                timeout=600,
                check=False,
            )
        if completed.returncode != 0:
            raise CliError(
                "daemon_start_failed",
                "Database migrations failed",
                {"exit_code": completed.returncode, "next": "bento daemon logs"},
                EXIT_UNREACHABLE,
            )

    def start_api(self) -> None:
        self.api.start()
        self.api.wait_ready(self.token, self.ready_timeout)

    def write_endpoint(self) -> None:
        write_private_json(
            self.profile.endpoint_file,
            {
                "version": 1,
                "kind": "daemon",
                "url": self.api.url,
                "token": self.token,
                "pid": os.getpid(),
                "app_version": cli_version(),
                "started_at": datetime.now(UTC).isoformat(),
                "profile": self.profile.name,
            },
        )
        self.profile.pid_file.write_text(str(os.getpid()), encoding="ascii")

    def cleanup_files(self) -> None:
        for path in (self.profile.endpoint_file, self.profile.pid_file, self.profile.root / STOP_FILE):
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)

    def install_signals(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        for name in ("SIGTERM", "SIGINT", "SIGBREAK", "SIGHUP"):
            sig = getattr(signal, name, None)
            if sig is not None:
                with contextlib.suppress(OSError, ValueError):
                    signal.signal(sig, self.request_stop)

    def stop_requested(self) -> bool:
        if (self.profile.root / STOP_FILE).exists():
            self._stop.set()
        return self._stop.is_set()

    def supervise_once(self) -> None:
        now = time.monotonic()
        for child in (self.api, self.worker):
            if child.running():
                if now - child.started_at > STABLE_AFTER_SECONDS:
                    child.backoff = BACKOFF_START
                continue
            if child.restart_at is None:
                code = None if child.process is None else child.process.returncode
                self.log(f"{child.name} exited (code {code}); restarting in {child.backoff:.0f}s")
                child.restart_at = now + child.backoff
                child.backoff = min(BACKOFF_MAX, child.backoff * 2)
                continue
            if now >= child.restart_at:
                child.restart_at = None
                try:
                    if child is self.api:
                        self.start_api()
                        self.write_endpoint()
                    else:
                        self.worker.start()
                    self.log(f"{child.name} restarted")
                except (CliError, OSError) as exc:
                    self.log(f"{child.name} restart failed: {getattr(exc, 'code', type(exc).__name__)}")

    def run(self) -> int:
        self.install_signals()
        self.log(f"starting profile {self.profile.name} (version {cli_version()})")
        try:
            self.migrate()
            self.start_api()
            self.worker.start()
            self.write_endpoint()
            self.log(f"ready on {self.api.url}")
            while not self.stop_requested():
                self.supervise_once()
                self._stop.wait(0.5)
        finally:
            self.log("stopping")
            self.api.stop()
            self.worker.stop()
            self.cleanup_files()
            self.log("stopped")
        return 0


def run_daemon(profile: Profile, environ: Mapping[str, str] | None = None, *, ready_timeout: float = 60.0) -> int:
    env = os.environ if environ is None else environ
    profile.ensure()
    if is_desktop_data_dir(profile.data_dir, env):
        raise CliError(
            "daemon_data_dir_conflict",
            "This data directory belongs to the Bento desktop app; a daemon cannot share it",
            {"profile": profile.name},
            2,
        )
    lock = ProfileLock(profile.lock_file)
    if not lock.acquire():
        raise CliError(
            "daemon_already_running",
            "A Bento daemon is already running for this profile",
            {"profile": profile.name},
            EXIT_CONFLICT,
        )
    try:
        with contextlib.suppress(OSError):
            (profile.root / STOP_FILE).unlink(missing_ok=True)
        return Supervisor(profile, env, ready_timeout=ready_timeout).run()
    finally:
        lock.release()


# Control -------------------------------------------------------------------------------------


def daemon_pid(profile: Profile) -> int | None:
    try:
        value = int(profile.pid_file.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    return value if value > 0 else None


def start_daemon(
    profile: Profile,
    timeout: float = 60.0,
    *,
    environ: Mapping[str, str] | None = None,
    check: Callable[[str, str | None], bool] = health_ok,
) -> Endpoint:
    existing = live_endpoint(profile.endpoint_file, check=check)
    if existing is not None:
        return existing
    profile.ensure()
    env = child_environment(os.environ if environ is None else environ)
    kwargs: dict[str, Any] = {}
    if _WINDOWS:
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    with profile.log_file("daemon").open("ab") as log:
        process = subprocess.Popen(
            cli_argv("daemon", "run", "--profile", profile.name),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            env=env,
            close_fds=True,
            **kwargs,
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        endpoint = live_endpoint(profile.endpoint_file, check=check)
        if endpoint is not None:
            return endpoint
        code = process.poll()
        if code is not None:
            if code == EXIT_CONFLICT:
                # Another `start` won the race; wait for its endpoint instead.
                time.sleep(0.25)
                continue
            raise CliError(
                "daemon_start_failed",
                "Bento could not start for this profile",
                {"profile": profile.name, "exit_code": code, "next": "bento daemon logs"},
                EXIT_UNREACHABLE,
            )
        time.sleep(0.25)
    raise CliError(
        "daemon_start_failed",
        "Bento did not become ready in time",
        {"profile": profile.name, "timeout_seconds": timeout, "next": "bento daemon logs"},
        EXIT_UNREACHABLE,
    )


def stop_daemon(profile: Profile, timeout: float = 20.0) -> bool:
    pid = daemon_pid(profile)
    if not pid_alive(pid):
        for path in (profile.endpoint_file, profile.pid_file, profile.root / STOP_FILE):
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
        return False
    assert pid is not None
    with contextlib.suppress(OSError):
        (profile.root / STOP_FILE).write_text("stop", encoding="ascii")
    if not _WINDOWS:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and pid_alive(pid):
        time.sleep(0.2)
    if pid_alive(pid):
        with contextlib.suppress(OSError):
            if _WINDOWS:
                os.kill(pid, signal.SIGTERM)
            else:
                os.killpg(pid, signal.SIGKILL)
        time.sleep(0.5)
    for path in (profile.endpoint_file, profile.pid_file, profile.root / STOP_FILE):
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
    return True


def daemon_status(profile: Profile, *, check: Callable[[str, str | None], bool] = health_ok) -> dict[str, Any]:
    pid = daemon_pid(profile)
    alive = pid_alive(pid)
    endpoint = live_endpoint(profile.endpoint_file, check=check) if alive else None
    return {
        "profile": profile.name,
        "running": alive,
        "healthy": endpoint is not None,
        "pid": pid if alive else None,
        "url": endpoint.url if endpoint else None,
        "app_version": endpoint.app_version if endpoint else None,
        "started_at": endpoint.started_at if endpoint else None,
        "data_dir": str(profile.data_dir),
        "logs_dir": str(profile.logs_dir),
    }


# Services ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ServiceFile:
    kind: str  # systemd | launchd
    path: Path
    content: str
    commands: tuple[str, ...]
    uninstall_commands: tuple[str, ...]


def service_file(profile: Profile, environ: Mapping[str, str] | None = None) -> ServiceFile:
    env = os.environ if environ is None else environ
    linux = sys.platform.startswith("linux") or sys.platform.startswith("freebsd")
    if not linux and sys.platform != "darwin":
        raise CliError(
            "service_not_supported",
            "Background services are not supported on this OS; use `bento daemon start`",
            {"platform": sys.platform},
            1,
        )
    argv = service_exec_argv(profile)
    home_override = env.get("BENTO_HOME", "").strip()
    if linux:
        unit = "bento.service" if profile.name == "default" else f"bento@{profile.name}.service"
        config_home = Path(env.get("XDG_CONFIG_HOME", "").strip() or Path.home() / ".config")
        lines = [
            "[Unit]",
            f"Description=Bento private cloud (profile {profile.name})",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"ExecStart={' '.join(_systemd_quote(part) for part in argv)}",
            "Restart=on-failure",
            "RestartSec=5",
            "TimeoutStopSec=30",
        ]
        if home_override:
            lines.append(f"Environment={_systemd_quote('BENTO_HOME=' + home_override)}")
        lines += ["", "[Install]", "WantedBy=default.target", ""]
        return ServiceFile(
            kind="systemd",
            path=config_home / "systemd" / "user" / unit,
            content="\n".join(lines),
            commands=(
                "systemctl --user daemon-reload",
                f"systemctl --user enable --now {unit}",
                "loginctl enable-linger $USER",
            ),
            uninstall_commands=(f"systemctl --user disable --now {unit}", "systemctl --user daemon-reload"),
        )
    else:
        label = f"app.bento.cli.{profile.name}"
        path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        args_xml = "\n".join(f"    <string>{_xml(part)}</string>" for part in argv)
        env_xml = ""
        if home_override:
            env_xml = (
                "  <key>EnvironmentVariables</key>\n  <dict>\n"
                f"    <key>BENTO_HOME</key>\n    <string>{_xml(home_override)}</string>\n  </dict>\n"
            )
        log = _xml(str(profile.log_file("daemon")))
        content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n<dict>\n'
            f"  <key>Label</key>\n  <string>{label}</string>\n"
            f"  <key>ProgramArguments</key>\n  <array>\n{args_xml}\n  </array>\n"
            f"{env_xml}"
            "  <key>RunAtLoad</key>\n  <true/>\n"
            "  <key>KeepAlive</key>\n  <dict>\n    <key>SuccessfulExit</key>\n    <false/>\n  </dict>\n"
            f"  <key>StandardOutPath</key>\n  <string>{log}</string>\n"
            f"  <key>StandardErrorPath</key>\n  <string>{log}</string>\n"
            "</dict>\n</plist>\n"
        )
        quoted = shlex.quote(str(path))
        return ServiceFile(
            kind="launchd",
            path=path,
            content=content,
            commands=(f"launchctl bootstrap gui/$(id -u) {quoted}",),
            uninstall_commands=(f"launchctl bootout gui/$(id -u)/{label}",),
        )


def _systemd_quote(value: str) -> str:
    if value and all(char.isalnum() or char in "/._-=:@+," for char in value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _xml(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
