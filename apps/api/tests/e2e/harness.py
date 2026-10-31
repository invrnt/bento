"""Real multi-process Bento devices against one fake Telegram cloud (and optionally the relay double).

Each `Device` runs the production entrypoints in subprocesses, exactly as Docker and the dev guide do:
`python -m bento.interfaces.desktop.launcher migrate`, `python -m bento.interfaces.http.main` and
`python -m bento.interfaces.worker.main`, with its own `DATA_DIR` and API port. Only
`BENTO_FAKE_TELEGRAM_DIR` (and `BENTO_RELAY_URL`) are shared. Everything is driven over HTTP.

Used by `tests/e2e` and by `scripts/smoke/two_devices.py`.
"""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import httpx

from bento.domain.settings_registry import SETTINGS_BY_ALIAS

T = TypeVar("T")

TRACE = os.environ.get("BENTO_E2E_TRACE", "") == "1"

API_MODULE = "bento.interfaces.http.main"
WORKER_MODULE = "bento.interfaces.worker.main"
LAUNCHER_MODULE = "bento.interfaces.desktop.launcher"
# Inherited variables that would leak another configuration into a device, besides every settings alias.
_DROPPED_PREFIXES = ("BENTO_", "VITE_")
_DROPPED = {"DATA_DIR", "API_PORT", "WEB_PORT", "HOST", "STORAGE_BACKEND", "ENVIRONMENT", "PYTHONPATH"}


class DeviceError(AssertionError):
    pass


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_until(
    probe: Callable[[], T | None],
    *,
    timeout: float = 30.0,
    interval: float = 0.2,
    message: str | Callable[[], str] = "condition",
) -> T:
    """Poll `probe` until it returns a truthy value; raise with `message` (and the last value) on timeout."""
    started = time.monotonic()
    deadline = started + timeout
    last: Any = None
    while True:
        last = probe()
        if last:
            if TRACE:
                text = message() if callable(message) else message
                print(f"[e2e] {time.monotonic() - started:6.2f}s {text[:100]}", file=sys.stderr, flush=True)
            return last
        if time.monotonic() >= deadline:
            text = message() if callable(message) else message
            raise DeviceError(f"Timed out after {timeout:.0f}s waiting for {text}; last value: {last!r}")
        time.sleep(interval)


def device_environ(base: Mapping[str, str] | None = None, **values: str) -> dict[str, str]:
    """`base` (default: this process) without Bento settings, plus `values`."""
    source = dict(os.environ if base is None else base)
    environ = {
        key: value
        for key, value in source.items()
        if key not in SETTINGS_BY_ALIAS and key not in _DROPPED and not key.startswith(_DROPPED_PREFIXES)
    }
    environ.update({"PYTHONUNBUFFERED": "1", **values})
    return environ


