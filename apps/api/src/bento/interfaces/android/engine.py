"""Embedded engine entrypoints called from Kotlin through Chaquopy (`api/android-endpoints.md` §1).

Plain functions with JSON-serializable arguments and results. The API (uvicorn) and the worker each run on their
own thread with their own asyncio loop, mirroring the desktop's two sidecars. Secrets arrive in memory
(`configure`), never through `os.environ` or files, and `.env` is never read.

Nothing here imports FastAPI, uvicorn, alembic, or Telethon at module import time: `configure` and `migrate`
stay cheap, and the API's imports happen in `start_api`.
"""

from __future__ import annotations

import asyncio
import gc
import hashlib
import hmac
import json
import logging
import logging.handlers
import tempfile
import threading
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bento.infrastructure import process_secrets, services
from bento.infrastructure.settings import Settings, install_settings, load_effective_settings

if TYPE_CHECKING:
    import socket

    import uvicorn

    from bento.adapters.android.host import AndroidHost
    from bento.interfaces.worker.runtime import WorkerRuntime

LOGGER = logging.getLogger("bento.android.engine")

WRAPPING_KEY_BYTES = 32
API_START_TIMEOUT_SECONDS = 30.0
WORKER_RESTART_BACKOFF_SECONDS = (1.0, 5.0, 30.0)
EVENT_KINDS = frozenset({"media_changed", "conditions", "access_changed", "low_memory"})
REQUIRED_KEYS = ("data_dir", "platform", "api_token", "wrapping_key")
KNOWN_KEYS = frozenset(
    {
        *REQUIRED_KEYS,
        "no_backup_dir",
        "cache_dir",
        "environment",
        "storage_backend",
        "telegram_api_id",
        "telegram_api_hash",
        "relay_url",
        "site_url",
        "app_version",
        "device_name_default",
        "migrations_dir",
        "fake_telegram_dir",
        "fake_telegram_url",
        "settings",
        "openapi",
        "bridges",
    }
)
# Debug-only `config["settings"]` overrides (environment aliases of non-secret settings).
_ALLOWED_OVERRIDES = frozenset(
    {"BENTO_TELEGRAM_PART_SIZE_MB", "BENTO_FAKE_TELEGRAM_MANUAL_LOGIN", "OCR_PROVIDER", "EMBEDDINGS_PROVIDER"}
)


class EngineConfigError(ValueError):
    """`configure` was called with invalid input, or with a configuration different from the active one."""


class EngineStateError(RuntimeError):
    """An entrypoint was called out of order (for example `migrate` before `configure`)."""


@dataclass
class _Engine:
    lock: threading.RLock = field(default_factory=threading.RLock)
    fingerprint: str | None = None
    settings: Settings | None = None
    host: AndroidHost | None = None
    migrations_dir: Path | None = None
    openapi: bool = False
    api_server: uvicorn.Server | None = None
    api_thread: threading.Thread | None = None
    api_port: int | None = None
    worker_thread: threading.Thread | None = None
    worker_loop: asyncio.AbstractEventLoop | None = None
    worker_stop: asyncio.Event | None = None
    worker_runtime: WorkerRuntime | None = None
    worker_mode: str = "stopped"
    worker_ready: threading.Event = field(default_factory=threading.Event)
    stopping: bool = False
    last_error: str | None = None
    events: ThreadPoolExecutor | None = None
    log_handler: logging.Handler | None = None


_engine = _Engine()


# configure ----------------------------------------------------------------------------------------------


