"""Automatic one-way folder backup: sources, incremental scans, debounced watcher events, and policy."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Protocol

from bento.application.drive import CreateFolderCommand
from bento.application.ingestion.assets import UploadedAssetFile
from bento.application.upload import UploadAssetResult
from bento.domain.assets import AssetMode
from bento.domain.backup import (
    BackupFile,
    BackupFileState,
    BackupPolicy,
    BackupSource,
    BackupSourceState,
    BackupSuggestion,
)
from bento.domain.drive import Folder
from bento.domain.errors import BackupSourceInvalidError, DomainError, ValidationFailedError
from bento.domain.jobs import JobStatus, JobType
from bento.ports.backup import BackupPolicyRepositoryPort, BackupSourceRepositoryPort, BackupSuggestionsPort
from bento.ports.jobs import JobQueuePort
from bento.ports.repositories import ClockPort

BACKUP_ROOT_FOLDER = "Respaldo"
BACKUP_SCAN_PRIORITY = 5
BACKUP_UPLOAD_PRIORITY = 6
BACKUP_UPLOAD_BATCH = 20
WATCH_DEBOUNCE_SECONDS = 2.0
WATCH_MAX_DELAY_SECONDS = 30.0
WATCH_MAX_PATHS = 200
MAX_BANDWIDTH_KBPS = 1_000_000
MAX_LABEL_LENGTH = 255
MAX_PATH_LENGTH = 4096
SETTLE_SECONDS = 3.0
"""Files modified more recently than this are still being written; they wait for the next batch."""


class BackupSourceNotFoundError(DomainError):
    def __init__(self, source_id: str) -> None:
        super().__init__("backup_source_not_found", "Backup folder not found", {"source_id": source_id})


@dataclass(frozen=True, slots=True)
class ScannedFile:
    relative_path: str
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class PathInfo:
    path: Path
    exists: bool
    is_dir: bool
    readable: bool
    is_root: bool


class FolderScannerPort(Protocol):
    def inspect(self, raw_path: str) -> PathInfo:
        """Resolve a user-supplied absolute path (symlinks resolved). Raises `ValueError` for malformed input."""
        ...

    def scan(self, root: Path, *, start: str | None = None, exclude: tuple[Path, ...] = ()) -> Iterator[ScannedFile]:
        """Regular files under `root` (or `root/start`), skipping hidden/system/temp files; symlinks are not followed."""
        ...

    def stat(self, root: Path, relative_path: str) -> ScannedFile | None:
        """A single eligible regular file, or None (missing, ignored, symlink, directory)."""
        ...

    def is_directory(self, root: Path, relative_path: str) -> bool: ...

    def relative(self, root: Path, absolute_path: str) -> str | None:
        """POSIX path relative to `root` when inside it and not ignored."""
        ...


class BackupFileStorePort(Protocol):
    async def pending(self, *, limit: int = 50) -> tuple[BackupFile, ...]:
        """Pending or interrupted (`uploading`) files of enabled sources."""
        ...

    async def counts(self, source_id: str) -> dict[str, int]: ...

    async def snapshot(self, source_id: str) -> dict[str, BackupFile]: ...

    async def save_many(self, files: tuple[BackupFile, ...]) -> None: ...

    async def delete_paths(self, source_id: str, relative_paths: tuple[str, ...], *, prefixes: tuple[str, ...] = ()) -> int: ...


class BackupJobsPort(Protocol):
    async def has_waiting(self, type: JobType, *, source_id: str | None = None) -> bool:
        """A queued or retrying (not running) job of this type, optionally for one source."""
        ...

    async def has_parked_retry(self, source_id: str) -> bool:
        """A retryable FAILED `backup_scan` job that re-queues this source's failed files."""
        ...

    async def scanning_source_ids(self) -> set[str]: ...


class BackupFolderLookupPort(Protocol):
    async def find_child(self, parent_id: str | None, name: str) -> str | None: ...


class FolderCreatorPort(Protocol):
    async def create_folder(self, command: CreateFolderCommand) -> Folder: ...


class BackupIngestionPort(Protocol):
    async def upload_file(self, file: UploadedAssetFile) -> UploadAssetResult: ...


@dataclass(frozen=True, slots=True)
class ScanSummary:
    queued: int = 0
    removed: int = 0
    skipped: bool = False


