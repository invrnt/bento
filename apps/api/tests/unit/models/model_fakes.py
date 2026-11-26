"""Shared fakes for the smart search model-download tests (unit and API)."""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bento.adapters.models.filesystem_store import FilesystemModelStore
from bento.adapters.models.http_downloader import HttpModelDownloader
from bento.adapters.models.manifest_catalog import ManifestModelCatalog
from bento.application.smart_search.activation import ModelInstallRecord, SmartSearchActivationService
from bento.domain.jobs import Job, JobStatus, JobType
from bento.domain.smart_search import (
    EmbeddingSpace,
    ModelFile,
    ModelFileRole,
    ModelSpec,
    SmartSearchState,
    SmartSearchStatus,
    parse_manifest,
)
from tests.fakes.model_host import MIRROR_URL, PRIMARY_URL, FakeModelHost, sha256_hex

CANONICAL_MANIFEST = Path(__file__).parents[1] / "smart_search" / "manifest_v1.json"
DEFAULT_MODEL_ID = "embeddinggemma-2-q8_0"
TEST_BLOCK_BYTES = 256 * 1024
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


def canonical_manifest() -> dict[str, Any]:
    return json.loads(CANONICAL_MANIFEST.read_text(encoding="utf-8"))


def tiny_spec(blob: bytes, *, revision: str | None = None, urls: tuple[str, ...] = (PRIMARY_URL, MIRROR_URL)) -> ModelSpec:
    """The default model (EmbeddingGemma 2 settings) with its weights swapped for the fake host's blob."""
    specs, _ = parse_manifest(canonical_manifest())
    base = next(spec for spec in specs if spec.model_id == DEFAULT_MODEL_ID)
    weights = ModelFile(
        name="tiny-model.gguf",
        role=ModelFileRole.WEIGHTS,
        urls=urls,
        size_bytes=len(blob),
        sha256=sha256_hex(blob),
    )
    return replace(base, files=(weights,), revision=revision or base.revision)


def tiny_catalog(blob: bytes, *, revision: str | None = None) -> ManifestModelCatalog:
    specs, default_id = parse_manifest(canonical_manifest())
    others = tuple(spec for spec in specs if spec.model_id != DEFAULT_MODEL_ID)
    return ManifestModelCatalog((tiny_spec(blob, revision=revision), *others), default_id)


class MemoryStatusRepository:
    """Thread-safe in-memory `SmartSearchStatusRepositoryPort` with the same compare-and-set rule as SQLite."""

    def __init__(self, status: SmartSearchStatus | None = None) -> None:
        self.status = status or SmartSearchStatus()
        self.records: dict[tuple[str, str, str], ModelInstallRecord] = {}
        self._lock = threading.Lock()

    async def load(self) -> SmartSearchStatus:
        with self._lock:
            return self.status

    async def replace(self, expected: SmartSearchStatus, new: SmartSearchStatus) -> bool:
        with self._lock:
            current = self.status
            if (current.state, current.space_id, current.error_code, current.waiting_network) != (
                expected.state,
                expected.space_id,
                expected.error_code,
                expected.waiting_network,
            ):
                return False
            self.status = new
            return True

    async def set_download_progress(self, space_id: str, bytes_done: int) -> bool:
        with self._lock:
            current = self.status
            if current.space_id != space_id or current.state not in {
                SmartSearchState.DOWNLOADING,
                SmartSearchState.PAUSED,
            }:
                return False
            self.status = replace(current, bytes_done=max(0, bytes_done))
            return True

    async def set_index_progress(self, space_id: str, done: int, total: int) -> bool:
        with self._lock:
            current = self.status
            if current.space_id != space_id or current.state is not SmartSearchState.INDEXING:
                return False
            total = max(0, total)
            self.status = replace(current, indexed_done=max(0, min(done, total)), indexed_total=total)
            return True

    async def save_install(self, record: ModelInstallRecord) -> None:
        with self._lock:
            self.records[(record.model_id, record.revision, record.file)] = record

    async def installs(self) -> tuple[ModelInstallRecord, ...]:
        with self._lock:
            return tuple(self.records[key] for key in sorted(self.records))

    async def delete_installs(self, model_id: str, revision: str | None = None) -> None:
        with self._lock:
            for key in [k for k in self.records if k[0] == model_id and (revision is None or k[1] == revision)]:
                del self.records[key]


