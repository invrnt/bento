"""llama-server as Bento's local embedding runtime (`EmbeddingRuntimePort`).

The worker owns one server for the active space:
- Linux/macOS: a Unix socket in `<data_dir>/run` (or a short private temp dir when that path is too long);
  Windows: `127.0.0.1` on a random free port.
- A per-launch API key in a 0600 `--api-key-file`; the key never appears in argv, files Bento writes or logs.
- `--embeddings --offline --no-ui -np 1` plus pooling, `-c`/`-ub`/`-b` from the manifest and `-t`/`-tb` threads.
- An allowlisted environment (`child_environment()`), no stdin, output discarded: request bodies are never logged.
- Crash/restart backoff of 1 s → 60 s over 5 tries; then `LlamaServerStartError` (the caller's `error(runtime)`).
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from bento.adapters.runtime.local_http import LocalHttpError, request, unix_base_url
from bento.domain.smart_search import EmbeddingSpace, ModelSpec
from bento.infrastructure.child_processes import child_environment, resolve_executable
from bento.ports.models import EndpointInfo

LOGGER = logging.getLogger("bento.embeddings.runtime")

PACKAGED_BINARY_ENV = "BENTO_LLAMA_SERVER_PATH"
BINARY_NAME = "llama-server"
BACKOFF_SECONDS: tuple[float, ...] = (1.0, 3.0, 8.0, 22.0, 60.0)
STABLE_SECONDS = 120.0
STARTUP_TIMEOUT_SECONDS = 180.0
_MAX_UNIX_SOCKET_PATH = 100  # sun_path is 104 bytes on macOS, 108 on Linux
_LEGACY_ENDPOINT_SUFFIXES = ("/v1/embeddings", "/embeddings", "/v1")


class LlamaServerError(RuntimeError):
    pass


class LlamaServerUnavailableError(LlamaServerError):
    """Nothing to retry: the binary or the weights are missing."""


class LlamaServerStartError(LlamaServerError):
    """The server did not start, or kept crashing after the restart budget."""


def resolve_llama_server_binary(
    setting_path: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    windows: bool | None = None,
    frozen_root: str | Path | None = None,
) -> Path | None:
    """Where `llama-server` is, first match wins:

    1. the `llama_server_path` setting (Advanced: an explicit override by the person);
    2. `BENTO_LLAMA_SERVER_PATH` (set by the desktop host for its bundled binary);
    3. the frozen sidecar's own copy, `sys._MEIPASS/llama-server/llama-server[.exe]`;
    4. `PATH`.

    `frozen_root` defaults to `sys._MEIPASS` (absent outside a PyInstaller bundle)."""
    source = os.environ if environ is None else environ
    is_windows = sys.platform == "win32" if windows is None else windows
    root = getattr(sys, "_MEIPASS", None) if frozen_root is None else frozen_root
    bundled = _bundled_binary(root, windows=is_windows)
    for candidate in (setting_path, source.get(PACKAGED_BINARY_ENV), bundled):
        resolved = _executable(candidate)
        if resolved is not None:
            return resolved
    found = resolve_executable(BINARY_NAME, environ=source, windows=windows)
    return Path(found) if found else None


def _bundled_binary(root: str | Path | None, *, windows: bool) -> str | None:
    if not root:
        return None
    name = f"{BINARY_NAME}.exe" if windows else BINARY_NAME
    return str(Path(root) / BINARY_NAME / name)


def _executable(value: str | None) -> Path | None:
    if not value or not value.strip():
        return None
    path = Path(value.strip()).expanduser()
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        return None
    return path


def normalize_server_url(value: str | None) -> str | None:
    """`embedding_server_url` → base URL (`http://host:port[/prefix]`), accepting the old `/v1/embeddings` form."""
    text = (value or "").strip().rstrip("/")
    if not text:
        return None
    for suffix in _LEGACY_ENDPOINT_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].rstrip("/")
            break
    return text or None


def build_argv(
    binary: Path,
    spec: ModelSpec,
    weights: Path,
    *,
    threads: int,
    host: str,
    port: int | None,
    key_file: Path,
    command_prefix: Sequence[str] = (),
) -> list[str]:
    """The exact llama-server command line (flags measured at b12777; `--no-ui` replaces `--no-webui`)."""
    argv = [
        *command_prefix,
        str(binary),
        "-m",
        str(weights),
        "--embeddings",
        "--pooling",
        spec.pooling.value,
        "-c",
        str(spec.context_tokens),
        "-ub",
        str(spec.ubatch_tokens),
        "-b",
        str(spec.ubatch_tokens),
        "-np",
        "1",
        "-t",
        str(threads),
        "-tb",
        str(threads),
        "--host",
        host,
    ]
    if port is not None:
        argv += ["--port", str(port)]
    argv += ["--api-key-file", str(key_file), "--no-ui", "--offline"]
    return argv


class LlamaServerProcess:
    """Spawns, health-checks, restarts and stops one llama-server child."""

    def __init__(
        self,
        *,
        run_dir: Path,
        binary: Path | None,
        threads: int,
        use_unix_socket: bool | None = None,
        command_prefix: Sequence[str] = (),
        backoff_seconds: Sequence[float] = BACKOFF_SECONDS,
        backoff_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        startup_timeout_seconds: float = STARTUP_TIMEOUT_SECONDS,
        poll_interval_seconds: float = 0.1,
        stop_timeout_seconds: float = 10.0,
        stable_seconds: float = STABLE_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        if threads < 1:
            raise ValueError("threads must be positive")
        self._run_dir = run_dir.expanduser().resolve()
        self._binary = binary
        self._threads = threads
        self._unix = (sys.platform != "win32") if use_unix_socket is None else use_unix_socket
        self._prefix = tuple(command_prefix)
        self._backoff = tuple(backoff_seconds)
        self._backoff_sleep = backoff_sleep
        self._startup_timeout = startup_timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._stop_timeout = stop_timeout_seconds
        self._stable_seconds = stable_seconds
        self._monotonic = monotonic
        self._environ = environ
        self._lock: asyncio.Lock | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._current: EndpointInfo | None = None
        self._launched_for: tuple[str, str, Path] | None = None
        self._key_file: Path | None = None
        self._socket_path: Path | None = None
        self._socket_dir: Path | None = None
        self._started_at = 0.0
        self._failures = 0

    @property
    def failures(self) -> int:
        """Consecutive failed starts or crashes since the last stable run (or `stop()`)."""
        return self._failures

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    def endpoint(self) -> EndpointInfo | None:
        return self._current

    async def ensure(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> EndpointInfo:
        async with self._guard():
            current = self._current
            wanted = (spec.model_id, spec.revision, weights)
            if current is not None and self._launched_for == wanted:
                if self._alive():
                    if await self._probe(current.base_url):
                        if current.space_id != space.id:  # another Matryoshka dims of the same model
                            current = replace(current, space_id=space.id)
                            self._current = current
                        return current
                    LOGGER.warning("The embedding server stopped answering; restarting it")
                else:
                    LOGGER.warning("The embedding server exited unexpectedly; restarting it")
                self._failures += 1
            await self._terminate()
            return await self._start_with_backoff(spec, space, weights)

    async def health(self) -> bool:
        proc, current = self._proc, self._current
        if proc is None or current is None:
            return False
        if proc.poll() is not None:
            LOGGER.warning("The embedding server exited unexpectedly (code %s)", proc.returncode)
            self._failures += 1
            await self._terminate()
            return False
        if not await self._probe(current.base_url):
            return False
        if self._failures and self._monotonic() - self._started_at >= self._stable_seconds:
            self._failures = 0
        return True

    async def stop(self) -> None:
        async with self._guard():
            await self._terminate()
            self._failures = 0

    def terminate_stale(self, info: EndpointInfo) -> None:
        """Stop a server left behind by a killed worker (Linux: only if its argv names that key file)."""
        pid = info.pid
        if pid is None or pid == os.getpid() or pid == self.pid:
            return
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except OSError:
            cmdline = []
        if os.fsencode(str(info.api_key_file)) in cmdline:
            try:
                os.kill(pid, signal.SIGTERM)
                LOGGER.info("Stopped a leftover embedding server (pid %s)", pid)
            except OSError:
                pass
        if info.api_key_file.parent == self._run_dir:
            info.api_key_file.unlink(missing_ok=True)

    # ----------------------------------------------------------------------------------

    def _guard(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    async def _start_with_backoff(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> EndpointInfo:
        if self._binary is None:
            raise LlamaServerUnavailableError("llama-server was not found")
        if not weights.is_file():
            raise LlamaServerUnavailableError("The embedding model file is missing")
        while True:
            if self._failures:
                if self._failures > len(self._backoff):
                    raise LlamaServerStartError("The embedding server could not be started")
                delay = self._backoff[self._failures - 1]
                LOGGER.warning(
                    "Starting the embedding server again in %.0f s (try %s of %s)",
                    delay,
                    self._failures,
                    len(self._backoff),
                )
                await self._backoff_sleep(delay)
            try:
                return await self._launch(self._binary, spec, space, weights)
            except LlamaServerStartError as exc:
                self._failures += 1
                LOGGER.warning("The embedding server did not start: %s", exc)

    async def _launch(self, binary: Path, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> EndpointInfo:
        self._run_dir.mkdir(parents=True, exist_ok=True)
        _restrict(self._run_dir, 0o700)
        tag = secrets.token_hex(4)
        key_file = self._run_dir / f"embedder-{tag}.key"
        _write_secret(key_file, secrets.token_urlsafe(32))
        self._key_file = key_file
        port: int | None
        if self._unix:
            socket_path = self._new_socket_path(tag)
            self._socket_path = socket_path
            host, port, base_url = str(socket_path), None, unix_base_url(str(socket_path))
        else:
            port = _free_loopback_port()
            host, base_url = "127.0.0.1", f"http://127.0.0.1:{port}"
        argv = build_argv(
            binary,
            spec,
            weights,
            threads=self._threads,
            host=host,
            port=port,
            key_file=key_file,
            command_prefix=self._prefix,
        )
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=child_environment(self._environ),
                cwd=str(self._run_dir),
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            self._cleanup_files()
            raise LlamaServerStartError(f"could not run llama-server ({exc.__class__.__name__})") from exc
        self._proc = proc
        await self._wait_ready(proc, base_url)
        self._started_at = self._monotonic()
        self._launched_for = (spec.model_id, spec.revision, weights)
        self._current = EndpointInfo(
            space_id=space.id,
            base_url=base_url,
            api_key_file=key_file,
            pid=proc.pid,
            started_at=datetime.now(UTC).isoformat(),
        )
        LOGGER.info("Embedding server ready for %s (pid %s, %s threads)", space.id, proc.pid, self._threads)
        return self._current

    async def _wait_ready(self, proc: subprocess.Popen[bytes], base_url: str) -> None:
        deadline = self._monotonic() + self._startup_timeout
        while True:
            code = proc.poll()
            if code is not None:
                await self._terminate()
                raise LlamaServerStartError(f"llama-server exited with code {code}")
            if await self._probe(base_url):
                return
            if self._monotonic() >= deadline:
                await self._terminate()
                raise LlamaServerStartError("llama-server did not become ready in time")
            await asyncio.sleep(self._poll_interval)

    async def _probe(self, base_url: str) -> bool:
        try:
            response = await asyncio.to_thread(request, base_url, "GET", "/health", timeout=5.0)
        except LocalHttpError:
            return False
        return response.status == 200  # 503 while the model loads

    async def _terminate(self) -> None:
        proc = self._proc
        self._proc = None
        self._current = None
        self._launched_for = None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                await asyncio.to_thread(proc.wait, self._stop_timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                await asyncio.to_thread(proc.wait, 5.0)
        self._cleanup_files()

    def _cleanup_files(self) -> None:
        if self._key_file is not None:
            self._key_file.unlink(missing_ok=True)
            self._key_file = None
        if self._socket_path is not None:
            self._socket_path.unlink(missing_ok=True)
            self._socket_path = None
        if self._socket_dir is not None:
            shutil.rmtree(self._socket_dir, ignore_errors=True)
            self._socket_dir = None

    def _new_socket_path(self, tag: str) -> Path:
        candidate = self._run_dir / f"embedder-{tag}.sock"
        if len(os.fsencode(str(candidate))) <= _MAX_UNIX_SOCKET_PATH:
            return candidate
        short_dir = Path(tempfile.mkdtemp(prefix="bento-emb-"))  # created 0700
        self._socket_dir = short_dir
        return short_dir / "embedder.sock"


class ExternalEmbeddingServer:
    """`embedding_server_url` is set: Bento spawns nothing and sends no key."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 5.0) -> None:
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._current: EndpointInfo | None = None

    async def ensure(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> EndpointInfo:
        del spec, weights
        if not await self.health_of(self._base_url):
            raise LlamaServerStartError("The configured embedding server is not reachable")
        if self._current is None or self._current.space_id != space.id:
            self._current = EndpointInfo(
                space_id=space.id,
                base_url=self._base_url,
                api_key_file=Path(""),
                pid=None,
                started_at=datetime.now(UTC).isoformat(),
            )
        return self._current

    async def stop(self) -> None:
        self._current = None

    async def health(self) -> bool:
        return self._current is not None and await self.health_of(self._base_url)

    def endpoint(self) -> EndpointInfo | None:
        return self._current

    async def health_of(self, base_url: str) -> bool:
        try:
            response = await asyncio.to_thread(request, base_url, "GET", "/health", timeout=self._timeout)
        except LocalHttpError:
            return False
        # Other OpenAI-shape servers may lack `/health`; reachable is enough unless it says it is loading.
        return response.status < 500


def _write_secret(path: Path, value: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value)


def _restrict(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
