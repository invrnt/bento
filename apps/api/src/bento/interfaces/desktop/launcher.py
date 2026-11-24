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

from bento.adapters.security.key_store import WRAPPING_KEY_ENV
from bento.infrastructure import process_secrets
from bento.infrastructure.child_processes import resolve_executable
from bento.infrastructure.db.migrate import DATA_DIR_LAYOUT, bundle_root, run_migrations
from bento.infrastructure.loopback import LOOPBACK_HOSTS as _LOOPBACK_HOSTS
from bento.infrastructure.loopback import bind_loopback_listener
from bento.infrastructure.settings import Settings, get_settings
from bento.interfaces.desktop.security import CLI_TOKEN_ENV, TOKEN_ENV
from bento.interfaces.http.request_guard import API_TOKEN_ENV

if TYPE_CHECKING:
    import uvicorn

# Desktop main reads the API port only from this single stdout line (`BENTO_API_READY {"port":N}`),
# written once the server accepts connections on the loopback socket it bound itself.
READY_PREFIX = "BENTO_API_READY "

__all__ = ["DATA_DIR_LAYOUT", "READY_PREFIX", "announce_ready", "bind_loopback_listener", "main"]


def main(argv: Sequence[str] | None = None) -> int:
    multiprocessing.freeze_support()
    # Before anything else runs: per-launch secrets must not stay where child processes inherit them.
    process_secrets.adopt_environment_secrets((TOKEN_ENV, CLI_TOKEN_ENV, API_TOKEN_ENV, WRAPPING_KEY_ENV))
    arguments = _parser().parse_args(argv)
    if arguments.command == "api":
        return _run_api(arguments)
    if arguments.command == "worker":
        return _run_worker()
    if arguments.command == "migrate":
        return _run_migrations()
    if arguments.command == "probe":
        return _run_probe(arguments)
    if arguments.command == "fake-telegram-serve":
        return _run_fake_telegram_serve(arguments)
    raise AssertionError(f"Unhandled command: {arguments.command}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bento-sidecar")
    subparsers = parser.add_subparsers(dest="command", required=True)

    api = subparsers.add_parser("api", help="run the local Bento API")
    api.add_argument("--host", help=argparse.SUPPRESS)
    api.add_argument("--port", type=int, help="headless only; the desktop API always binds an OS-assigned port")
    api.add_argument(
        "--ephemeral",
        action="store_true",
        help="headless only: bind an OS-assigned loopback port and print BENTO_API_READY {\"port\":N}",
    )
    subparsers.add_parser("worker", help="run the Bento background worker")
    subparsers.add_parser("migrate", help="upgrade the local database schema")

    probe = subparsers.add_parser("probe", help="run one bounded, secret-free capability probe")
    probe.add_argument(
        "kind",
        choices=("runtime", "writable-directory", "model-file", "ffmpeg", "ocr", "telegram"),
    )
    probe.add_argument("--path")

    fake = subparsers.add_parser(
        "fake-telegram-serve", help="development only: serve a fake Telegram cloud directory over HTTP"
    )
    fake.add_argument("--dir", required=True, help="fake cloud directory (shared with local processes)")
    fake.add_argument("--port", type=int, default=0, help="TCP port (0: OS-assigned, printed on stdout)")
    fake.add_argument("--host", default="127.0.0.1", help="bind address (an emulator reaches the host as 10.0.2.2)")
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
    if arguments.ephemeral:
        if arguments.port is not None:
            raise SystemExit("--ephemeral binds a port chosen by the operating system; do not pass --port")
        if host not in _LOOPBACK_HOSTS:
            raise SystemExit("--ephemeral API must bind to an explicit loopback address")
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
    try:
        port = int(listener.getsockname()[1])
        config = uvicorn.Config(app, host=host, port=port, reload=False, access_log=False)
        server = _announcing_server(config, lambda: announce_ready(port))
        server.run(sockets=[listener])
        started = server.started
    finally:
        listener.close()
    if not started:
        # Same contract as `uvicorn.run`: a failed startup is a failed process.
        raise SystemExit(3)


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
    run_migrations(get_settings(), migrations_dir=_bundle_root() / "migrations")
    return 0


def _run_fake_telegram_serve(arguments: argparse.Namespace) -> int:
    if os.environ.get("ENVIRONMENT", "local") == "production":
        raise SystemExit("fake-telegram-serve is not available in production")
    if not 0 <= arguments.port <= 65535:
        raise SystemExit("port must be between 0 and 65535")
    from bento.adapters.fake_telegram.remote import serve

    def ready(port: int) -> None:
        print(f"BENTO_FAKE_TELEGRAM_READY {json.dumps({'port': port}, separators=(',', ':'))}", flush=True)

    try:
        serve(Path(arguments.dir).expanduser(), host=arguments.host, port=arguments.port, on_ready=ready)
    except KeyboardInterrupt:
        pass
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
    return bundle_root()


if __name__ == "__main__":
    raise SystemExit(main())