def configure(config: Mapping[str, Any]) -> dict[str, object]:
    """Build `Settings` from `config` (no environment, no `.env`), hold secrets in memory, install bridges.

    Idempotent for an identical configuration (same values and the same bridge instances); a different one
    raises `EngineConfigError` (stop the engine and restart the process to change it).
    """
    if not isinstance(config, Mapping):
        raise EngineConfigError("config must be a mapping")
    unknown = sorted(set(config) - KNOWN_KEYS)
    if unknown:
        raise EngineConfigError(f"Unknown config keys: {unknown}")
    missing = [key for key in REQUIRED_KEYS if config.get(key) in (None, "")]
    if missing:
        raise EngineConfigError(f"Missing config keys: {missing}")
    if config["platform"] != "android":
        raise EngineConfigError("platform must be 'android'")
    from bento.interfaces.http.request_guard import API_TOKEN_ENV, MIN_TOKEN_LENGTH

    token = str(config["api_token"])
    if len(token) < MIN_TOKEN_LENGTH:
        raise EngineConfigError(f"api_token must contain at least {MIN_TOKEN_LENGTH} characters")
    wrapping_key = _wrapping_key(config["wrapping_key"])
    bridges = config.get("bridges") or {}
    if not isinstance(bridges, Mapping):
        raise EngineConfigError("bridges must be a mapping")
    fingerprint = _fingerprint(config, token, wrapping_key, bridges)

    with _engine.lock:
        if _engine.fingerprint is not None:
            if hmac.compare_digest(_engine.fingerprint, fingerprint):
                return _configured_summary()
            raise EngineConfigError("The engine is already configured differently; restart the process to change it")

        environ = _settings_environ(config)
        data_dir = Path(str(config["data_dir"])).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)
        base = Settings(_env_file=None, data_dir=str(data_dir), runtime_mode="headless")  # type: ignore[call-arg]
        try:
            settings = load_effective_settings(base, environ=environ)
        except ValueError as exc:
            raise EngineConfigError(f"Invalid settings: {exc.__class__.__name__}") from None

        from bento.adapters.android.host import AndroidHost
        from bento.adapters.security.key_store import WRAPPING_KEY_ENV
        from bento.adapters.security.primitives import b64url_encode

        try:
            host = AndroidHost.from_bridges(dict(bridges))
        except ValueError as exc:
            raise EngineConfigError(str(exc)) from None

        cache_dir = config.get("cache_dir")
        if cache_dir:
            # Android has no /tmp; every `tempfile` user (uploads, staging) writes under the app cache.
            temporary = Path(str(cache_dir)) / "tmp"
            temporary.mkdir(parents=True, exist_ok=True)
            tempfile.tempdir = str(temporary)
        no_backup_dir = config.get("no_backup_dir")
        if no_backup_dir:
            _engine.log_handler = _install_log_file(Path(str(no_backup_dir)) / "logs")

        process_secrets.put(API_TOKEN_ENV, token)
        process_secrets.put(WRAPPING_KEY_ENV, b64url_encode(wrapping_key))
        services.reset_services()
        install_settings(settings)
        services.install_android_host(host)
        migrations_dir = config.get("migrations_dir")
        _engine.migrations_dir = Path(str(migrations_dir)) if migrations_dir else None
        _engine.openapi = bool(config.get("openapi", settings.environment != "production"))
        _engine.settings = settings
        _engine.host = host
        _engine.fingerprint = fingerprint
        _engine.stopping = False
        return _configured_summary()


def _settings_environ(config: Mapping[str, Any]) -> dict[str, str]:
    """Environment-style aliases for `load_effective_settings`: fixed by the host, so locked (headless rules)."""
    values: dict[str, Any] = {
        "BENTO_PLATFORM": "android",
        "BENTO_RUNTIME_MODE": "headless",
        "HOST": "127.0.0.1",
        "DATA_DIR": str(config["data_dir"]),
        "ENVIRONMENT": config.get("environment") or "production",
        "STORAGE_BACKEND": config.get("storage_backend") or "telegram",
        "BENTO_TELEGRAM_API_ID": config.get("telegram_api_id"),
        "BENTO_TELEGRAM_API_HASH": config.get("telegram_api_hash"),
        "BENTO_RELAY_URL": config.get("relay_url"),
        "BENTO_PUBLIC_SITE_URL": config.get("site_url"),
        "APP_VERSION": config.get("app_version"),
        "BENTO_DEVICE_NAME": config.get("device_name_default"),
        "BENTO_FAKE_TELEGRAM_DIR": config.get("fake_telegram_dir"),
        "BENTO_FAKE_TELEGRAM_URL": config.get("fake_telegram_url"),
    }
    overrides = config.get("settings") or {}
    if not isinstance(overrides, Mapping):
        raise EngineConfigError("settings must be a mapping")
    for key, value in overrides.items():
        if key not in _ALLOWED_OVERRIDES:
            raise EngineConfigError(f"Setting {key} cannot be overridden")
        values[key] = value
    environ = {key: str(value) for key, value in values.items() if value is not None and str(value) != ""}
    if environ["ENVIRONMENT"] == "production" and (
        environ["STORAGE_BACKEND"] == "fake" or "BENTO_FAKE_TELEGRAM_URL" in environ
    ):
        raise EngineConfigError("The fake Telegram backend cannot be used in production")
    return environ