class RecordingJobQueue:
    def __init__(self) -> None:
        self.jobs: list[Job] = []

    async def enqueue(
        self,
        *,
        type: JobType,  # noqa: A002 - port signature
        priority: int,
        payload: dict[str, object],
        asset_id: str | None = None,
        max_attempts: int = 3,
    ) -> Job:
        job = Job(
            id=f"job_{len(self.jobs) + 1}",
            type=type,
            status=JobStatus.QUEUED,
            priority=priority,
            payload=dict(payload),
            attempts=0,
            max_attempts=max_attempts,
            created_at=NOW,
            updated_at=NOW,
            asset_id=asset_id,
        )
        self.jobs.append(job)
        return job

    def last_payload(self) -> dict[str, object]:
        assert self.jobs, "no job was enqueued"
        return self.jobs[-1].payload


@dataclass
class FakeProviderSwitch:
    is_locked: bool = False
    value: str = "disabled"
    changes: list[str] = field(default_factory=list)

    async def locked(self) -> bool:
        return self.is_locked

    async def enable(self) -> None:
        self.value = "managed"
        self.changes.append("managed")

    async def disable(self) -> None:
        if self.value == "managed":
            self.value = "disabled"
            self.changes.append("disabled")


@dataclass
class RecordingHooks:
    started: list[tuple[str, Path]] = field(default_factory=list)
    updates: list[str] = field(default_factory=list)
    stopped_spaces: list[str | None] = field(default_factory=list)

    async def starting(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> None:
        self.started.append((space.id, weights))

    async def update_ready(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> None:
        self.updates.append(space.id)

    async def stopped(self, space_id: str | None) -> None:
        self.stopped_spaces.append(space_id)


class LimitedSpaceStore(FilesystemModelStore):
    def __init__(self, root: Path, free: int) -> None:
        super().__init__(root)
        self.free = free

    def free_bytes(self) -> int:
        return self.free


async def no_sleep(seconds: float) -> None:
    await asyncio.sleep(0)


def fake_host_downloader(host: FakeModelHost, **overrides: Any) -> HttpModelDownloader:
    options: dict[str, Any] = {
        "user_agent": "Bento/0.0.0-test",
        "timeout_seconds": 5.0,
        "block_bytes": TEST_BLOCK_BYTES,
        "progress_interval_seconds": 0.0,
        "rewrite_url": host.rewrite,
        "allow_http_loopback": True,
    }
    options.update(overrides)
    return HttpModelDownloader(**options)


@dataclass
class ServiceKit:
    service: SmartSearchActivationService
    repository: MemoryStatusRepository
    jobs: RecordingJobQueue
    switch: FakeProviderSwitch
    hooks: RecordingHooks
    store: FilesystemModelStore
    spec: ModelSpec

    async def run_last_job(self, *, final_attempt: bool = False) -> Any:
        return await self.service.run_download_job(self.jobs.last_payload(), final_attempt=final_attempt)


def make_kit(
    tmp_path: Path,
    host: FakeModelHost,
    *,
    free_bytes: int | None = None,
    catalog: ManifestModelCatalog | None = None,
    retry_delays: tuple[float, ...] = (0.0,),
    **downloader_overrides: Any,
) -> ServiceKit:
    root = tmp_path / "data" / "models"
    store: FilesystemModelStore = (
        FilesystemModelStore(root) if free_bytes is None else LimitedSpaceStore(root, free_bytes)
    )
    resolved_catalog = catalog or tiny_catalog(host.blob)
    repository = MemoryStatusRepository()
    jobs = RecordingJobQueue()
    switch = FakeProviderSwitch()
    hooks = RecordingHooks()
    service = SmartSearchActivationService(
        catalog=resolved_catalog,
        store=store,
        repository=repository,
        jobs=jobs,
        provider_switch=switch,
        hooks=hooks,
        downloader=fake_host_downloader(host, **downloader_overrides),
        write_license=lambda spec: store.write_license(spec, "Apache License\nVersion 2.0\n"),
        sleep=no_sleep,
        poll_interval_seconds=0.005,
        network_retry_delays=retry_delays,
    )
    return ServiceKit(service, repository, jobs, switch, hooks, store, resolved_catalog.default())


def files_under(path: Path) -> list[Path]:
    return sorted(item for item in path.rglob("*") if item.is_file()) if path.exists() else []