def validate_source_path(
    info: PathInfo,
    *,
    data_dir: Path,
    existing: tuple[BackupSource, ...],
    ignore_id: str | None = None,
) -> Path:
    if not info.exists:
        raise BackupSourceInvalidError("not_found")
    if not info.is_dir:
        raise BackupSourceInvalidError("not_directory")
    if info.is_root:
        raise BackupSourceInvalidError("filesystem_root")
    if not info.readable:
        raise BackupSourceInvalidError("not_readable")
    path = info.path
    resolved_data_dir = data_dir.resolve()
    if path == resolved_data_dir or path.is_relative_to(resolved_data_dir):
        raise BackupSourceInvalidError("inside_data_dir")
    for source in existing:
        if source.id == ignore_id:
            continue
        other = Path(source.path)
        if path == other:
            raise BackupSourceInvalidError("duplicate")
        if path.is_relative_to(other) or other.is_relative_to(path):
            raise BackupSourceInvalidError("overlap")
    return path


def default_label(path: Path) -> str:
    return (path.name or str(path)).strip()[:MAX_LABEL_LENGTH] or "Carpeta"


def needs_upload(existing: BackupFile | None, scanned: ScannedFile, *, retry_failed: bool) -> bool:
    if existing is None:
        return True
    if existing.size_bytes != scanned.size_bytes or existing.mtime_ns != scanned.mtime_ns:
        return True
    return retry_failed and existing.state == BackupFileState.FAILED


