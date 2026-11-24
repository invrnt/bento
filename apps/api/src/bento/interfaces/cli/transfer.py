"""Upload/download engine (`architecture/cli-runtime.md` § Uploads).

Uploads: walk → hash (SHA-256) → `POST /assets/lookup` (skip contents that already exist) → ensure each
destination folder once, parents first (`POST /drive/folders/ensure`) → concurrent streaming uploads with
retries. Re-running an interrupted upload transfers only what is missing.
"""

from __future__ import annotations

import contextlib
import mimetypes
import os
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bento.interfaces.cli.client import BentoClient
from bento.interfaces.cli.errors import CliError
from bento.interfaces.cli.local_files import LocalFile, WalkOptions, collect, safe_local_name, sha256_file
from bento.interfaces.cli.paths import BentoRef, join_path, join_segments, parse_ref

LOOKUP_BATCH = 500
HASH_WORKERS = 4
UPLOAD_ATTEMPTS = 4
UPLOAD_TIMEOUT = 600.0
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class UploadOptions:
    to: str = "/"
    walk: WalkOptions = field(default_factory=WalkOptions)
    jobs: int = 2
    dry_run: bool = False
    dedupe: bool = True


@dataclass
class UploadEntry:
    local_path: str
    status: str  # uploaded | duplicate | skipped | failed | planned
    size_bytes: int = 0
    sha256: str | None = None
    relative_dir: tuple[str, ...] = ()
    asset: dict[str, Any] | None = None
    path: str | None = None
    reason: str | None = None
    error: dict[str, Any] | None = None
    source: LocalFile | None = None

    def public(self) -> dict[str, Any]:
        data: dict[str, Any] = {"local_path": self.local_path, "status": self.status, "size_bytes": self.size_bytes}
        for key in ("sha256", "asset", "path", "reason", "error"):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        return data


ProgressHook = Callable[[int], None]


def _failure(error: Exception) -> dict[str, Any]:
    if isinstance(error, CliError):
        return {"code": error.code, "message": error.message, "details": error.details}
    if isinstance(error, OSError):
        return {"code": "local_read_failed", "message": error.strerror or type(error).__name__, "details": {}}
    return {"code": "unexpected_error", "message": type(error).__name__, "details": {}}


def _retryable(error: CliError) -> bool:
    return error.code == "bento_unreachable" or (error.status in _RETRYABLE_STATUS and error.code != "upload_too_large")


