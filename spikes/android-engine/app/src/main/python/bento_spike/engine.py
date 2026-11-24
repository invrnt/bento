"""Spike stand-in for `bento.interfaces.android.engine`: configure in memory, migrate, start worker + API threads."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("bento.spike")
_state: dict[str, Any] = {}
_warm: dict[str, Any] = {}


def _home() -> Path:
    return Path(os.environ.get("HOME", "/data/local/tmp"))


def warm_up() -> str:
    """Import the backend in a fixed order (interpreter warm-up); profiled when `files/import-profile` exists."""
    if _warm:
        return json.dumps(_warm)
    profile = (_home() / "import-profile").exists()
    if profile:
        from bento_spike import importprof

        importprof.enable()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    stages: dict[str, float] = {}
    for label, module in (
        ("pydantic", "pydantic"),
        ("sqlalchemy", "sqlalchemy.orm"),
        ("fastapi", "fastapi"),
        ("cryptography", "cryptography.hazmat.primitives.ciphers.aead"),
        ("telethon", "telethon"),
        ("patches", "bento_spike.patches"),
        ("bento_http", "bento.interfaces.http.main"),
        ("bento_worker", "bento.interfaces.worker.main"),
        ("uvicorn", "uvicorn"),
        ("alembic", "alembic.command"),
    ):
        started = time.perf_counter()
        __import__(module)
        if module == "bento_spike.patches":
            from bento_spike import patches

            patches.apply()
        stages[label] = round((time.perf_counter() - started) * 1000, 1)
    if profile:
        from bento_spike import importprof

        importprof.disable()
    import sys

    _warm.update({"stages_ms": stages, "python": sys.version.split()[0], "profiled": profile})
    return json.dumps(_warm)


def start(config_json: str) -> str:
    if "port" in _state:
        return json.dumps({"port": _state["port"], "already_started": True})
    config = json.loads(config_json)
    options = config.get("options") or {}
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    warm_up()
    data_dir = Path(config["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    # Non-secret settings: process environment (as the desktop sidecars receive them).
    os.environ.update(
        {
            "BENTO_RUNTIME_MODE": "headless",
            "ENVIRONMENT": "local",
            "STORAGE_BACKEND": options.get("storage_backend", "fake"),
            "DATA_DIR": str(data_dir),
            "BENTO_FAKE_TELEGRAM_DIR": config["fake_cloud_dir"],
            "HOST": "127.0.0.1",
            "OCR_PROVIDER": "disabled",
            "EMBEDDINGS_PROVIDER": "disabled",
            "BENTO_TELEGRAM_PART_SIZE_MB": str(options.get("part_size_mb", 64)),
            "BENTO_RELAY_URL": options.get("relay_url", ""),
        }
    )
    if options.get("manual_login"):
        os.environ["BENTO_FAKE_TELEGRAM_MANUAL_LOGIN"] = "1"
    # Secrets: in memory only, never in os.environ.
    from bento.adapters.security.key_store import WRAPPING_KEY_ENV
    from bento.infrastructure import process_secrets
    from bento.interfaces.http.request_guard import API_TOKEN_ENV

    process_secrets.adopt_environment_secrets(
        (API_TOKEN_ENV, WRAPPING_KEY_ENV),
        environ={API_TOKEN_ENV: config["api_token"], WRAPPING_KEY_ENV: config["wrapping_key"]},
    )
    from bento.infrastructure.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    timings["configure_ms"] = _ms(t0)

    t1 = time.perf_counter()
    from bento.interfaces.desktop import launcher

    launcher._run_migrations()
    timings["migrations_ms"] = _ms(t1)

    t2 = time.perf_counter()
    worker_ready = threading.Event()
    threading.Thread(target=_worker_thread, args=(worker_ready,), name="bento-worker", daemon=True).start()
    worker_ready.wait(30)
    timings["worker_start_ms"] = _ms(t2)

    t3 = time.perf_counter()
    port = _start_api(settings)
    timings["api_start_ms"] = _ms(t3)
    timings["total_ms"] = _ms(t0)
    _state["port"] = port
    return json.dumps({"port": port, "timings": timings, "warm_up": _warm})


def _worker_thread(ready: threading.Event) -> None:
    from bento.interfaces.worker.main import run_worker

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    stop = asyncio.Event()
    _state["worker_loop"] = loop
    _state["worker_stop"] = stop
    loop.call_soon(ready.set)
    try:
        loop.run_until_complete(run_worker(stop))
    except Exception:
        LOGGER.exception("worker loop crashed")
    finally:
        loop.close()


def _start_api(settings: Any) -> int:
    import uvicorn

    from bento.interfaces.desktop.launcher import bind_loopback_listener
    from bento.interfaces.http.main import create_app

    listener = bind_loopback_listener("127.0.0.1")
    port = int(listener.getsockname()[1])
    config = uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, access_log=False, log_level="warning")
    server = uvicorn.Server(config)
    _state["server"] = server

    def serve() -> None:
        try:
            server.run(sockets=[listener])
        except Exception:
            LOGGER.exception("API server crashed")

    threading.Thread(target=serve, name="bento-api", daemon=True).start()
    deadline = time.monotonic() + 30
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("API did not start within 30 s")
        time.sleep(0.005)
    return port


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