class ScanDebouncer:
    """Coalesces watcher events per source; a source is due `delay` seconds after its last event
    (or `max_delay` after its first one while events keep arriving). Thread-safe."""

    def __init__(
        self,
        *,
        delay: float = WATCH_DEBOUNCE_SECONDS,
        max_delay: float = WATCH_MAX_DELAY_SECONDS,
        max_paths: int = WATCH_MAX_PATHS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._delay = delay
        self._max_delay = max_delay
        self._max_paths = max_paths
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: dict[str, _PendingEvents] = {}

    def add(self, source_id: str, absolute_path: str) -> None:
        now = self._clock()
        with self._lock:
            pending = self._pending.get(source_id)
            if pending is None:
                pending = self._pending[source_id] = _PendingEvents(first_at=now, last_at=now)
            pending.last_at = now
            if pending.paths is not None:
                pending.paths.add(absolute_path)
                if len(pending.paths) > self._max_paths:
                    pending.paths = None

    def due(self) -> list[tuple[str, tuple[str, ...] | None]]:
        """Pop sources ready to scan: `(source_id, changed paths)`; None paths means a full scan."""
        now = self._clock()
        ready: list[tuple[str, tuple[str, ...] | None]] = []
        with self._lock:
            for source_id, pending in list(self._pending.items()):
                if now - pending.last_at >= self._delay or now - pending.first_at >= self._max_delay:
                    del self._pending[source_id]
                    ready.append((source_id, None if pending.paths is None else tuple(sorted(pending.paths))))
        return ready

    def discard(self, source_id: str) -> None:
        with self._lock:
            self._pending.pop(source_id, None)


@dataclass(slots=True)
class _PendingEvents:
    first_at: float
    last_at: float
    paths: set[str] | None = field(default_factory=set)


class BackupService:
    def __init__(
        self,
        *,
        sources: BackupSourceRepositoryPort,
        files: BackupFileStorePort,
        policy: BackupPolicyRepositoryPort,
        suggestions: BackupSuggestionsPort,
        scanner: FolderScannerPort,
        jobs: JobQueuePort,
        job_state: BackupJobsPort,
        clock: ClockPort,
        data_dir: Path,
        new_id: Callable[[], str],
        ingestion: BackupIngestionPort | None = None,
        folders: BackupFolderLookupPort | None = None,
        folder_creator: FolderCreatorPort | None = None,
        settle_seconds: float = SETTLE_SECONDS,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._settle_seconds = settle_seconds
        self._wall_clock = wall_clock
        self._sources = sources
        self._files = files
        self._policy = policy
        self._suggestions = suggestions
        self._scanner = scanner
        self._jobs = jobs
        self._job_state = job_state
        self._clock = clock
        self._data_dir = data_dir
        self._new_id = new_id
        self._ingestion = ingestion
        self._folders = folders
        self._folder_creator = folder_creator

    # Sources -----------------------------------------------------------------------------------------

    async def list_sources(self) -> tuple[BackupSource, ...]:
        sources = await self._sources.list()
        policy = await self._policy.get()
        scanning = await self._job_state.scanning_source_ids()
        return tuple([await self._with_progress(source, policy, scanning) for source in sources])

    async def get_source(self, source_id: str) -> BackupSource:
        source = await self._require(source_id)
        return await self._with_progress(source, await self._policy.get(), await self._job_state.scanning_source_ids())

    async def add_source(self, raw_path: str, label: str | None = None) -> BackupSource:
        if not raw_path or "\x00" in raw_path or len(raw_path) > MAX_PATH_LENGTH:
            raise BackupSourceInvalidError("invalid_path")
        try:
            info = self._scanner.inspect(raw_path)
        except ValueError as exc:
            raise BackupSourceInvalidError("not_absolute" if "absolute" in str(exc) else "invalid_path") from exc
        path = validate_source_path(info, data_dir=self._data_dir, existing=await self._sources.list())
        now = self._clock.now()
        source = BackupSource(
            id=self._new_id(),
            path=str(path),
            label=_clean_label(label) or default_label(path),
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        await self._sources.save(source)
        await self.enqueue_scan(source.id)
        return await self.get_source(source.id)

    async def update_source(self, source_id: str, *, enabled: bool | None = None, label: str | None = None) -> BackupSource:
        source = await self._require(source_id)
        changes: dict[str, object] = {}
        if label is not None:
            cleaned = _clean_label(label)
            if not cleaned:
                raise ValidationFailedError("Backup folder label is required")
            changes["label"] = cleaned
        if enabled is not None:
            changes["enabled"] = enabled
        if changes:
            source = replace(source, updated_at=self._clock.now(), **changes)  # type: ignore[arg-type]
            await self._sources.save(source)
            if enabled:
                await self.enqueue_scan(source.id)
        return await self.get_source(source.id)

    async def remove_source(self, source_id: str) -> None:
        """Stops backing up the folder. Files already in Bento stay (one-way backup)."""
        await self._require(source_id)
        await self._sources.delete(source_id)

    async def request_scan(self, source_id: str) -> BackupSource:
        await self._require(source_id)
        await self.enqueue_scan(source_id, retry_failed=True)
        return await self.get_source(source_id)

    async def suggestions(self) -> tuple[BackupSuggestion, ...]:
        return await asyncio.to_thread(self._suggestions.suggestions)

    # Policy ------------------------------------------------------------------------------------------

    async def get_policy(self) -> BackupPolicy:
        return await self._policy.get()

    async def update_policy(
        self,
        *,
        paused: bool | None = None,
        pause_on_battery: bool | None = None,
        bandwidth_limit_kbps: int | None = None,
    ) -> BackupPolicy:
        current = await self._policy.get()
        if bandwidth_limit_kbps is not None and not 0 <= bandwidth_limit_kbps <= MAX_BANDWIDTH_KBPS:
            raise ValidationFailedError(
                "Bandwidth limit is out of range", {"minimum": 0, "maximum": MAX_BANDWIDTH_KBPS}
            )
        updated = replace(
            current,
            paused=current.paused if paused is None else paused,
            pause_on_battery=current.pause_on_battery if pause_on_battery is None else pause_on_battery,
            bandwidth_limit_kbps=current.bandwidth_limit_kbps if bandwidth_limit_kbps is None else bandwidth_limit_kbps,
        )
        await self._policy.save(updated)
        return await self._resume_if_unpaused(current, await self._policy.get())

    async def set_power(self, *, on_battery: bool) -> BackupPolicy:
        current = await self._policy.get()
        await self._policy.save(replace(current, on_battery=on_battery))
        return await self._resume_if_unpaused(current, await self._policy.get())

    async def _resume_if_unpaused(self, before: BackupPolicy, after: BackupPolicy) -> BackupPolicy:
        if before.effective_paused and not after.effective_paused:
            await self.enqueue_scans_for_all()
        return after

    # Jobs --------------------------------------------------------------------------------------------

    async def enqueue_scan(
        self, source_id: str, *, paths: tuple[str, ...] | None = None, retry_failed: bool = False
    ) -> bool:
        if paths is None and not retry_failed and await self._job_state.has_waiting(JobType.BACKUP_SCAN, source_id=source_id):
            return False
        payload: dict[str, object] = {"source_id": source_id, "retry_failed": retry_failed}
        if paths is not None:
            payload["paths"] = list(paths[:WATCH_MAX_PATHS])
        await self._jobs.enqueue(type=JobType.BACKUP_SCAN, priority=BACKUP_SCAN_PRIORITY, payload=payload)
        return True

    async def enqueue_scans_for_all(self) -> int:
        count = 0
        for source in await self._sources.list():
            if source.enabled:
                count += int(await self.enqueue_scan(source.id))
        return count

    async def park_failed_files(self, source_id: str) -> bool:
        """Expose failed files as a retryable FAILED `backup_scan` job (retrying it re-queues them)."""
        if await self._job_state.has_parked_retry(source_id):
            return False
        job = await self._jobs.enqueue(
            type=JobType.BACKUP_SCAN,
            priority=BACKUP_SCAN_PRIORITY,
            payload={"source_id": source_id, "retry_failed": True, "parked": True},
        )
        await self._jobs.save(
            replace(job, status=JobStatus.FAILED, attempts=0, error="backup_files_failed", updated_at=self._clock.now())
        )
        return True

    async def ensure_upload_job(self, *, delay_seconds: float = 0) -> bool:
        if await self._job_state.has_waiting(JobType.BACKUP_UPLOAD):
            return False
        job = await self._jobs.enqueue(
            type=JobType.BACKUP_UPLOAD, priority=BACKUP_UPLOAD_PRIORITY, payload={}, max_attempts=5
        )
        if delay_seconds > 0:
            await self._jobs.save(replace(job, run_after=self._clock.now() + timedelta(seconds=delay_seconds)))
        return True

    # Worker work -------------------------------------------------------------------------------------

    async def scan_source(
        self, source_id: str, *, paths: tuple[str, ...] | None = None, retry_failed: bool = False
    ) -> ScanSummary:
        source = await self._sources.get(source_id)
        if source is None or not source.enabled:
            return ScanSummary(skipped=True)
        if (await self._policy.get()).effective_paused:
            return ScanSummary(skipped=True)
        root = Path(source.path)
        try:
            info = await asyncio.to_thread(self._scanner.inspect, source.path)
        except ValueError:
            info = PathInfo(path=root, exists=False, is_dir=False, readable=False, is_root=False)
        if not (info.exists and info.is_dir and info.readable):
            await self._sources.save(replace(source, error_code="source_unavailable", updated_at=self._clock.now()))
            return ScanSummary(skipped=True)

        known = await self._files.snapshot(source_id)
        exclude = (self._data_dir.resolve(),)
        changed: list[BackupFile] = []
        vanished: list[str] = []
        vanished_prefixes: list[str] = []
        now = self._clock.now()

        def consider(item: ScannedFile) -> None:
            existing = known.get(item.relative_path)
            if needs_upload(existing, item, retry_failed=retry_failed):
                changed.append(
                    BackupFile(
                        source_id=source_id,
                        relative_path=item.relative_path,
                        size_bytes=item.size_bytes,
                        mtime_ns=item.mtime_ns,
                        state=BackupFileState.PENDING,
                        updated_at=now,
                    )
                )

        if paths is None:
            scanned = await asyncio.to_thread(lambda: list(self._scanner.scan(root, exclude=exclude)))
            for item in scanned:
                consider(item)
            seen = {item.relative_path for item in scanned}
            vanished = [relative for relative in known if relative not in seen]
        else:
            for absolute in paths:
                relative = self._scanner.relative(root, absolute)
                if relative is None or _excluded(root / relative, exclude):
                    continue
                item = await asyncio.to_thread(self._scanner.stat, root, relative)
                if item is not None:
                    consider(item)
                elif await asyncio.to_thread(self._scanner.is_directory, root, relative):
                    for nested in await asyncio.to_thread(
                        lambda rel=relative: list(self._scanner.scan(root, start=rel, exclude=exclude))
                    ):
                        consider(nested)
                else:
                    vanished.append(relative)
                    vanished_prefixes.append(relative)

        if changed:
            await self._files.save_many(tuple(changed))
        removed = 0
        if vanished:
            removed = await self._files.delete_paths(source_id, tuple(vanished), prefixes=tuple(vanished_prefixes))
        await self._sources.save(replace(source, last_scan_at=now, error_code=None, updated_at=now))
        counts = await self._files.counts(source_id)
        if counts.get(BackupFileState.PENDING.value, 0) or counts.get(BackupFileState.UPLOADING.value, 0):
            await self.ensure_upload_job()
        return ScanSummary(queued=len(changed), removed=removed)

    async def upload_pending(self, *, limit: int = BACKUP_UPLOAD_BATCH) -> int:
        """Ingest a batch of pending files; re-enqueues itself while work remains."""
        if self._ingestion is None:
            raise RuntimeError("Backup ingestion is not configured")
        if (await self._policy.get()).effective_paused:
            return 0
        batch = await self._files.pending(limit=limit)
        sources = {source.id: source for source in await self._sources.list()}
        processed = 0
        unsettled = 0
        failed_sources: set[str] = set()
        for file in batch:
            source = sources.get(file.source_id)
            if source is None or not source.enabled:
                continue
            outcome = await self._upload_one(source, file)
            if outcome is None:
                unsettled += 1
                continue
            processed += 1
            if outcome == BackupFileState.FAILED:
                failed_sources.add(source.id)
        for source_id in sorted(failed_sources):
            await self.park_failed_files(source_id)
        if batch and await self._files.pending(limit=1):
            await self.ensure_upload_job(delay_seconds=self._settle_seconds if unsettled and not processed else 0)
        return processed

    async def _upload_one(self, source: BackupSource, file: BackupFile) -> BackupFileState | None:
        """Resulting state, or None when the file is still being written and must wait."""
        assert self._ingestion is not None
        root = Path(source.path)
        current = await asyncio.to_thread(self._scanner.stat, root, file.relative_path)
        if current is None:
            await self._files.delete_paths(source.id, (file.relative_path,))
            return BackupFileState.SKIPPED
        if self._wall_clock() - current.mtime_ns / 1_000_000_000 < self._settle_seconds:
            return None
        uploading = replace(
            file,
            size_bytes=current.size_bytes,
            mtime_ns=current.mtime_ns,
            state=BackupFileState.UPLOADING,
            error_code=None,
            updated_at=self._clock.now(),
        )
        await self._files.save_many((uploading,))
        relative = PurePosixPath(file.relative_path)
        try:
            result = await self._ingestion.upload_file(
                UploadedAssetFile(
                    source_path=root.joinpath(*relative.parts),
                    original_filename=relative.name,
                    allow_duplicate=True,
                    folder_resolver=lambda mode: self._folder_for(source, relative.parent, mode),
                )
            )
        except DomainError as exc:
            await self._files.save_many((replace(uploading, state=BackupFileState.FAILED, error_code=exc.code[:64]),))
            return BackupFileState.FAILED
        except OSError:
            await self._files.save_many((replace(uploading, state=BackupFileState.FAILED, error_code="source_unreadable"),))
            return BackupFileState.FAILED
        # The row keeps the stat taken before ingestion, so a file edited meanwhile is picked up by the next scan.
        await self._files.save_many(
            (
                replace(
                    uploading,
                    state=BackupFileState.DONE,
                    sha256=result.asset.metadata.sha256,
                    asset_id=result.asset.id,
                    updated_at=self._clock.now(),
                ),
            )
        )
        return BackupFileState.DONE

    async def _folder_for(self, source: BackupSource, relative_dir: PurePosixPath, mode: AssetMode) -> str | None:
        if mode == AssetMode.PHOTOS or self._folders is None or self._folder_creator is None:
            return None
        names = [BACKUP_ROOT_FOLDER, source.label, *(part for part in relative_dir.parts if part not in {"", "."})]
        parent_id: str | None = None
        for name in names:
            name = name.strip()[:255] or "_"
            existing = await self._folders.find_child(parent_id, name)
            if existing is None:
                existing = (await self._folder_creator.create_folder(CreateFolderCommand(name=name, parent_id=parent_id))).id
            parent_id = existing
        return parent_id

    # Helpers -----------------------------------------------------------------------------------------

    async def _require(self, source_id: str) -> BackupSource:
        source = await self._sources.get(source_id)
        if source is None:
            raise BackupSourceNotFoundError(source_id)
        return source

    async def _with_progress(self, source: BackupSource, policy: BackupPolicy, scanning: set[str]) -> BackupSource:
        counts = await self._files.counts(source.id)
        done = counts.get(BackupFileState.DONE.value, 0) + counts.get(BackupFileState.SKIPPED.value, 0)
        pending = counts.get(BackupFileState.PENDING.value, 0) + counts.get(BackupFileState.UPLOADING.value, 0)
        total = sum(counts.get(state.value, 0) for state in BackupFileState)
        if not source.enabled or policy.effective_paused:
            state = BackupSourceState.PAUSED
        elif source.error_code:
            state = BackupSourceState.ERROR
        elif source.id in scanning:
            state = BackupSourceState.SCANNING
        elif pending:
            state = BackupSourceState.UPLOADING
        else:
            state = BackupSourceState.IDLE
        return replace(
            source,
            state=state,
            files_total=total,
            files_done=done,
            files_pending=pending,
            bytes_pending=counts.get("bytes_pending", 0),
        )


def _clean_label(label: str | None) -> str | None:
    if label is None:
        return None
    cleaned = " ".join(label.replace("/", " ").replace("\\", " ").split())[:MAX_LABEL_LENGTH]
    return cleaned or None


def _excluded(path: Path, exclude: tuple[Path, ...]) -> bool:
    return any(path == item or path.is_relative_to(item) for item in exclude)