class Uploader:
    def __init__(self, api: BentoClient, options: UploadOptions, *, on_bytes: ProgressHook | None = None) -> None:
        self.api = api
        self.options = options
        self.on_bytes = on_bytes or (lambda _: None)
        self._folders: dict[tuple[str, ...], str | None] = {}
        self._folder_paths: dict[tuple[str, ...], str] = {}
        self._lock = threading.Lock()

    # Planning ----------------------------------------------------------------------------------

    def plan(self, inputs: Sequence[str]) -> list[UploadEntry]:
        walked = collect(inputs, self.options.walk)
        entries: list[UploadEntry] = [
            UploadEntry(
                local_path=str(path),
                status="failed",
                error={"code": "local_not_found", "message": "Local path not found", "details": {}},
            )
            for path in walked.missing
        ]
        entries += [UploadEntry(local_path=str(item.path), status="skipped", reason=item.reason) for item in walked.skipped]
        entries += [
            UploadEntry(
                local_path=str(item.path),
                status="planned",
                size_bytes=item.size,
                relative_dir=item.relative_dir,
                source=item,
            )
            for item in walked.files
        ]
        return entries

    def hash_all(self, entries: Sequence[UploadEntry]) -> None:
        pending = [entry for entry in entries if entry.status == "planned"]

        def work(entry: UploadEntry) -> None:
            try:
                assert entry.source is not None
                entry.sha256 = sha256_file(entry.source.path)
            except OSError as exc:
                entry.status = "failed"
                entry.error = _failure(exc)

        with ThreadPoolExecutor(max_workers=HASH_WORKERS) as pool:
            list(pool.map(work, pending))

    def lookup(self, entries: Sequence[UploadEntry]) -> None:
        planned = [entry for entry in entries if entry.status == "planned" and entry.sha256]
        if self.options.dedupe:
            hashes = list(dict.fromkeys(entry.sha256 for entry in planned if entry.sha256))
            existing: dict[str, Any] = {}
            for start in range(0, len(hashes), LOOKUP_BATCH):
                data = self.api.post("/assets/lookup", {"sha256": hashes[start : start + LOOKUP_BATCH]})
                if isinstance(data, dict) and isinstance(data.get("items"), dict):
                    existing.update(data["items"])
            for entry in planned:
                match = existing.get(entry.sha256 or "")
                if isinstance(match, dict):
                    entry.status = "duplicate"
                    entry.asset = match.get("asset")
                    entry.path = match.get("path")
        # Identical contents inside this run upload once; the others are duplicates of the first.
        first: dict[str, UploadEntry] = {}
        for entry in planned:
            if entry.status != "planned" or not entry.sha256:
                continue
            if entry.sha256 in first:
                entry.status = "duplicate"
                entry.reason = "same_content_in_batch"
            else:
                first[entry.sha256] = entry

    # Folders -----------------------------------------------------------------------------------

    def _base(self) -> BentoRef:
        ref = parse_ref(self.options.to)
        if ref.item_id is None:
            return ref
        resolved = self.api.get("/drive/resolve", {"path": ref.text})
        if resolved.get("kind") not in {"root", "folder"}:
            raise CliError("not_a_folder", "The destination is a file, not a folder", {"path": resolved.get("path")})
        return parse_ref(str(resolved.get("path") or "/"))

    def ensure_folders(self, entries: Sequence[UploadEntry]) -> None:
        base = self._base()
        needed = sorted({entry.relative_dir for entry in entries if entry.status == "planned"}, key=lambda parts: (len(parts), parts))
        for relative in needed:
            target = join_segments(base, relative)
            try:
                if target.is_root:
                    self._folders[relative] = None
                    self._folder_paths[relative] = "/"
                    continue
                data = self.api.post("/drive/folders/ensure", {"path": target.canonical})
                folder = data.get("folder") or {}
                self._folders[relative] = folder.get("id")
                self._folder_paths[relative] = str(data.get("path") or target.canonical)
            except CliError as error:
                if error.exit_code in {5, 6}:
                    raise
                for entry in entries:
                    if entry.status == "planned" and entry.relative_dir == relative:
                        entry.status = "failed"
                        entry.error = _failure(error)

    # Upload ------------------------------------------------------------------------------------

    def upload_one(self, entry: UploadEntry) -> None:
        assert entry.source is not None
        folder_id = self._folders.get(entry.relative_dir)
        name = entry.source.name
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        last_error: Exception | None = None
        for attempt in range(UPLOAD_ATTEMPTS):
            try:
                with entry.source.path.open("rb") as handle:
                    data = {"folder_id": folder_id} if folder_id else None
                    asset = self.api.request(
                        "POST",
                        "/assets/upload",
                        files={"file": (name, handle, mime)},
                        data=data,
                        timeout=UPLOAD_TIMEOUT,
                    )
                entry.asset = asset
                if asset.get("duplicate"):
                    entry.status = "duplicate"
                else:
                    entry.status = "uploaded"
                    entry.path = join_path(self._folder_paths.get(entry.relative_dir, "/"), str(asset.get("filename") or name))
                self.on_bytes(entry.size_bytes)
                return
            except CliError as error:
                last_error = error
                if not _retryable(error) or attempt + 1 == UPLOAD_ATTEMPTS:
                    break
                retry_after = error.details.get("retry_after_seconds")
                delay = float(retry_after) if isinstance(retry_after, int) and retry_after <= 30 else 0.5 * 2**attempt
                time.sleep(delay)
            except OSError as error:
                last_error = error
                break
        entry.status = "failed"
        entry.error = _failure(last_error) if last_error else None
        self.on_bytes(entry.size_bytes)

    def upload_all(self, entries: Sequence[UploadEntry]) -> None:
        pending = [entry for entry in entries if entry.status == "planned"]
        with ThreadPoolExecutor(max_workers=max(1, self.options.jobs)) as pool:
            list(pool.map(self.upload_one, pending))
        duplicates = [entry for entry in entries if entry.status == "duplicate" and entry.path is None and entry.asset]
        if duplicates:
            with contextlib.suppress(CliError):
                data = self.api.post("/drive/paths", {"ids": [entry.asset["id"] for entry in duplicates if entry.asset]})
                found = data.get("paths") or {}
                for entry in duplicates:
                    if entry.asset:
                        entry.path = found.get(entry.asset["id"])
        # In-batch duplicates point at the copy uploaded in this run.
        by_hash = {entry.sha256: entry for entry in entries if entry.status == "uploaded" and entry.sha256}
        for entry in entries:
            if entry.reason == "same_content_in_batch" and entry.sha256 in by_hash:
                source = by_hash[entry.sha256]
                entry.asset, entry.path = source.asset, source.path

    def run(self, inputs: Sequence[str]) -> dict[str, Any]:
        entries = self.plan(inputs)
        self.hash_all(entries)
        self.lookup(entries)
        if not self.options.dry_run:
            self.ensure_folders(entries)
            self.upload_all(entries)
        return summarize(entries, to=self.options.to, dry_run=self.options.dry_run)


