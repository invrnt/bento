from __future__ import annotations

import asyncio
import json
import stat
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from bento.application.smart_search.runtime import (
    CUSTOM_MODEL_ID,
    SmartSearchRuntimeHooks,
    StatusRuntimeTargets,
    EmbeddingRuntimeFailedError,
    EmbeddingRuntimeUnavailableError,
    EndpointFileReader,
    EndpointFileRuntime,
    RuntimeTarget,
    SmartSearchRuntimeService,
    custom_model_spec,
    endpoint_file_path,
    read_endpoint_file,
    write_endpoint_file,
)
from bento.domain.smart_search import (
    EmbeddingSpace,
    ModelFile,
    ModelSpec,
    Pooling,
    SmartSearchErrorCode,
    SmartSearchState,
    SmartSearchStatus,
    parse_manifest,
)
from bento.ports.models import EndpointInfo

MANIFEST = json.loads((Path(__file__).parents[1] / "smart_search" / "manifest_v1.json").read_text(encoding="utf-8"))
SPECS, _ = parse_manifest(MANIFEST)
EG2, QWEN = SPECS


@dataclass
class FakeRuntime:
    healthy: bool = True
    fail: bool = False
    ensure_calls: list[str] = field(default_factory=list)
    stops: int = 0
    launches: int = 0

    async def ensure(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> EndpointInfo:
        del spec
        self.ensure_calls.append(space.id)
        if self.fail:
            raise RuntimeError("no start")
        self.launches += 1
        return EndpointInfo(
            space_id=space.id,
            base_url=f"http+unix:///run/embedder-{self.launches}.sock",
            api_key_file=weights.parent / f"embedder-{self.launches}.key",
            pid=1000 + self.launches,
            started_at="2026-11-26T00:00:00+00:00",
        )

    async def stop(self) -> None:
        self.stops += 1

    async def health(self) -> bool:
        return self.healthy

    def endpoint(self) -> EndpointInfo | None:
        return None


@dataclass
class FakeTargets:
    current: RuntimeTarget | None

    async def target(self) -> RuntimeTarget | None:
        return self.current


@dataclass
class FakeStatus:
    events: list[tuple[str, str]] = field(default_factory=list)

    async def runtime_ready(self, space_id: str) -> None:
        self.events.append(("ready", space_id))

    async def runtime_failed(self, space_id: str) -> None:
        self.events.append(("failed", space_id))


def target_for(tmp_path: Path, spec: ModelSpec = EG2) -> RuntimeTarget:
    return RuntimeTarget(spec=spec, space=spec.space(), weights=tmp_path / spec.weights.name)


def service_for(
    tmp_path: Path, runtime: FakeRuntime, targets: FakeTargets, status: FakeStatus | None = None
) -> SmartSearchRuntimeService:
    return SmartSearchRuntimeService(
        runtime=runtime, targets=targets, endpoint_file=endpoint_file_path(tmp_path / "data"), status=status
    )


def test_tick_starts_the_server_and_publishes_embedder_json(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime, status = FakeRuntime(), FakeStatus()
        service = service_for(tmp_path, runtime, FakeTargets(target_for(tmp_path)), status)

        await service.tick()

        path = tmp_path / "data" / "run" / "embedder.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload == {
            "space_id": EG2.space().id,
            "base_url": "http+unix:///run/embedder-1.sock",
            "api_key_file": str(tmp_path / "embedder-1.key"),
            "pid": 1001,
            "started_at": "2026-11-26T00:00:00+00:00",
        }
        if sys.platform != "win32":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert status.events == [("ready", EG2.space().id)]
        assert service.current_endpoint() == read_endpoint_file(path)

    asyncio.run(scenario())


def test_healthy_server_is_left_alone(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = FakeRuntime()
        service = service_for(tmp_path, runtime, FakeTargets(target_for(tmp_path)))

        await service.tick()
        await service.tick()

        assert runtime.ensure_calls == [EG2.space().id]

    asyncio.run(scenario())


def test_unhealthy_server_is_restarted_and_the_file_rewritten(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime, status = FakeRuntime(), FakeStatus()
        service = service_for(tmp_path, runtime, FakeTargets(target_for(tmp_path)), status)
        await service.tick()

        runtime.healthy = False
        await service.tick()

        assert runtime.ensure_calls == [EG2.space().id, EG2.space().id]
        info = read_endpoint_file(service.endpoint_file)
        assert info is not None and info.pid == 1002
        assert status.events == [("ready", EG2.space().id), ("ready", EG2.space().id)]

    asyncio.run(scenario())


def test_server_stops_when_smart_search_is_off_or_the_model_is_removed(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = FakeRuntime()
        targets = FakeTargets(target_for(tmp_path))
        service = service_for(tmp_path, runtime, targets)
        await service.tick()
        assert service.endpoint_file.exists()

        targets.current = None
        await service.tick()

        assert runtime.stops == 1
        assert not service.endpoint_file.exists()
        assert service.current_endpoint() is None

    asyncio.run(scenario())


def test_space_change_starts_the_new_space(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = FakeRuntime()
        targets = FakeTargets(target_for(tmp_path))
        service = service_for(tmp_path, runtime, targets)
        await service.tick()

        targets.current = target_for(tmp_path, QWEN)
        await service.tick()

        assert runtime.ensure_calls == [EG2.space().id, QWEN.space().id]
        info = read_endpoint_file(service.endpoint_file)
        assert info is not None and info.space_id == QWEN.space().id

    asyncio.run(scenario())


def test_start_failure_is_error_runtime_until_retry(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime, status = FakeRuntime(fail=True), FakeStatus()
        service = service_for(tmp_path, runtime, FakeTargets(target_for(tmp_path)), status)

        await service.tick()
        await service.tick()  # gave up: no new attempt

        assert runtime.ensure_calls == [EG2.space().id]
        assert service.failed_space == EG2.space().id
        assert status.events == [("failed", EG2.space().id)]
        assert not service.endpoint_file.exists()
        assert await service.available() is False
        with pytest.raises(EmbeddingRuntimeFailedError):
            await service.ensure_running()

        runtime.fail = False
        await service.retry()
        await service.tick()

        assert runtime.ensure_calls == [EG2.space().id, EG2.space().id]
        assert service.failed_space is None
        assert service.endpoint_file.exists()

    asyncio.run(scenario())


def test_ensure_running_needs_a_target_and_reuses_a_healthy_server(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = FakeRuntime()
        targets = FakeTargets(None)
        service = service_for(tmp_path, runtime, targets)
        with pytest.raises(EmbeddingRuntimeUnavailableError):
            await service.ensure_running()

        targets.current = target_for(tmp_path)
        first = await service.ensure_running()
        second = await service.ensure_running()

        assert first == second
        assert runtime.ensure_calls == [EG2.space().id]

    asyncio.run(scenario())


def test_run_stops_the_server_on_shutdown(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = FakeRuntime()
        service = SmartSearchRuntimeService(
            runtime=runtime,
            targets=FakeTargets(target_for(tmp_path)),
            endpoint_file=endpoint_file_path(tmp_path / "data"),
            interval_seconds=0.01,
        )
        stop = asyncio.Event()
        task = asyncio.create_task(service.run(stop))
        for _ in range(200):
            if service.current_endpoint() is not None:
                break
            await asyncio.sleep(0.01)
        stop.set()
        await task

        assert runtime.ensure_calls == [EG2.space().id]
        assert runtime.stops == 1
        assert not service.endpoint_file.exists()

    asyncio.run(scenario())


def test_leftover_endpoint_file_is_cleaned_up_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = endpoint_file_path(tmp_path / "data")
        stale = EndpointInfo(
            space_id=EG2.space().id,
            base_url="http+unix:///old.sock",
            api_key_file=tmp_path / "old.key",
            pid=4242,
            started_at="2026-11-25T00:00:00+00:00",
        )
        write_endpoint_file(path, stale)
        seen: list[EndpointInfo] = []
        service = SmartSearchRuntimeService(
            runtime=FakeRuntime(),
            targets=FakeTargets(None),
            endpoint_file=path,
            stale_cleanup=seen.append,
        )

        await service.tick()
        await service.tick()

        assert seen == [stale]
        assert not path.exists()

    asyncio.run(scenario())


def test_endpoint_file_round_trip_and_validation(tmp_path: Path) -> None:
    path = tmp_path / "run" / "embedder.json"
    info = EndpointInfo(
        space_id=EG2.space().id,
        base_url="http://127.0.0.1:50123",
        api_key_file=tmp_path / "k.key",
        pid=77,
        started_at="2026-11-26T10:00:00+00:00",
    )
    write_endpoint_file(path, info)
    assert read_endpoint_file(path) == info

    external = EndpointInfo(
        space_id=EG2.space().id, base_url="http://llama:8080", api_key_file=Path(""), pid=None, started_at="t"
    )
    write_endpoint_file(path, external)
    assert json.loads(path.read_text(encoding="utf-8"))["api_key_file"] == ""
    assert read_endpoint_file(path) == external

    for bad in ("{", "[]", '{"space_id": "", "base_url": "http://x"}', '{"space_id": "s", "base_url": "ftp://x"}'):
        path.write_text(bad, encoding="utf-8")
        assert read_endpoint_file(path) is None
    path.write_text('{"space_id": "s", "base_url": "http://x", "pid": true}', encoding="utf-8")
    assert read_endpoint_file(path) is None
    assert read_endpoint_file(tmp_path / "missing.json") is None


def test_endpoint_file_reader_follows_changes(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = endpoint_file_path(tmp_path)
        reader = EndpointFileReader(path)
        runtime_view = EndpointFileRuntime(path)
        assert reader() is None
        assert await runtime_view.health() is False
        with pytest.raises(EmbeddingRuntimeUnavailableError):
            await runtime_view.ensure(EG2, EG2.space(), tmp_path / "w.gguf")

        first = EndpointInfo(EG2.space().id, "http://127.0.0.1:1", tmp_path / "a.key", 1, "t1")
        write_endpoint_file(path, first)
        assert reader() == first
        second = EndpointInfo(EG2.space().id, "http://127.0.0.1:22", tmp_path / "bb.key", 22, "t22")
        write_endpoint_file(path, second)
        assert reader() == second
        assert runtime_view.endpoint() == second
        path.unlink()
        assert reader() is None

    asyncio.run(scenario())


def test_custom_model_spec_prefixes_pooling_and_revision() -> None:
    spec = custom_model_spec(
        file_name="mi-modelo.gguf",
        identity="/models/mi-modelo.gguf",
        size_bytes=1234,
        mtime_ns=1,
        dims=384,
        pooling="CLS",
        query_prefix="query: ",
        document_prefix="passage: ",
    )
    assert spec.model_id == CUSTOM_MODEL_ID
    assert spec.pooling is Pooling.CLS
    assert spec.format_query(" playa ") == "query: playa"
    assert spec.format_document("arena", "x.txt") == "passage: arena"
    assert spec.space().id == f"custom@{spec.revision}/384"

    templated = custom_model_spec(
        file_name="m.gguf",
        identity="/m.gguf",
        size_bytes=1,
        mtime_ns=1,
        dims=8,
        pooling="rank",
        query_prefix="Q[{q}]",
        document_prefix="{title}: {text}",
    )
    assert templated.pooling is Pooling.MEAN
    assert templated.format_query("a") == "Q[a]"
    assert templated.format_document("b", None) == "none: b"

    plain = custom_model_spec(file_name=".hidden", identity="/h", size_bytes=0, mtime_ns=0, dims=8)
    assert plain.weights.name == "model.gguf"
    assert plain.format_query("a") == "a" and plain.format_document("b") == "b"

    changed = custom_model_spec(file_name="m.gguf", identity="/m.gguf", size_bytes=1, mtime_ns=2, dims=8)
    same = custom_model_spec(file_name="m.gguf", identity="/m.gguf", size_bytes=1, mtime_ns=1, dims=8)
    assert changed.revision != same.revision


# Status-driven targets (managed mode in the worker) ---------------------------------------

SMALL_EG2 = replace(EG2, files=(replace(EG2.weights, size_bytes=4),))


class OneModelCatalog:
    def default(self) -> ModelSpec:
        return SMALL_EG2

    def get(self, model_id: str, revision: str | None = None) -> ModelSpec | None:
        if model_id == SMALL_EG2.model_id and revision in {None, SMALL_EG2.revision}:
            return SMALL_EG2
        return None

    def all(self) -> tuple[ModelSpec, ...]:
        return (SMALL_EG2,)


@dataclass
class LayoutStore:
    root: Path

    def installed(self) -> tuple[object, ...]:
        return ()

    def path_for(self, spec: ModelSpec, file: ModelFile) -> Path:
        return self.root / spec.model_id / spec.revision / file.name

    def part_path_for(self, spec: ModelSpec, file: ModelFile) -> Path:
        return self.path_for(spec, file).with_suffix(".part")

    def free_bytes(self) -> int:
        return 0

    def remove(self, spec: ModelSpec) -> int:
        del spec
        return 0

    def verify(self, spec: ModelSpec) -> bool:
        del spec
        return True


def status_targets(tmp_path: Path, status: SmartSearchStatus) -> tuple[StatusRuntimeTargets, LayoutStore]:
    store = LayoutStore(tmp_path / "models")

    async def load() -> SmartSearchStatus:
        return status

    return StatusRuntimeTargets(catalog=OneModelCatalog(), store=store, load_status=load), store  # type: ignore[arg-type]


def test_status_names_the_space_once_the_weights_are_installed(tmp_path: Path) -> None:
    async def scenario() -> None:
        space_id = SMALL_EG2.space(256).id
        targets, store = status_targets(tmp_path, SmartSearchStatus(state=SmartSearchState.STARTING, space_id=space_id))
        assert await targets.target() is None

        weights = store.path_for(SMALL_EG2, SMALL_EG2.weights)
        weights.parent.mkdir(parents=True)
        weights.write_bytes(b"gguf")
        target = await targets.target()

        assert target is not None
        assert target.space.id == space_id and target.space.dims == 256 and target.weights == weights

    asyncio.run(scenario())


def test_only_serving_states_have_a_target(tmp_path: Path) -> None:
    async def scenario() -> None:
        space_id = SMALL_EG2.space().id
        for state in (SmartSearchState.STARTING, SmartSearchState.INDEXING, SmartSearchState.READY):
            targets, store = status_targets(tmp_path, SmartSearchStatus(state=state, space_id=space_id))
            weights = store.path_for(SMALL_EG2, SMALL_EG2.weights)
            weights.parent.mkdir(parents=True, exist_ok=True)
            weights.write_bytes(b"gguf")
            assert await targets.target() is not None, state
        others = [
            SmartSearchStatus(),
            SmartSearchStatus(state=SmartSearchState.DOWNLOADING, space_id=space_id),
            SmartSearchStatus(state=SmartSearchState.VERIFYING, space_id=space_id),
            SmartSearchStatus(
                state=SmartSearchState.ERROR,
                space_id=space_id,
                error_code=SmartSearchErrorCode.RUNTIME,
                failed_step=SmartSearchState.STARTING,
            ),
            SmartSearchStatus(state=SmartSearchState.READY, space_id="legacy:jina/768"),
            SmartSearchStatus(state=SmartSearchState.READY, space_id=QWEN.space().id),  # not in this catalog
        ]
        for status in others:
            targets, _ = status_targets(tmp_path, status)
            assert await targets.target() is None, status

    asyncio.run(scenario())


def test_hooks_start_on_starting_and_stop_on_removal(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime, status = FakeRuntime(), FakeStatus()
        service = service_for(tmp_path, runtime, FakeTargets(None))
        service.attach_status(status)
        hooks = SmartSearchRuntimeHooks(service)

        await hooks.starting(EG2, EG2.space(256), tmp_path / "w.gguf")

        assert runtime.ensure_calls == [EG2.space(256).id]
        assert status.events == [("ready", EG2.space(256).id)]
        assert service.current_model() == (EG2, EG2.space(256))
        assert service.endpoint_file.exists()

        await hooks.update_ready(QWEN, QWEN.space(), tmp_path / "q.gguf")
        assert runtime.ensure_calls == [EG2.space(256).id]

        await hooks.stopped(EG2.space(256).id)
        assert runtime.stops == 1 and service.current_model() is None
        assert not service.endpoint_file.exists()

    asyncio.run(scenario())


def test_starting_hook_clears_a_previous_give_up(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = FakeRuntime(fail=True)
        target = target_for(tmp_path)
        service = service_for(tmp_path, runtime, FakeTargets(target))
        await service.tick()
        assert service.failed_space == target.space.id

        runtime.fail = False
        await SmartSearchRuntimeHooks(service).starting(target.spec, target.space, target.weights)

        assert service.failed_space is None and service.current_endpoint() is not None

    asyncio.run(scenario())
