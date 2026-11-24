"""Automatic one-way folder backup: sources, incremental scans, debounced watcher events, and policy."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import timedelta
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol

from bento.application.drive import CreateFolderCommand
from bento.application.ingestion.assets import UploadedAssetFile
from bento.application.upload import UploadAssetResult
from bento.domain.assets import AssetMode
from bento.domain.backup import (
    BackupFile,
    BackupFileState,
    BackupPolicy,
    BackupSource,
    BackupSourceKind,
    BackupSourceState,
    BackupSuggestion,
    MediaItem,
)
from bento.domain.drive import Folder
from bento.domain.errors import BackupSourceInvalidError, DomainError, ValidationFailedError
from bento.domain.jobs import JobStatus, JobType
from bento.application.work_budget import check_safe_boundary
from bento.ports.backup import BackupPolicyRepositoryPort, BackupSourceRepositoryPort, BackupSuggestionsPort, MediaLibraryPort
from bento.ports.jobs import JobQueuePort
from bento.ports.repositories import ClockPort

BACKUP_ROOT_FOLDER = "Respaldo"
PHONE_ROOT_FOLDER = "Del teléfono"
MEDIA_STORE_PREFIX = "media_store:"
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


class MediaStagingPort(Protocol):
    """Streams phone media once: hashing for dedupe, or copying into a staging file for local-first ingest."""

    def sha256(self, stream: BinaryIO) -> str: ...

    def stage(self, stream: BinaryIO, filename: str) -> Path: ...


class MediaBackupCatalogPort(Protocol):
    async def asset_for_sha256(self, sha256: str) -> str | None:
        """A live asset with this content (from any device), or None."""
        ...

    async def done_media_files(self, source_ids: tuple[str, ...]) -> tuple[BackupFile, ...]: ...

    async def verified_originals(self, asset_ids: tuple[str, ...]) -> dict[str, str]:
        """Asset id -> plaintext sha256 for assets whose original has a confirmed remote copy."""
        ...

    async def mark_freed(self, source_ids: tuple[str, ...], media_ids: tuple[str, ...]) -> int: ...

    async def summary(self, since: datetime) -> tuple[int, datetime | None]:
        """(files done since `since`, last time any file finished)."""
        ...


@dataclass(frozen=True, slots=True)
class FreeUpSpaceItem:
    asset_id: str
    media_id: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class FreeUpSpacePreview:
    items: tuple[FreeUpSpaceItem, ...]

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.items)


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
        media: MediaLibraryPort | None = None,
        media_staging: MediaStagingPort | None = None,
        media_catalog: MediaBackupCatalogPort | None = None,
        device_name: str = "",
    ) -> None:
        self._media = media
        self._media_staging = media_staging
        self._media_catalog = media_catalog
        self._device_name = device_name
        self._media_items: dict[str, dict[str, MediaItem]] = {}
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

    async def add_media_source(self, bucket_id: str, label: str | None = None) -> BackupSource:
        """Back up a MediaStore bucket into `Del teléfono/<device name>/<bucket name>` (Android)."""
        if self._media is None:
            raise BackupSourceInvalidError("media_store_unavailable")
        bucket_id = (bucket_id or "").strip()
        if not bucket_id or len(bucket_id) > 64:
            raise BackupSourceInvalidError("invalid_bucket")
        buckets = {bucket.bucket_id: bucket for bucket in await asyncio.to_thread(self._media.buckets)}
        bucket = buckets.get(bucket_id)
        if bucket is None:
            raise BackupSourceInvalidError("not_found")
        path = f"{MEDIA_STORE_PREFIX}{bucket_id}"
        if any(source.path == path for source in await self._sources.list()):
            raise BackupSourceInvalidError("duplicate")
        now = self._clock.now()
        source = BackupSource(
            id=self._new_id(),
            path=path,
            label=_clean_label(label) or _clean_label(bucket.name) or "Fotos",
            enabled=True,
            created_at=now,
            updated_at=now,
            kind=BackupSourceKind.MEDIA_STORE,
            bucket_id=bucket_id,
        )
        await self._sources.save(source)
        await self._media_folder(source)
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
        if source.kind == BackupSourceKind.MEDIA_STORE:
            return await self._scan_media(source, retry_failed=retry_failed)
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
            check_safe_boundary()  # bounded runs stop between files; the rest stays pending
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
        if source.kind == BackupSourceKind.MEDIA_STORE:
            return await self._upload_media(source, file)
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

    # Phone media (MediaStore) ------------------------------------------------------------------------

    async def _scan_media(self, source: BackupSource, *, retry_failed: bool) -> ScanSummary:
        if self._media is None or source.bucket_id is None:
            await self._sources.save(replace(source, error_code="source_unavailable", updated_at=self._clock.now()))
            return ScanSummary(skipped=True)
        try:
            items = await asyncio.to_thread(lambda: list(self._media.scan(source.bucket_id)))  # type: ignore[union-attr,arg-type]
        except Exception:  # noqa: BLE001 - bridge failures (permission revoked) surface as a source error
            await self._sources.save(replace(source, error_code="source_unavailable", updated_at=self._clock.now()))
            return ScanSummary(skipped=True)
        self._media_items[source.id] = {item.media_id: item for item in items}
        known = await self._files.snapshot(source.id)
        by_key = {file.source_key: file for file in known.values() if file.source_key}
        now = self._clock.now()
        changed: list[BackupFile] = []
        stale_paths: list[str] = []
        for item in items:
            existing = by_key.get(item.media_id)
            relative = _media_relative_path(item)
            if existing is not None and existing.relative_path != relative:
                stale_paths.append(existing.relative_path)
                existing = None
            scanned = ScannedFile(relative_path=relative, size_bytes=item.size_bytes, mtime_ns=item.change_token)
            if existing is not None and existing.state == BackupFileState.FREED:
                continue
            if needs_upload(existing, scanned, retry_failed=retry_failed):
                changed.append(
                    BackupFile(
                        source_id=source.id,
                        relative_path=relative,
                        size_bytes=item.size_bytes,
                        mtime_ns=item.change_token,
                        state=BackupFileState.PENDING,
                        updated_at=now,
                        source_key=item.media_id,
                    )
                )
        seen = {item.media_id for item in items}
        vanished = [
            file.relative_path
            for file in known.values()
            if file.source_key not in seen and file.state != BackupFileState.FREED
        ]
        if changed:
            await self._files.save_many(tuple(changed))
        removed = 0
        if vanished or stale_paths:
            removed = await self._files.delete_paths(source.id, tuple(vanished + stale_paths))
        await self._sources.save(replace(source, last_scan_at=now, error_code=None, updated_at=now))
        counts = await self._files.counts(source.id)
        if counts.get(BackupFileState.PENDING.value, 0) or counts.get(BackupFileState.UPLOADING.value, 0):
            await self.ensure_upload_job()
        return ScanSummary(queued=len(changed), removed=removed)

    async def _upload_media(self, source: BackupSource, file: BackupFile) -> BackupFileState:
        """Hash while streaming from the fd; a vault asset with the same sha256 is linked (no upload), otherwise
        the file is staged and ingested local-first (`origin=device`), then uploads follow by policy."""
        assert self._ingestion is not None
        if self._media is None or self._media_staging is None or file.source_key is None:
            await self._files.save_many((replace(file, state=BackupFileState.FAILED, error_code="source_unavailable"),))
            return BackupFileState.FAILED
        item = await self._media_item(source, file.source_key)
        if item is None:
            await self._files.delete_paths(source.id, (file.relative_path,))
            return BackupFileState.SKIPPED
        uploading = replace(
            file,
            size_bytes=item.size_bytes,
            mtime_ns=item.change_token,
            state=BackupFileState.UPLOADING,
            error_code=None,
            updated_at=self._clock.now(),
        )
        await self._files.save_many((uploading,))
        require_original = await asyncio.to_thread(self._location_access)
        staging = self._media_staging
        media = self._media
        try:
            sha256 = await asyncio.to_thread(_with_stream, media, item, require_original, staging.sha256)
            asset_id = await self._media_catalog.asset_for_sha256(sha256) if self._media_catalog is not None else None
            if asset_id is None:
                staged = await asyncio.to_thread(
                    _with_stream, media, item, require_original, lambda stream: staging.stage(stream, item.display_name)
                )
                try:
                    result = await self._ingestion.upload_file(
                        UploadedAssetFile(
                            source_path=staged,
                            original_filename=item.display_name,
                            declared_mime_type=item.mime_type,
                            allow_duplicate=True,
                            folder_resolver=lambda _mode: self._media_folder(source),
                            taken_at=_taken_at(item),
                        )
                    )
                finally:
                    staged.unlink(missing_ok=True)
                asset_id = result.asset.id
                sha256 = result.asset.metadata.sha256
        except DomainError as exc:
            await self._files.save_many((replace(uploading, state=BackupFileState.FAILED, error_code=exc.code[:64]),))
            return BackupFileState.FAILED
        except Exception:  # noqa: BLE001 - unreadable content, revoked permission, bridge failure
            await self._files.save_many((replace(uploading, state=BackupFileState.FAILED, error_code="source_unreadable"),))
            return BackupFileState.FAILED
        await self._files.save_many(
            (replace(uploading, state=BackupFileState.DONE, sha256=sha256, asset_id=asset_id, updated_at=self._clock.now()),)
        )
        return BackupFileState.DONE

    async def _media_item(self, source: BackupSource, media_id: str) -> MediaItem | None:
        items = self._media_items.get(source.id)
        if items is None or media_id not in items:
            if self._media is None or source.bucket_id is None:
                return None
            scanned = await asyncio.to_thread(lambda: list(self._media.scan(source.bucket_id)))  # type: ignore[union-attr,arg-type]
            items = self._media_items[source.id] = {item.media_id: item for item in scanned}
        return items.get(media_id)

    def _location_access(self) -> bool:
        try:
            return bool(self._media is not None and self._media.access().location)
        except Exception:  # noqa: BLE001
            return False

    async def _media_folder(self, source: BackupSource) -> str | None:
        if self._folders is None or self._folder_creator is None:
            return None
        parent_id: str | None = None
        for name in (PHONE_ROOT_FOLDER, self._device_name or "Teléfono", source.label):
            name = _clean_label(name) or "_"
            existing = await self._folders.find_child(parent_id, name)
            if existing is None:
                existing = (await self._folder_creator.create_folder(CreateFolderCommand(name=name, parent_id=parent_id))).id
            parent_id = existing
        return parent_id

    async def free_up_space_preview(self, source_id: str | None = None) -> FreeUpSpacePreview:
        """Phone originals whose upload is verified: remote copy confirmed and sha256 equal to the local hash."""
        if self._media is None or self._media_catalog is None:
            return FreeUpSpacePreview(items=())
        candidates = await self._verified_media_files(await self._media_source_ids(source_id))
        present = await asyncio.to_thread(self._media.existing, tuple(file.source_key or "" for file in candidates))
        return FreeUpSpacePreview(
            items=tuple(
                FreeUpSpaceItem(asset_id=file.asset_id or "", media_id=file.source_key or "", size_bytes=file.size_bytes)
                for file in candidates
                if file.source_key in present
            )
        )

    async def free_up_space_confirm(self, media_ids: tuple[str, ...]) -> int:
        """Kotlin deleted these originals through `MediaStore.createDeleteRequest`; assets and thumbnails stay."""
        if self._media_catalog is None or not media_ids:
            return 0
        # Only verified items count: an id that was not uploaded and verified is ignored. (They are gone from
        # MediaStore by now, so presence is not checked here.)
        source_ids = await self._media_source_ids(None)
        verified = {file.source_key for file in await self._verified_media_files(source_ids)}
        accepted = tuple(media_id for media_id in media_ids if media_id in verified)
        return await self._media_catalog.mark_freed(source_ids, accepted)

    async def _verified_media_files(self, source_ids: tuple[str, ...]) -> list[BackupFile]:
        assert self._media_catalog is not None
        files = await self._media_catalog.done_media_files(source_ids)
        verified = await self._media_catalog.verified_originals(tuple(sorted({f.asset_id for f in files if f.asset_id})))
        return [
            file
            for file in files
            if file.asset_id and file.source_key and file.sha256 and verified.get(file.asset_id) == file.sha256
        ]

    async def media_summary(self) -> dict[str, object]:
        today = self._clock.now().astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        uploaded_today, last_backup_at = (
            await self._media_catalog.summary(today) if self._media_catalog is not None else (0, None)
        )
        access = None
        if self._media is not None:
            try:
                access = await asyncio.to_thread(self._media.access)
            except Exception:  # noqa: BLE001
                access = None
        return {
            "uploaded_today": uploaded_today,
            "last_backup_at": last_backup_at,
            "partial_access": bool(access and access.partial and not access.full),
            "location_access": True if self._media is None else bool(access and access.location),
        }

    async def pending_files(self) -> int:
        total = 0
        for source in await self._sources.list():
            if source.enabled:
                counts = await self._files.counts(source.id)
                total += counts.get(BackupFileState.PENDING.value, 0) + counts.get(BackupFileState.UPLOADING.value, 0)
        return total

    async def _media_source_ids(self, source_id: str | None) -> tuple[str, ...]:
        sources = [s for s in await self._sources.list() if s.kind == BackupSourceKind.MEDIA_STORE]
        if source_id is not None:
            sources = [s for s in sources if s.id == source_id]
            if not sources:
                raise BackupSourceNotFoundError(source_id)
        return tuple(source.id for source in sources)

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


def _media_relative_path(item: MediaItem) -> str:
    name = item.display_name.replace("/", "_").replace("\x00", "").strip() or item.media_id
    return name[:MAX_LABEL_LENGTH]


def _taken_at(item: MediaItem) -> datetime | None:
    if item.date_taken_ms is None or item.date_taken_ms <= 0:
        return None
    return datetime.fromtimestamp(item.date_taken_ms / 1000, tz=UTC)


def _with_stream(media: MediaLibraryPort, item: MediaItem, require_original: bool, use: Callable[[BinaryIO], object]) -> object:
    with media.open(item, require_original=require_original) as stream:
        return use(stream)