def planned_bytes(entries: Sequence[UploadEntry]) -> int:
    return sum(entry.size_bytes for entry in entries if entry.status == "planned")


def summarize(entries: Sequence[UploadEntry], *, to: str, dry_run: bool) -> dict[str, Any]:
    counts = {status: sum(1 for entry in entries if entry.status == status) for status in ("uploaded", "duplicate", "skipped", "failed", "planned")}
    document: dict[str, Any] = {
        "to": to,
        "dry_run": dry_run,
        "uploaded": counts["uploaded"],
        "duplicates": counts["duplicate"],
        "skipped": counts["skipped"],
        "failed": counts["failed"],
        "bytes": sum(entry.size_bytes for entry in entries if entry.status == "uploaded"),
        "items": [entry.public() for entry in entries],
    }
    if dry_run:
        document["planned"] = counts["planned"]
        document["planned_bytes"] = planned_bytes(entries)
    return document


# Downloads -----------------------------------------------------------------------------------


@dataclass
class DownloadEntry:
    path: str
    local_path: str
    status: str  # downloaded | skipped | failed
    size_bytes: int = 0
    id: str | None = None
    reason: str | None = None
    error: dict[str, Any] | None = None

    def public(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "path": self.path, "local_path": self.local_path, "status": self.status, "size_bytes": self.size_bytes}
        if self.reason:
            data["reason"] = self.reason
        if self.error:
            data["error"] = self.error
        return data


class Downloader:
    def __init__(self, api: BentoClient, *, overwrite: bool, on_bytes: ProgressHook | None = None) -> None:
        self.api = api
        self.overwrite = overwrite
        self.on_bytes = on_bytes or (lambda _: None)
        self.entries: list[DownloadEntry] = []
        self._claimed: set[Path] = set()

    def _target(self, directory: Path, name: str) -> Path:
        safe = safe_local_name(name)
        candidate = directory / safe
        stem, suffix = os.path.splitext(safe)
        counter = 2
        while candidate in self._claimed:
            candidate = directory / f"{stem} ({counter}){suffix}"
            counter += 1
        self._claimed.add(candidate)
        return candidate

    def file(self, asset: dict[str, Any], bento_path: str, directory: Path) -> None:
        target = self._target(directory, str(asset.get("filename") or asset.get("id")))
        size = int(asset.get("size_bytes") or 0)
        entry = DownloadEntry(path=bento_path, local_path=str(target), status="downloaded", size_bytes=size, id=asset.get("id"))
        self.entries.append(entry)
        if target.exists() and not self.overwrite:
            entry.status, entry.reason = "skipped", "exists"
            self.on_bytes(size)
            return
        partial = target.with_name(f".{target.name}.bento-part")
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with self.api.stream("GET", f"/assets/{asset['id']}/download") as response, partial.open("wb") as handle:
                for chunk in response.iter_bytes(1024 * 1024):
                    handle.write(chunk)
            os.replace(partial, target)
        except (CliError, OSError) as error:
            with contextlib.suppress(OSError):
                partial.unlink(missing_ok=True)
            entry.status, entry.error = "failed", _failure(error)
        self.on_bytes(size)

    def folder(self, folder_id: str | None, bento_path: str, directory: Path) -> None:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.entries.append(DownloadEntry(path=bento_path, local_path=str(directory), status="failed", error=_failure(error)))
            return
        cursor: str | None = None
        while True:
            page = self.api.get("/drive/items", {"folder_id": folder_id, "cursor": cursor, "limit": 200})
            for item in page.get("items") or []:
                child_path = join_path(bento_path, str(item.get("name", "")))
                if item.get("type") == "folder":
                    child_dir = self._target(directory, str(item.get("name") or item.get("id")))
                    self.folder(str(item["id"]), child_path, child_dir)
                elif item.get("asset"):
                    self.file(item["asset"], child_path, directory)
            cursor = page.get("next_cursor")
            if not cursor:
                return

    def summary(self) -> dict[str, Any]:
        return {
            "downloaded": sum(1 for entry in self.entries if entry.status == "downloaded"),
            "skipped": sum(1 for entry in self.entries if entry.status == "skipped"),
            "failed": sum(1 for entry in self.entries if entry.status == "failed"),
            "bytes": sum(entry.size_bytes for entry in self.entries if entry.status == "downloaded"),
            "items": [entry.public() for entry in self.entries],
        }