def _wrapping_key(value: object) -> bytes:
    if isinstance(value, str):
        from bento.adapters.security.primitives import b64url_decode

        try:
            key = b64url_decode(value.strip())
        except Exception:  # noqa: BLE001 - never echo key material
            raise EngineConfigError("wrapping_key must be 32 bytes (or their base64url)") from None
    else:
        try:
            key = bytes(value)  # type: ignore[call-overload]  # bytes, bytearray, or a Java byte[] (jarray)
        except ValueError:
            try:  # a sequence of signed Java bytes
                key = bytes(int(byte) & 0xFF for byte in value)  # type: ignore[attr-defined]
            except (TypeError, ValueError):
                raise EngineConfigError("wrapping_key must be 32 bytes (or their base64url)") from None
        except TypeError:
            raise EngineConfigError("wrapping_key must be 32 bytes (or their base64url)") from None
    if len(key) != WRAPPING_KEY_BYTES:
        raise EngineConfigError("wrapping_key must be 32 bytes (or their base64url)")
    return key


def _fingerprint(config: Mapping[str, Any], token: str, wrapping_key: bytes, bridges: Mapping[str, Any]) -> str:
    plain = {key: config[key] for key in sorted(config) if key not in {"api_token", "wrapping_key", "bridges"}}
    material = json.dumps(plain, sort_keys=True, default=str).encode()
    digest = hashlib.sha256(material)
    digest.update(hashlib.sha256(token.encode()).digest())
    digest.update(hashlib.sha256(wrapping_key).digest())
    digest.update(json.dumps(sorted((key, id(value)) for key, value in bridges.items())).encode())
    return digest.hexdigest()


def _configured_summary() -> dict[str, object]:
    settings = _require_settings()
    return {
        "platform": settings.platform,
        "environment": settings.environment,
        "storage_backend": settings.storage_backend,
        "bridges": sorted(key for key, value in (_engine.host.bridges if _engine.host else {}).items() if value is not None),
    }


# migrate ------------------------------------------------------------------------------------------------


def migrate() -> dict[str, object]:
    """Upgrade the catalog to head: `{from, to, ran, ms}`; no alembic import when already at head."""
    from bento.infrastructure.db.migrate import run_migrations

    settings = _require_settings()
    return run_migrations(settings, migrations_dir=_engine.migrations_dir).as_dict()


# API ----------------------------------------------------------------------------------------------------


def start_api() -> int:
    """Serve the HTTP API on an ephemeral `127.0.0.1` port (bearer token required); returns it once accepting."""
    with _engine.lock:
        settings = _require_settings()
        if _engine.api_thread is not None and _engine.api_thread.is_alive() and _engine.api_port is not None:
            return _engine.api_port
        _engine.stopping = False

        import uvicorn

        from bento.infrastructure.loopback import bind_loopback_listener
        from bento.interfaces.http.main import create_app

        app = create_app(settings, guard_environ={}, openapi=_engine.openapi)
        listener = bind_loopback_listener("127.0.0.1")
        port = int(listener.getsockname()[1])
        config = uvicorn.Config(
            app, host="127.0.0.1", port=port, access_log=False, log_level="warning", lifespan="on", http="h11"
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=_serve_api, args=(server, listener), name="bento-api", daemon=True)
        _engine.api_server, _engine.api_thread, _engine.api_port = server, thread, port
        thread.start()
    deadline = time.monotonic() + API_START_TIMEOUT_SECONDS
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            with _engine.lock:
                _engine.api_port = None
                _engine.last_error = _engine.last_error or "api_start_failed"
            raise EngineStateError("The API did not start")
        time.sleep(0.005)
    return port


def _serve_api(server: uvicorn.Server, listener: socket.socket) -> None:
    try:
        server.run(sockets=[listener])
    except Exception as exc:  # noqa: BLE001 - recorded for `status()`; Kotlin restarts the engine
        LOGGER.exception("API server crashed")
        _record_error("api", exc)
    finally:
        listener.close()
        with _engine.lock:
            if _engine.api_server is server:
                _engine.api_port = None


# worker -------------------------------------------------------------------------------------------------


