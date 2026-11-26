"""Ports for managed smart-search models: catalog, download, storage and runtime.

Contract: `orchestration/api/smart-search-contract.md`. Implemented in Stage 24
(`adapters/models/**`, `adapters/runtime/**`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from bento.domain.smart_search import EmbeddingSpace, ModelFile, ModelSpec

ProgressCallback = Callable[[int, int], None]
"""`(bytes_done, bytes_total)`; the downloader rate-limits calls (≤ 4 per second)."""

StopCheck = Callable[[], bool]
"""Polled between 4 MiB blocks; `True` stops the download, keeping the `.part` file."""


class DownloadResult(StrEnum):
    COMPLETED = "completed"  # whole file on disk as `.part`, sha256 matched, renamed
    STOPPED = "stopped"  # `should_stop()` returned True (pause/cancel/shutdown)
    NETWORK = "network"  # connection lost; resumable from `bytes_done`
    FAILED = "failed"  # every URL failed with a non-retryable HTTP status
    CHECKSUM = "checksum"  # complete but the hash did not match; `.part` deleted
    NO_SPACE = "no_space"  # the disk filled up; `.part` kept


@dataclass(frozen=True, slots=True)
class DownloadOutcome:
    result: DownloadResult
    bytes_done: int
    url_used: str | None = None


@dataclass(frozen=True, slots=True)
class InstalledModel:
    model_id: str
    revision: str
    path: Path
    size_bytes: int


@dataclass(frozen=True, slots=True)
class EndpointInfo:
    """How to reach the running embedding server (`<data_dir>/run/embedder.json`)."""

    space_id: str
    base_url: str  # `http://127.0.0.1:<port>` or `http+unix://<socket>`
    api_key_file: Path
    pid: int | None
    started_at: str


class ModelCatalogPort(Protocol):
    def default(self) -> ModelSpec: ...

    def get(self, model_id: str, revision: str | None = None) -> ModelSpec | None: ...

    def all(self) -> tuple[ModelSpec, ...]: ...


class ModelDownloaderPort(Protocol):
    async def download(
        self,
        file: ModelFile,
        dest_part: Path,
        on_progress: ProgressCallback,
        should_stop: StopCheck,
    ) -> DownloadOutcome:
        """Resume from `dest_part.stat().st_size` with `Range`; require `206` + `Content-Range`;
        restart from zero on `200` or an ETag change. Try `file.urls` in order. Hash while
        streaming; fsync and rename to the final name only when the sha256 matches."""
        ...


class ModelStorePort(Protocol):
    def installed(self) -> tuple[InstalledModel, ...]: ...

    def path_for(self, spec: ModelSpec, file: ModelFile) -> Path: ...

    def part_path_for(self, spec: ModelSpec, file: ModelFile) -> Path: ...

    def free_bytes(self) -> int: ...

    def remove(self, spec: ModelSpec) -> int:
        """Delete the model's files (final and partial); return the bytes freed."""
        ...

    def verify(self, spec: ModelSpec) -> bool:
        """Size + mtime marker check; full re-hash only when those changed."""
        ...


class EmbeddingRuntimePort(Protocol):
    async def ensure(self, spec: ModelSpec, space: EmbeddingSpace, weights: Path) -> EndpointInfo: ...

    async def stop(self) -> None: ...

    async def health(self) -> bool: ...

    def endpoint(self) -> EndpointInfo | None:
        """Read side for the API process: `None` means vector search is unavailable."""
        ...
