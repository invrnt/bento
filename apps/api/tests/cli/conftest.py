"""CLI test helpers: run `bento` in-process with captured streams, and a real API on a loopback thread."""

from __future__ import annotations

import io
import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from bento.interfaces.cli.app import run

API_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class CliResult:
    code: int
    stdout: str
    stderr: str

    @property
    def json(self) -> Any:
        return json.loads(self.stdout)

    @property
    def error(self) -> dict[str, Any]:
        return json.loads(self.stderr.strip().splitlines()[-1])["error"]


def _capture() -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding="utf-8", write_through=True)


def invoke(
    args: list[str],
    *,
    environ: dict[str, str],
    stdin: str = "",
    transport: httpx.BaseTransport | None = None,
    start_daemon: Any = None,
) -> CliResult:
    stdout, stderr = _capture(), _capture()
    code = run(args, stdout=stdout, stderr=stderr, stdin=io.StringIO(stdin), environ=environ, transport=transport, start_daemon=start_daemon)
    stdout.flush()
    stderr.flush()
    return CliResult(
        code=code,
        stdout=stdout.buffer.getvalue().decode("utf-8"),  # type: ignore[attr-defined]
        stderr=stderr.buffer.getvalue().decode("utf-8"),  # type: ignore[attr-defined]
    )


@pytest.fixture
def cli_env(tmp_path: Path) -> dict[str, str]:
    return {
        "BENTO_HOME": str(tmp_path / "cli-home"),
        "BENTO_DESKTOP_USER_DATA": str(tmp_path / "no-desktop"),
        "BENTO_LANG": "en",
        "PATH": "/usr/bin:/bin",
    }


@pytest.fixture
def mock_cli(cli_env: dict[str, str]) -> Callable[..., CliResult]:
    """Run the CLI against an `httpx.MockTransport` handler."""

    def runner(args: list[str], handler: Callable[[httpx.Request], httpx.Response], *, stdin: str = "", env: dict[str, str] | None = None) -> CliResult:
        environ = {**cli_env, "BENTO_API_URL": "http://127.0.0.1:9", **(env or {})}
        return invoke(args, environ=environ, stdin=stdin, transport=httpx.MockTransport(handler))

    return runner


def migrated_data_dir(base: Path) -> Path:
    from alembic import command
    from alembic.config import Config

    from bento.infrastructure.db.engine import sqlite_url

    data_dir = base / "data"
    (data_dir / "db").mkdir(parents=True)
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", sqlite_url(data_dir / "db" / "bento.sqlite3"))
    command.upgrade(config, "head")
    return data_dir


@dataclass
class LiveApi:
    url: str
    shimmed: bool
    cli_env: dict[str, str]

    def cli(self, *args: str, stdin: str = "") -> CliResult:
        return invoke(list(args), environ={**self.cli_env, "BENTO_API_URL": self.url}, stdin=stdin)

    def json(self, *args: str) -> Any:
        result = self.cli(*args, "--json")
        assert result.code == 0, (result.code, result.stdout, result.stderr)
        return result.json


@pytest.fixture
def live_api(tmp_path: Path, cli_env: dict[str, str]) -> Iterator[LiveApi]:
    import uvicorn

    from bento.infrastructure.settings import Settings
    from bento.interfaces.http.main import create_app
    from tests.cli import cli_endpoints_shim

    data_dir = migrated_data_dir(tmp_path)
    app = create_app(Settings(data_dir=str(data_dir), storage_backend="local"))
    shimmed = cli_endpoints_shim.install(app)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(64)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("API did not start")
        time.sleep(0.02)
    try:
        yield LiveApi(url=f"http://127.0.0.1:{port}", shimmed=shimmed, cli_env=cli_env)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
