"""TEMPORARY engine shim (agent 36). Delete when agent 35's `bento.interfaces.android.engine` merges.

Kotlin (`ChaquopyEngineRuntime`) always calls this module. When the real backend entrypoints exist they are
used as-is; otherwise this module provides the `api/android-endpoints.md` §1 functions on top of the
*unchanged* backend, with the Stage 19 spike monkeypatches (`patches.py`). Only `warm_up` stays Kotlin-facing
after the swap (move it into the real module, then point `ENGINE_MODULE` at it).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import sqlite3
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

try:  # pragma: no cover - depends on agent 35's merge
    from bento.interfaces.android import engine as _real  # type: ignore[attr-defined]
except ImportError:
    _real = None

LOGGER = logging.getLogger("bento.android.shim")
WARM_UP_ORDER = (
    ("pydantic", "pydantic"),
    ("sqlalchemy", "sqlalchemy.orm"),
    ("fastapi", "fastapi"),
    ("cryptography", "cryptography.hazmat.primitives.ciphers.aead"),
    ("bento_http", "bento.interfaces.http.main"),
    ("uvicorn", "uvicorn"),
    ("telethon", "telethon"),
    ("bento_worker", "bento.interfaces.worker.main"),
)
LOOP_BACKOFF_S = (1.0, 5.0, 30.0)

_lock = threading.RLock()
_warm: dict[str, Any] = {}
_state: dict[str, Any] = {"worker": "stopped", "last_error": None, "crashes": deque(maxlen=16)}
_events: deque[tuple[str, str]] = deque(maxlen=256)


def using_real_engine() -> bool:
    return _real is not None


def warm_up() -> str:
    """Interpreter warm-up: import the backend in a fixed order. Returns `{stages_ms, python, real_engine}`."""
    with _lock:
        if _warm:
            return json.dumps(_warm)
        if _real is None:
            from bento_engine_shim import patches

            patches.install_import_stubs()
        stages: dict[str, float] = {}
        for label, module in WARM_UP_ORDER:
            started = time.perf_counter()
            try:
                __import__(module)
            except Exception as error:  # noqa: BLE001 - warm-up must not crash the app
                stages[label] = -1.0
                LOGGER.warning("warm-up import %s failed: %s", module, type(error).__name__)
                continue
            stages[label] = round((time.perf_counter() - started) * 1000, 1)
        _warm.update({"stages_ms": stages, "python": sys.version.split()[0], "real_engine": _real is not None})
        return json.dumps(_warm)


# region contract (api/android-endpoints.md §1)
def configure(config: dict[str, Any]) -> None:
    if _real is not None:
        return _real.configure(config)
    with _lock:
        signature = _signature(config)
        if _state.get("configured"):
            if _state["configured"] != signature:
                raise EngineConfigError("configure() called again with a different configuration")
            return None
        _redirect_output(Path(config["no_backup_dir"]) / "logs", config.get("environment") == "production",
                         (config["api_token"], _b64(config["wrapping_key"])))
        _apply_settings(config)
        from bento_engine_shim import patches

        patches.apply(config.get("bridges") or {})
        _state["configured"] = signature
        _state["config"] = {k: v for k, v in config.items() if k not in {"api_token", "wrapping_key", "bridges"}}
        return None


def migrate() -> dict[str, Any]:
    if _real is not None:
        return _real.migrate()
    started = time.perf_counter()
    before = _alembic_revision()
    from bento.interfaces.desktop import launcher

    launcher._run_migrations()
    after = _alembic_revision()
    return {"from": before, "to": after, "ran": before != after, "ms": int((time.perf_counter() - started) * 1000)}


def start_api() -> int:
    if _real is not None:
        return _real.start_api()
    with _lock:
        server = _state.get("server")
        if server is not None and not server.should_exit and _state.get("api_thread") and _state["api_thread"].is_alive():
            return int(_state["api_port"])
        import uvicorn

        from bento.infrastructure.settings import get_settings
        from bento.interfaces.desktop.launcher import bind_loopback_listener
        from bento.interfaces.http.main import create_app

        listener = bind_loopback_listener("127.0.0.1")
        port = int(listener.getsockname()[1])
        config = uvicorn.Config(create_app(get_settings()), host="127.0.0.1", port=port, access_log=False,
                                log_level="warning", log_config=None)
        server = uvicorn.Server(config)

        def serve() -> None:
            try:
                server.run(sockets=[listener])
            except Exception as error:  # noqa: BLE001
                _record_crash("api", error)
            finally:
                with _lock:
                    if _state.get("server") is server:
                        _state["api_port"] = None

        thread = threading.Thread(target=serve, name="bento-api", daemon=True)
        _state.update({"server": server, "api_thread": thread, "api_port": port})
        thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("API did not start")
        time.sleep(0.005)
    return port


def start_worker(mode: str) -> None:
    if _real is not None:
        return _real.start_worker(mode)
    if mode not in {"full", "drain"}:
        raise ValueError("mode must be full or drain")
    with _lock:
        if _state["worker"] == mode:
            return None
        _stop_worker_loop(10.0)
        if mode == "full":
            ready = threading.Event()
            thread = threading.Thread(target=_full_worker_thread, args=(ready,), name="bento-worker", daemon=True)
            _state["worker_thread"] = thread
            thread.start()
            ready.wait(30)
        _state["worker"] = mode
    return None


def run_worker_until(deadline_epoch_ms: int, kinds: list[str] | None = None) -> dict[str, Any]:
    """Drain eligible jobs until the deadline. The shim ignores `kinds` (all eligible jobs run)."""
    if _real is not None:
        return _real.run_worker_until(deadline_epoch_ms, kinds)
    deadline = deadline_epoch_ms / 1000.0
    if _state["worker"] == "full":
        while time.time() < deadline:
            if _pending_jobs(eligible_only=True) == 0:
                return _run_result(0, "idle")
            time.sleep(0.5)
        return _run_result(0, "deadline")
    return asyncio.run(_drain(deadline))


def stop(timeout_ms: int) -> None:
    if _real is not None:
        return _real.stop(timeout_ms)
    timeout = max(timeout_ms, 0) / 1000.0
    with _lock:
        server = _state.pop("server", None)
        thread = _state.pop("api_thread", None)
        _state["api_port"] = None
    if server is not None:
        server.should_exit = True
    if thread is not None:
        thread.join(timeout)
    _stop_worker_loop(timeout)
    _state["worker"] = "stopped"
    return None


def on_event(kind: str, payload_json: str) -> None:
    if _real is not None:
        return _real.on_event(kind, payload_json)
    _events.append((kind, payload_json))  # deque.append is thread-safe; consumed by agent 35's adapters
    return None


def status() -> dict[str, Any]:
    if _real is not None:
        return _real.status()
    return {
        "api_port": _state.get("api_port"),
        "worker": _state["worker"],
        "telegram": "disconnected",
        "last_error": _state.get("last_error"),
    }
# endregion


class EngineConfigError(RuntimeError):
    pass


# region worker
def _full_worker_thread(ready: threading.Event) -> None:
    from bento.interfaces.worker.main import run_worker

    attempt = 0
    while True:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        stop_event = asyncio.Event()
        with _lock:
            _state["worker_loop"] = loop
            _state["worker_stop"] = stop_event
        loop.call_soon(ready.set)
        crashed = False
        try:
            loop.run_until_complete(run_worker(stop_event))
        except Exception as error:  # noqa: BLE001 - crash isolation (android-runtime.md §3)
            crashed = True
            _record_crash("worker", error)
        finally:
            loop.close()
        if not crashed or stop_event.is_set():
            return
        time.sleep(LOOP_BACKOFF_S[min(attempt, len(LOOP_BACKOFF_S) - 1)])
        attempt += 1
        with _lock:
            if _state["worker"] != "full":
                return


def _stop_worker_loop(timeout: float) -> None:
    with _lock:
        loop = _state.pop("worker_loop", None)
        stop_event = _state.pop("worker_stop", None)
        thread = _state.pop("worker_thread", None)
    if loop is not None and stop_event is not None and not loop.is_closed():
        try:
            loop.call_soon_threadsafe(stop_event.set)
        except RuntimeError:
            pass
    if thread is not None:
        thread.join(timeout)


async def _drain(deadline: float) -> dict[str, Any]:
    from bento.interfaces.worker.main import _create_dispatcher

    worker_id = f"worker-{os.getpid()}-drain"
    dispatcher = _create_dispatcher(worker_id=worker_id)
    # Jobs left `running` by a killed process are requeued (resume at part granularity via upload_sessions).
    await dispatcher.jobs.release_abandoned(worker_id)
    ran = 0
    try:
        while time.time() < deadline:
            if not await dispatcher.process_one():
                return _run_result(ran, "idle")
            ran += 1
        return _run_result(ran, "deadline")
    except Exception as error:  # noqa: BLE001
        _record_crash("drain", error)
        return _run_result(ran, "error")


def _run_result(ran: int, reason: str) -> dict[str, Any]:
    return {"ran": ran, "remaining": _pending_jobs(eligible_only=False), "next_eligible_at": _next_eligible_at(),
            "stopped_reason": reason}


def _database_path() -> Path:
    from bento.infrastructure.settings import get_settings, settings_database_path

    return settings_database_path(get_settings())


def _query(sql: str) -> Any:
    path = _database_path()
    if not path.exists():
        return None
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as db:
        row = db.execute(sql).fetchone()
        return row[0] if row else None


def _pending_jobs(*, eligible_only: bool) -> int:
    clause = " AND (run_after IS NULL OR run_after <= datetime('now'))" if eligible_only else ""
    try:
        return int(_query(f"SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running','retrying'){clause}") or 0)
    except sqlite3.Error:
        return 0


def _next_eligible_at() -> int | None:
    try:
        value = _query("SELECT MIN(run_after) FROM jobs WHERE status IN ('queued','retrying') AND run_after > datetime('now')")
    except sqlite3.Error:
        return None
    if not value:
        return None
    from datetime import datetime, timezone

    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _alembic_revision() -> str | None:
    try:
        return _query("SELECT version_num FROM alembic_version")
    except sqlite3.Error:
        return None
# endregion


# region configuration
def _apply_settings(config: dict[str, Any]) -> None:
    debug = {str(k): str(v) for k, v in (config.get("debug_options") or {}).items()}
    production = config.get("environment") == "production"
    data_dir = Path(config["no_backup_dir"]) / "bento"
    data_dir.mkdir(parents=True, exist_ok=True)
    storage_backend = str(config.get("storage_backend") or "telegram")
    if production and storage_backend == "fake":
        raise EngineConfigError("the fake backend is not available in release builds")
    values = {
        "BENTO_RUNTIME_MODE": "headless",
        "ENVIRONMENT": "production" if production else "local",
        "STORAGE_BACKEND": storage_backend,
        "DATA_DIR": str(data_dir),
        "HOST": "127.0.0.1",
        "OCR_PROVIDER": "disabled",
        "EMBEDDINGS_PROVIDER": "disabled",
        "BENTO_RELAY_URL": str(config.get("relay_url") or ""),
        "APP_VERSION": str(config.get("app_version") or ""),
    }
    if config.get("telegram_api_id"):
        # App credentials (not user secrets); the backend reads them from settings.
        values["BENTO_TELEGRAM_API_ID"] = str(config["telegram_api_id"])
        values["BENTO_TELEGRAM_API_HASH"] = str(config.get("telegram_api_hash") or "")
    if not production:
        if debug.get("fake_cloud_dir"):
            values["BENTO_FAKE_TELEGRAM_DIR"] = debug["fake_cloud_dir"]
        if debug.get("part_size_mb"):
            values["BENTO_TELEGRAM_PART_SIZE_MB"] = debug["part_size_mb"]
        if debug.get("manual_login") == "true":
            values["BENTO_FAKE_TELEGRAM_MANUAL_LOGIN"] = "1"
    os.environ.update(values)
    # Secrets: in memory only, never in os.environ (process_secrets with a private mapping).
    from bento.adapters.security.key_store import WRAPPING_KEY_ENV
    from bento.infrastructure import process_secrets
    from bento.interfaces.http.request_guard import API_TOKEN_ENV

    secrets = {API_TOKEN_ENV: config["api_token"], WRAPPING_KEY_ENV: _b64(config["wrapping_key"])}
    process_secrets.adopt_environment_secrets(tuple(secrets), environ=secrets)
    os.chdir(data_dir)  # dotenv_values(".env") reads cwd; never `/` on Android
    from bento.infrastructure.settings import get_settings

    get_settings.cache_clear()


def _signature(config: dict[str, Any]) -> str:
    stable = {k: v for k, v in config.items() if k not in {"bridges", "wrapping_key"}}
    stable["wrapping_key"] = hashlib.sha256(bytes(config["wrapping_key"])).hexdigest()
    return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()


def _b64(value: Any) -> str:
    return base64.urlsafe_b64encode(bytes(value)).rstrip(b"=").decode("ascii")


def _record_crash(loop: str, error: BaseException) -> None:
    from bento_engine_shim.redaction import redact

    message = redact(f"{loop}: {type(error).__name__}: {error}")
    _state["last_error"] = message
    _state["crashes"].append((time.time(), loop))
    LOGGER.error("loop crashed: %s", message)


def _redirect_output(log_dir: Path, production: bool, secrets: tuple[str, ...]) -> None:
    from bento_engine_shim.redaction import install

    install(log_dir, mirror=not production, secrets=secrets)
# endregion