def start_worker(mode: str = "full") -> dict[str, object]:
    """`full`: job loop, Inbox and sync loops (app visible). `drain`: jobs only inside `run_worker_until`.

    Switching modes restarts the worker thread at a job boundary."""
    if mode not in ("full", "drain"):
        raise EngineConfigError("mode must be 'full' or 'drain'")
    with _engine.lock:
        settings = _require_settings()
        if _worker_alive():
            if _engine.worker_mode == mode:
                return {"worker": mode, "started": False}
            _stop_worker(timeout=30.0)
        from bento.interfaces.worker.runtime import WorkerRuntime

        _engine.stopping = False
        runtime = WorkerRuntime(settings, mode=mode)  # type: ignore[arg-type]
        _engine.worker_ready = threading.Event()
        thread = threading.Thread(target=_worker_main, args=(runtime,), name="bento-worker", daemon=True)
        _engine.worker_runtime, _engine.worker_thread, _engine.worker_mode = runtime, thread, mode
        thread.start()
        ready = _engine.worker_ready
    ready.wait(API_START_TIMEOUT_SECONDS)
    return {"worker": mode, "started": True}


def _worker_main(runtime: WorkerRuntime) -> None:
    """The worker thread: restarts a crashed loop with backoff (1, 5, 30 s) until `stop()`."""
    failures: list[float] = []
    while True:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        stop_event = asyncio.Event()
        with _engine.lock:
            _engine.worker_loop, _engine.worker_stop = loop, stop_event
        loop.call_soon(_engine.worker_ready.set)
        crashed = False
        try:
            loop.run_until_complete(runtime.run(stop_event))
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Worker loop crashed")
            _record_error("worker", exc)
            crashed = True
        finally:
            with _engine.lock:
                if _engine.worker_loop is loop:
                    _engine.worker_loop = None
            loop.close()
        with _engine.lock:
            if _engine.stopping or not crashed or _engine.worker_runtime is not runtime:
                return
        now = time.monotonic()
        failures = [moment for moment in failures if now - moment < 300] + [now]
        time.sleep(WORKER_RESTART_BACKOFF_SECONDS[min(len(failures), len(WORKER_RESTART_BACKOFF_SECONDS)) - 1])


def run_worker_until(deadline_epoch_ms: int, kinds: list[str] | None = None) -> dict[str, object]:
    """Run eligible jobs until `deadline_epoch_ms` (wall clock) or none is eligible; blocks the calling thread.

    Returns `{ran, remaining, next_eligible_at, stopped_reason: idle|deadline|conditions|error, waiting}`;
    `next_eligible_at` is epoch ms or None. Starts the worker in `drain` mode when it is not running."""
    if not _worker_alive():
        start_worker("drain")
    with _engine.lock:
        loop, runtime = _engine.worker_loop, _engine.worker_runtime
    if loop is None or runtime is None:
        raise EngineStateError("The worker is not running")
    kinds_list = None if kinds is None else [str(kind) for kind in kinds]
    future = asyncio.run_coroutine_threadsafe(runtime.run_until(int(deadline_epoch_ms), kinds_list), loop)
    budget = max(0.0, int(deadline_epoch_ms) / 1000 - time.time())
    try:
        result = future.result(timeout=budget + 60.0)
    except TimeoutError:
        future.cancel()
        return {"ran": 0, "remaining": None, "next_eligible_at": None, "stopped_reason": "error", "waiting": {}}
    return result.as_dict()


# stop / events / status -----------------------------------------------------------------------------------


def stop(timeout_ms: int = 10_000) -> dict[str, object]:
    """Stop the API and the worker (the current job step finishes); Telethon clients close with their loops."""
    timeout = max(0.1, int(timeout_ms) / 1000)
    with _engine.lock:
        _engine.stopping = True
        server, api_thread = _engine.api_server, _engine.api_thread
    if server is not None:
        server.should_exit = True
    if api_thread is not None:
        api_thread.join(timeout)
    worker_stopped = _stop_worker(timeout=timeout)
    with _engine.lock:
        _engine.api_server = _engine.api_thread = None
        _engine.api_port = None
        api_stopped = api_thread is None or not api_thread.is_alive()
    return {"api_stopped": api_stopped, "worker_stopped": worker_stopped}


