from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import multiprocessing
import os
import socket
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL

from bento.adapters.security.key_store import WRAPPING_KEY_ENV
from bento.infrastructure import process_secrets
from bento.infrastructure.child_processes import resolve_executable
from bento.infrastructure.settings import Settings, get_settings, settings_database_path
from bento.interfaces.desktop.security import TOKEN_ENV

if TYPE_CHECKING:
    import uvicorn

# Desktop main reads the API port only from this single stdout line (`BENTO_API_READY {"port":N}`),
# written once the server accepts connections on the loopback socket it bound itself.
READY_PREFIX = "BENTO_API_READY "
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})
_LISTEN_BACKLOG = 2048


def main(argv: Sequence[str] | None = None) -> int:
    multiprocessing.freeze_support()
    # Before anything else runs: per-launch secrets must not stay where child processes inherit them.
    process_secrets.adopt_environment_secrets((TOKEN_ENV, WRAPPING_KEY_ENV))
    arguments = _parser().parse_args(argv)
    if arguments.command == "api":
        return _run_api(arguments)
    if arguments.command == "worker":
        return _run_worker()
    if arguments.command == "migrate":
        return _run_migrations()
    if arguments.command == "probe":
        return _run_probe(arguments)
    raise AssertionError(f"Unhandled command: {arguments.command}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bento-sidecar")
    subparsers = parser.add_subparsers(dest="command", required=True)

    api = subparsers.add_parser("api", help="run the local Bento API")
    api.add_argument("--host", help=argparse.SUPPRESS)
    api.add_argument("--port", type=int, help="headless only; the desktop API always binds an OS-assigned port")
    subparsers.add_parser("worker", help="run the Bento background worker")
    subparsers.add_parser("migrate", help="upgrade the local database schema")

    probe = subparsers.add_parser("probe", help="run one bounded, secret-free capability probe")
    probe.add_argument(
        "kind",
        choices=("runtime", "writable-directory", "model-file", "ffmpeg", "ocr", "telegram"),
    )
    probe.add_argument("--path")
    return parser


def _run_api(arguments: argparse.Namespace) -> int:
    import uvicorn

    from bento.interfaces.http.main import create_app

    settings = get_settings()
    host = arguments.host or settings.host
    if settings.runtime_mode == "desktop":
        if host not in _LOOPBACK_HOSTS:
            raise SystemExit("desktop API must bind to an explicit loopback address")
        if arguments.port is not None:
            raise SystemExit("desktop API binds an ephemeral port chosen by the operating system")
        _serve_desktop_api(create_app(settings), host)
        return 0
    port = arguments.port if arguments.port is not None else settings.api_port
    if not 1 <= port <= 65535:
        raise SystemExit("API port must be between 1 and 65535")
    uvicorn.run(create_app(settings), host=host, port=port, reload=False, access_log=False)
    return 0


def _serve_desktop_api(app: object, host: str) -> None:
    """Serve on a socket this process bound itself, so no other process can take the port between
    allocation and listening, and announce the port only once requests are being accepted."""
    import uvicorn

    listener = bind_loopback_listener(host)
    port = int(listener.getsockname()[1])
    try:
        config = uvicorn.Config(app, host=host, port=port, reload=False, access_log=False)
        server = _announcing_server(config, lambda: announce_ready(port))
        server.run(sockets=[listener])
    finally:
        listener.close()


def bind_loopback_listener(host: str) -> socket.socket:
    if host not in _LOOPBACK_HOSTS:
        raise ValueError("Only loopback listeners are allowed")
    listener = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
    try:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            # Windows: forbid any other socket from binding the same address and port.
            listener.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        listener.bind((host, 0))
        listener.listen(_LISTEN_BACKLOG)
    except BaseException:
        listener.close()
        raise
    return listener


