"""The llama-server process adapter against `tests/fakes/fake_llama_server_bin.py` (a real child process)."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import stat
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from bento.adapters.embeddings import LlamaCppEmbeddingProvider
from bento.adapters.runtime.llama_server_process import (
    BACKOFF_SECONDS,
    PACKAGED_BINARY_ENV,
    ExternalEmbeddingServer,
    LlamaServerProcess,
    LlamaServerStartError,
    LlamaServerUnavailableError,
    normalize_server_url,
    resolve_llama_server_binary,
)
from bento.application.smart_search.runtime import RuntimeTarget, SmartSearchRuntimeService, endpoint_file_path
from bento.domain.smart_search import parse_manifest
from tests.fakes.llama_server import FakeLlamaServer

FAKE_BIN = Path(__file__).parents[2] / "fakes" / "fake_llama_server_bin.py"
MANIFEST = json.loads(
    (Path(__file__).parents[2] / "unit" / "smart_search" / "manifest_v1.json").read_text(encoding="utf-8")
)
SPECS, _ = parse_manifest(MANIFEST)
EG2 = SPECS[0]
POSIX = sys.platform != "win32"


@dataclass
class Sleeps:
    delays: list[float]

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


@pytest.fixture
def run_dir() -> Iterator[Path]:
    """Short, so the Unix socket lives in the run dir like in a real profile."""
    base = "/tmp" if os.path.isdir("/tmp") else None
    path = Path(tempfile.mkdtemp(prefix="bento-run-", dir=base))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def weights_with(tmp_path: Path, **control: Any) -> Path:
    weights = tmp_path / "embeddinggemma-2-Q8_0.gguf"
    weights.write_bytes(b"GGUF")
    control.setdefault("dims", 768)
    Path(f"{weights}.fake.json").write_text(json.dumps(control), encoding="utf-8")
    return weights


def launches(weights: Path) -> list[dict[str, Any]]:
    path = Path(f"{weights}.launches.jsonl")
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def process(run_dir: Path, sleeps: Sleeps, **overrides: Any) -> LlamaServerProcess:
    options: dict[str, Any] = {
        "run_dir": run_dir,
        "binary": FAKE_BIN,
        "threads": 2,
        "command_prefix": (sys.executable,),
        "backoff_sleep": sleeps,
        "startup_timeout_seconds": 20.0,
        "poll_interval_seconds": 0.02,
        "stop_timeout_seconds": 5.0,
        "environ": {"PATH": os.environ.get("PATH", ""), "BENTO_SECRET_SENTINEL": "must-not-leak"},
    }
    options.update(overrides)
    return LlamaServerProcess(**options)


def flag(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


def test_argv_flags_key_file_and_environment(tmp_path: Path, run_dir: Path) -> None:
    async def scenario() -> None:
        weights = weights_with(tmp_path)
        runtime = process(run_dir, Sleeps([]))
        try:
            info = await runtime.ensure(EG2, EG2.space(), weights)

            (launch,) = launches(weights)
            argv = launch["argv"]
            assert flag(argv, "-m") == str(weights)
            assert "--embeddings" in argv and "--offline" in argv and "--no-ui" in argv
            assert "--no-webui" not in argv
            assert flag(argv, "--pooling") == "mean"
            assert (flag(argv, "-c"), flag(argv, "-ub"), flag(argv, "-b")) == ("2048", "2048", "2048")
            assert flag(argv, "-np") == "1"
            assert (flag(argv, "-t"), flag(argv, "-tb")) == ("2", "2")
            key_file = Path(flag(argv, "--api-key-file"))
            assert key_file.parent == run_dir.resolve() and info.api_key_file == key_file
            key = key_file.read_text(encoding="utf-8").strip()
            assert key and all(key not in part for part in argv)
            if POSIX:
                assert launch["key_file_mode"] == 0o600
                assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
                host = flag(argv, "--host")
                assert host.endswith(".sock") and Path(host).parent == run_dir.resolve()
                assert "--port" not in argv
                assert info.base_url == f"http+unix://{host}"
            assert "BENTO_SECRET_SENTINEL" not in launch["env_keys"]
            assert info.space_id == EG2.space().id and info.pid == runtime.pid

            provider = LlamaCppEmbeddingProvider(spec=EG2, space=EG2.space(), endpoint=runtime.endpoint)
            assert len(await provider.embed_query("factura de la luz")) == 512
        finally:
            await runtime.stop()

        assert runtime.endpoint() is None
        assert not key_file.exists()
        if POSIX:
            assert not Path(host).exists()

    asyncio.run(scenario())


def test_loopback_with_a_random_port(tmp_path: Path, run_dir: Path) -> None:
    async def scenario() -> None:
        weights = weights_with(tmp_path)
        runtime = process(run_dir, Sleeps([]), use_unix_socket=False)
        try:
            info = await runtime.ensure(EG2, EG2.space(), weights)
            argv = launches(weights)[0]["argv"]
            assert flag(argv, "--host") == "127.0.0.1"
            port = int(flag(argv, "--port"))
            assert info.base_url == f"http://127.0.0.1:{port}"
            assert await runtime.health() is True
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_readiness_waits_for_the_model_to_load(tmp_path: Path, run_dir: Path) -> None:
    async def scenario() -> None:
        weights = weights_with(tmp_path, loading_health_responses=5)
        runtime = process(run_dir, Sleeps([]))
        try:
            await runtime.ensure(EG2, EG2.space(), weights)
            assert await runtime.health() is True
            assert len(launches(weights)) == 1
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_failed_starts_back_off_then_succeed(tmp_path: Path, run_dir: Path) -> None:
    async def scenario() -> None:
        weights = weights_with(tmp_path, fail_launches=2)
        sleeps = Sleeps([])
        runtime = process(run_dir, sleeps)
        try:
            await runtime.ensure(EG2, EG2.space(), weights)
            assert sleeps.delays == [1.0, 3.0]
            assert len(launches(weights)) == 3
            assert runtime.failures == 2
        finally:
            await runtime.stop()
        assert runtime.failures == 0

    asyncio.run(scenario())


def test_gives_up_after_five_restarts(tmp_path: Path, run_dir: Path) -> None:
    async def scenario() -> None:
        weights = weights_with(tmp_path, fail_launches=100)
        sleeps = Sleeps([])
        runtime = process(run_dir, sleeps)

        with pytest.raises(LlamaServerStartError):
            await runtime.ensure(EG2, EG2.space(), weights)

        assert sleeps.delays == list(BACKOFF_SECONDS) == [1.0, 3.0, 8.0, 22.0, 60.0]
        assert len(launches(weights)) == 6
        assert list(run_dir.glob("embedder-*")) == []  # no key files or sockets left behind
        await runtime.stop()

    asyncio.run(scenario())


def test_crash_is_detected_and_restarted_with_backoff(tmp_path: Path, run_dir: Path) -> None:
    async def scenario() -> None:
        weights = weights_with(tmp_path, crash_after_seconds=0.5)
        sleeps = Sleeps([])
        runtime = process(run_dir, sleeps)
        try:
            first = await runtime.ensure(EG2, EG2.space(), weights)
            for _ in range(200):  # until health() sees the exit (a dying server may refuse first)
                await runtime.health()
                if runtime.endpoint() is None:
                    break
                await asyncio.sleep(0.05)
            assert runtime.failures == 1
            assert runtime.endpoint() is None

            second = await runtime.ensure(EG2, EG2.space(), weights)

            assert sleeps.delays == [1.0]
            assert second.pid != first.pid and second.api_key_file != first.api_key_file
            assert len(launches(weights)) == 2
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_same_model_other_dims_reuses_the_server(tmp_path: Path, run_dir: Path) -> None:
    async def scenario() -> None:
        weights = weights_with(tmp_path)
        runtime = process(run_dir, Sleeps([]))
        try:
            first = await runtime.ensure(EG2, EG2.space(512), weights)
            second = await runtime.ensure(EG2, EG2.space(768), weights)
            assert second.pid == first.pid and second.space_id == EG2.space(768).id
            assert len(launches(weights)) == 1
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_missing_binary_or_weights_is_not_retried(tmp_path: Path, run_dir: Path) -> None:
    async def scenario() -> None:
        sleeps = Sleeps([])
        with pytest.raises(LlamaServerUnavailableError):
            await process(run_dir, sleeps, binary=None).ensure(EG2, EG2.space(), weights_with(tmp_path))
        with pytest.raises(LlamaServerUnavailableError):
            await process(run_dir, sleeps).ensure(EG2, EG2.space(), tmp_path / "missing.gguf")
        assert sleeps.delays == []

    asyncio.run(scenario())


def test_supervisor_stops_the_server_when_smart_search_is_turned_off(tmp_path: Path, run_dir: Path) -> None:
    async def scenario() -> None:
        weights = weights_with(tmp_path)
        runtime = process(run_dir, Sleeps([]))

        class Targets:
            current: RuntimeTarget | None = RuntimeTarget(spec=EG2, space=EG2.space(), weights=weights)

            async def target(self) -> RuntimeTarget | None:
                return self.current

        targets = Targets()
        service = SmartSearchRuntimeService(
            runtime=runtime, targets=targets, endpoint_file=endpoint_file_path(tmp_path / "data")
        )
        await service.tick()
        pid = runtime.pid
        assert pid is not None and service.endpoint_file.exists()

        targets.current = None
        await service.tick()

        assert runtime.pid is None and runtime.endpoint() is None
        assert not service.endpoint_file.exists()
        assert list(run_dir.glob("embedder-*")) == []

    asyncio.run(scenario())


@pytest.mark.skipif(not POSIX, reason="the executable bit is POSIX-only")
def test_binary_resolution_order(tmp_path: Path) -> None:
    def executable(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    packaged = executable(tmp_path / "packaged" / "llama-server")
    configured = executable(tmp_path / "configured" / "llama-server")
    on_path = executable(tmp_path / "bin" / "llama-server")
    not_executable = tmp_path / "plain" / "llama-server"
    not_executable.parent.mkdir()
    not_executable.write_text("", encoding="utf-8")
    env = {PACKAGED_BINARY_ENV: str(packaged), "PATH": str(on_path.parent)}

    assert resolve_llama_server_binary(str(configured), environ=env) == packaged
    assert resolve_llama_server_binary(str(configured), environ={"PATH": str(on_path.parent)}) == configured
    assert resolve_llama_server_binary(None, environ={"PATH": str(on_path.parent)}) == on_path
    assert resolve_llama_server_binary("relative/llama-server", environ={"PATH": str(on_path.parent)}) == on_path
    assert resolve_llama_server_binary(str(not_executable), environ={"PATH": ""}) is None


def test_normalize_server_url() -> None:
    assert normalize_server_url("") is None
    assert normalize_server_url("http://127.0.0.1:8080/v1/embeddings") == "http://127.0.0.1:8080"
    assert normalize_server_url("http://127.0.0.1:8080/v1/") == "http://127.0.0.1:8080"
    assert normalize_server_url("http://llama:8080/proxy") == "http://llama:8080/proxy"


def test_external_server_is_used_without_spawning(tmp_path: Path) -> None:
    async def scenario() -> None:
        with FakeLlamaServer(dims=768) as fake:
            runtime = ExternalEmbeddingServer(fake.base_url)
            info = await runtime.ensure(EG2, EG2.space(), tmp_path / "unused.gguf")
            assert info.base_url == fake.base_url and info.pid is None and str(info.api_key_file) in {"", "."}
            assert await runtime.health() is True

            provider = LlamaCppEmbeddingProvider(spec=EG2, space=EG2.space(), endpoint=runtime.endpoint)
            await provider.embed_query("hola")
            assert fake.state.embedding_requests()[0]["authorization"] is None
            dead_url = fake.base_url

        with pytest.raises(LlamaServerStartError):
            await ExternalEmbeddingServer(dead_url, timeout_seconds=1.0).ensure(EG2, EG2.space(), tmp_path / "x")

    asyncio.run(scenario())