@dataclass
class Device:
    """One Bento installation: API + worker processes over a private data directory."""

    name: str
    root: Path
    cloud_dir: Path
    relay_url: str = ""
    port: int = field(default_factory=free_port)
    web_port: int = 5173
    manual_login: bool = False
    extra_env: dict[str, str] = field(default_factory=dict)
    python: str = sys.executable
    api: subprocess.Popen[bytes] | None = None
    worker: subprocess.Popen[bytes] | None = None
    _client: httpx.Client | None = None

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/api"

    @property
    def environ(self) -> dict[str, str]:
        values = {
            "STORAGE_BACKEND": "fake",
            "ENVIRONMENT": "local",
            "DATA_DIR": str(self.data_dir),
            "API_PORT": str(self.port),
            "WEB_PORT": str(self.web_port),
            "BENTO_FAKE_TELEGRAM_DIR": str(self.cloud_dir),
            "BENTO_RELAY_URL": self.relay_url,
            "OCR_PROVIDER": "disabled",
            "EMBEDDINGS_PROVIDER": "disabled",
        }
        if self.manual_login:
            values["BENTO_FAKE_TELEGRAM_MANUAL_LOGIN"] = "1"
        values.update(self.extra_env)
        return device_environ(**values)

    # Processes -----------------------------------------------------------------------------

    def start(self, *, worker: bool = True) -> Device:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.migrate()
        self.start_api()
        if worker:
            self.start_worker()
        return self

    def migrate(self) -> None:
        completed = subprocess.run(
            [self.python, "-m", LAUNCHER_MODULE, "migrate"],
            cwd=self.root,
            env=self.environ,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0:
            raise DeviceError(f"{self.name}: migrate failed\n{completed.stderr.decode(errors='replace')[-4000:]}")

    def start_api(self) -> None:
        if self.api is not None and self.api.poll() is None:
            return
        self.api = self._spawn("api", API_MODULE)
        wait_until(self._api_ready, timeout=60, interval=0.1, message=lambda: f"{self.name} API on {self.port}")

    def start_worker(self) -> None:
        if self.worker is not None and self.worker.poll() is None:
            return
        self.worker = self._spawn("worker", WORKER_MODULE)

    def stop_worker(self) -> None:
        self.worker = _terminate(self.worker)

    def stop_api(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        self.api = _terminate(self.api)

    def stop(self) -> None:
        self.stop_worker()
        self.stop_api()

    def restart(self) -> None:
        self.stop()
        self.start()

    def assert_running(self) -> None:
        for role, process in (("api", self.api), ("worker", self.worker)):
            if process is not None and process.poll() is not None:
                raise DeviceError(f"{self.name} {role} exited with {process.returncode}\n{self.log_tail(role)}")

    def log_tail(self, role: str, lines: int = 60) -> str:
        path = self.logs_dir / f"{role}.log"
        if not path.is_file():
            return ""
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])

    def _spawn(self, role: str, module: str) -> subprocess.Popen[bytes]:
        log = (self.logs_dir / f"{role}.log").open("ab")
        try:
            return subprocess.Popen(
                [self.python, "-m", module],
                cwd=self.root,
                env=self.environ,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log.close()

    def _api_ready(self) -> bool:
        if self.api is not None and self.api.poll() is not None:
            raise DeviceError(f"{self.name} API exited with {self.api.returncode}\n{self.log_tail('api')}")
        try:
            return httpx.get(f"{self.base_url}/health", timeout=1.0).status_code == 200
        except httpx.HTTPError:
            return False

    # HTTP ----------------------------------------------------------------------------------

    @property
    def http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self.base_url, timeout=30.0)
        return self._client

    def request(self, method: str, path: str, *, expect: int | tuple[int, ...] = 200, **kwargs: Any) -> httpx.Response:
        response = self.http.request(method, path, **kwargs)
        allowed = (expect,) if isinstance(expect, int) else expect
        if response.status_code not in allowed:
            self.assert_running()
            raise DeviceError(f"{self.name} {method} {path} -> {response.status_code}: {response.text[:2000]}")
        return response

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs).json()

    def post(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        return self.request("POST", path, json=json, **kwargs).json()

    def patch(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        return self.request("PATCH", path, json=json, **kwargs).json()

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs).json()

    # Journeys ------------------------------------------------------------------------------

    def sign_in_with_qr(self, *, timeout: float = 30.0) -> dict[str, Any]:
        """`POST /account/login/qr`, then poll `GET /account` (the fake approves the QR after ~2 s)."""
        started = self.post("/account/login/qr")
        if started["step"] == "authorized":
            return started
        assert started["step"] == "qr_pending", started
        assert started["qr_url"] and started["qr"]["rows"], started

        def authorized() -> dict[str, Any] | None:
            if self.manual_login:
                self.post("/dev/fake-telegram/approve-login")
            status = self.get("/account")
            return status if status["step"] == "authorized" else None

        return wait_until(authorized, timeout=timeout, interval=0.3, message=f"{self.name} QR sign-in")

    def upload(
        self, filename: str, content: bytes, mime: str, *, mode: str = "drive", folder_id: str | None = None
    ) -> dict[str, Any]:
        data = {"mode": mode}
        if folder_id is not None:
            data["folder_id"] = folder_id
        return self.post("/assets/upload", files={"file": (filename, content, mime)}, data=data)

    def jobs(self, **params: Any) -> list[dict[str, Any]]:
        return list(self.get("/jobs", params=params or None)["items"])

    def drive_items(self, folder_id: str | None = None) -> list[dict[str, Any]]:
        params = {"folder_id": folder_id} if folder_id else None
        return list(self.get("/drive/items", params=params)["items"])

    def drive_assets(self, folder_id: str | None = None) -> dict[str, dict[str, Any]]:
        return {item["asset"]["id"]: item["asset"] for item in self.drive_items(folder_id) if item["type"] == "asset"}

    def drive_folders(self, folder_id: str | None = None) -> dict[str, dict[str, Any]]:
        items = self.drive_items(folder_id)
        return {item["folder"]["id"]: item["folder"] for item in items if item["type"] == "folder"}

    def asset(self, asset_id: str) -> dict[str, Any] | None:
        response = self.http.get(f"/assets/{asset_id}")
        return response.json() if response.status_code == 200 else None

    def sync_now(self) -> None:
        self.post("/sync/now")


def _terminate(process: subprocess.Popen[bytes] | None, timeout: float = 15.0) -> None:
    if process is None or process.poll() is not None:
        return None
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=timeout)
    return None


@dataclass
class World:
    """One simulated Telegram account (fake cloud directory), an optional relay, and its devices."""

    root: Path
    relay_url: str = ""
    devices: dict[str, Device] = field(default_factory=dict)

    @property
    def cloud_dir(self) -> Path:
        return self.root / "fake-telegram"

    def device(self, name: str, *, start: bool = True, relay: bool = True, **options: Any) -> Device:
        device = Device(
            name=name,
            root=self.root / name,
            cloud_dir=self.cloud_dir,
            relay_url=self.relay_url if relay else "",
            **options,
        )
        self.devices[name] = device
        if start:
            device.start()
        return device

    def stop(self) -> None:
        for device in self.devices.values():
            with contextlib.suppress(Exception):
                device.stop()

    def logs(self, lines: int = 40) -> str:
        sections = []
        for device in self.devices.values():
            for role in ("api", "worker"):
                tail = device.log_tail(role, lines)
                if tail:
                    sections.append(f"----- {device.name} {role} -----\n{tail}")
        return "\n".join(sections)


@contextlib.contextmanager
def sigterm_as_interrupt() -> Iterator[None]:
    """Turn SIGTERM into `KeyboardInterrupt` so cleanup still stops the device processes (own sessions)."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def interrupt(signum: int, frame: object) -> None:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)  # a repeated SIGTERM must not cut the cleanup short
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


@contextlib.contextmanager
def relay_double() -> Iterator[str]:
    """The Python relay double (`tests/integration/pairing/relay_double.py`) on a background thread."""
    from tests.integration.pairing.relay_double import relay_in_thread

    with relay_in_thread() as relay:
        yield relay.url