def announce_ready(port: int, stream: TextIO | None = None) -> None:
    target = sys.stdout if stream is None else stream
    target.write(f"{READY_PREFIX}{json.dumps({'port': port}, separators=(',', ':'))}\n")
    target.flush()


def _announcing_server(config: uvicorn.Config, on_started: Callable[[], None]) -> uvicorn.Server:
    import uvicorn

    class AnnouncingServer(uvicorn.Server):
        async def startup(self, sockets: list[socket.socket] | None = None) -> None:
            await super().startup(sockets=sockets)
            if self.started and not self.should_exit:
                on_started()

    return AnnouncingServer(config)


def _run_worker() -> int:
    from bento.interfaces.worker.main import main as worker_main

    worker_main()
    return 0


def _run_migrations() -> int:
    settings = get_settings()
    database_path = settings_database_path(settings)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(_bundle_root() / "alembic.ini"))
    config.set_main_option("script_location", str(_bundle_root() / "migrations"))
    config.set_main_option(
        "sqlalchemy.url",
        URL.create("sqlite+pysqlite", database=str(database_path)).render_as_string(hide_password=False),
    )
    command.upgrade(config, "head")
    return 0


def _run_probe(arguments: argparse.Namespace) -> int:
    settings = get_settings()
    probe = arguments.kind
    if probe == "runtime":
        result = {"probe": probe, "status": "ok", "version": settings.app_version}
    elif probe == "writable-directory":
        path = Path(arguments.path or settings.data_dir)
        result = _probe_writable_directory(path)
    elif probe == "model-file":
        path = Path(arguments.path or settings.jina_model_path)
        result = _probe_model_file(path)
    elif probe == "ffmpeg":
        result = _probe_ffmpeg()
    elif probe == "ocr":
        result = _probe_ocr()
    else:
        result = asyncio.run(_probe_telegram(settings))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
    return 0 if result["status"] == "ok" else 1


def _probe_writable_directory(path: Path) -> dict[str, str]:
    try:
        resolved = path.expanduser().resolve()
        if resolved == Path(resolved.anchor):
            return _failed("writable-directory", "unsafe_path")
        resolved.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(prefix=".bento-write-probe-", dir=resolved)
        os.close(descriptor)
        Path(temporary_path).unlink()
    except OSError:
        return _failed("writable-directory", "not_writable")
    return {"probe": "writable-directory", "status": "ok"}


def _probe_model_file(path: Path) -> dict[str, str]:
    try:
        available = path.expanduser().resolve().is_file() and os.access(path, os.R_OK)
    except OSError:
        available = False
    return {"probe": "model-file", "status": "ok"} if available else _failed("model-file", "not_readable")


def _probe_ffmpeg() -> dict[str, str]:
    available = resolve_executable("ffmpeg") is not None and resolve_executable("ffprobe") is not None
    return {"probe": "ffmpeg", "status": "ok"} if available else _failed("ffmpeg", "not_available")


def _probe_ocr() -> dict[str, str]:
    try:
        # RapidOCR logs engine and model paths during construction; one-shot probe
        # stdout is reserved for the fixed JSON contract and must not expose them.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from rapidocr import RapidOCR

            RapidOCR()
    except Exception:
        return _failed("ocr", "not_available")
    return {"probe": "ocr", "status": "ok"}


async def _probe_telegram(settings: Settings) -> dict[str, str]:
    if not settings.telegram_configured:
        return _failed("telegram", "not_configured")
    try:
        from bento.infrastructure.storage.factory import create_blob_store

        connected = await create_blob_store(settings).probe()
    except Exception:  # External failures are intentionally reduced to a fixed, non-sensitive code.
        connected = False
    return {"probe": "telegram", "status": "ok"} if connected else _failed("telegram", "connection_failed")


def _failed(probe: str, code: str) -> dict[str, str]:
    return {"probe": probe, "status": "failed", "code": code}


def _bundle_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root is not None:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[4]


if __name__ == "__main__":
    raise SystemExit(main())