def _stop_worker(*, timeout: float) -> bool:
    with _engine.lock:
        loop, stop_event, thread = _engine.worker_loop, _engine.worker_stop, _engine.worker_thread
        _engine.worker_runtime = None
    if loop is not None and stop_event is not None and not loop.is_closed():
        try:
            loop.call_soon_threadsafe(stop_event.set)
        except RuntimeError:
            pass
    if thread is not None:
        thread.join(timeout)
    stopped = thread is None or not thread.is_alive()
    with _engine.lock:
        if stopped:
            _engine.worker_thread = None
            _engine.worker_mode = "stopped"
    return stopped


def on_event(kind: str, payload_json: str = "") -> bool:
    """Thread-safe, non-blocking hand-off from Kotlin (`media_changed`, `conditions`, `access_changed`,
    `low_memory`). Returns False for an unknown kind or before `configure`."""
    if kind not in EVENT_KINDS:
        return False
    with _engine.lock:
        if _engine.settings is None:
            return False
        if _engine.events is None:
            _engine.events = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bento-events")
        executor = _engine.events
    executor.submit(_handle_event, kind, payload_json or "")
    return True


def _handle_event(kind: str, payload_json: str) -> None:
    try:
        host = _engine.host
        if kind == "conditions" and host is not None and host.conditions is not None:
            host.conditions.update(payload_json)
        elif kind in {"media_changed", "access_changed"} and host is not None:
            host.watcher.notify(_bucket_ids(payload_json) if kind == "media_changed" else None)
        elif kind == "low_memory":
            gc.collect()
        _wake_worker()
    except Exception:  # noqa: BLE001 - an event never takes the engine down
        LOGGER.warning("Engine event %s failed", kind, exc_info=True)


def _bucket_ids(payload_json: str) -> frozenset[str] | None:
    try:
        payload = json.loads(payload_json) if payload_json else {}
    except ValueError:
        return None
    ids = payload.get("bucket_ids") if isinstance(payload, dict) else None
    return frozenset(str(value) for value in ids) if isinstance(ids, list) and ids else None


def _wake_worker() -> None:
    with _engine.lock:
        loop, runtime = _engine.worker_loop, _engine.worker_runtime
    if loop is not None and runtime is not None and not loop.is_closed():
        try:
            loop.call_soon_threadsafe(runtime.wake)
        except RuntimeError:
            pass


def status() -> dict[str, object]:
    """`{api_port, worker, telegram, last_error}`; never contains secrets."""
    with _engine.lock:
        settings = _engine.settings
        api_port = _engine.api_port if _engine.api_thread is not None and _engine.api_thread.is_alive() else None
        worker = _engine.worker_mode if _worker_alive() else "stopped"
        last_error = _engine.last_error
    return {"api_port": api_port, "worker": worker, "telegram": _telegram_state(settings, worker), "last_error": last_error}


def _telegram_state(settings: Settings | None, worker: str) -> str:
    if settings is None or not settings.telegram_configured:
        return "signed_out"
    try:
        from bento.infrastructure.mtproto import wiring

        installed = wiring.vault_installed(settings)
    except Exception:  # noqa: BLE001
        return "disconnected"
    if not installed:
        return "signed_out"
    return "connected" if worker != "stopped" else "disconnected"


# helpers ------------------------------------------------------------------------------------------------


def _require_settings() -> Settings:
    if _engine.settings is None:
        raise EngineStateError("configure() must be called first")
    return _engine.settings


def _worker_alive() -> bool:
    return _engine.worker_thread is not None and _engine.worker_thread.is_alive()


def _record_error(component: str, exc: BaseException) -> None:
    with _engine.lock:
        _engine.last_error = f"{component}:{exc.__class__.__name__}"


def _install_log_file(directory: Path) -> logging.Handler:
    directory.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(directory / "engine.log", maxBytes=1_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.setLevel(logging.INFO)
    root = logging.getLogger("bento")
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return handler


def _reset_for_tests() -> None:
    """Stop everything and forget the configuration (tests only; a real process configures once)."""
    stop(5_000)
    with _engine.lock:
        if _engine.events is not None:
            _engine.events.shutdown(wait=True)
        if _engine.log_handler is not None:
            logging.getLogger("bento").removeHandler(_engine.log_handler)
            _engine.log_handler.close()
        _engine.__init__()  # type: ignore[misc]
    services.install_android_host(None)
    install_settings(None)
    services.reset_services()
    process_secrets.clear()
    tempfile.tempdir = None
