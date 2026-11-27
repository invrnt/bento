"""`ModelDownloaderPort` over `urllib`: resumable, verified downloads of pinned model files.

- Resumes from the size of `dest_part` with `Range: bytes=<n>-` (plus `If-Range` when a strong ETag is known)
  and requires `206` with a matching `Content-Range`. A `200` (the server ignored the range or the ETag
  changed), a changed ETag or a bad `Content-Range` restarts the file from zero.
- Tries `file.urls` in order (pinned Hugging Face first, then the Bento mirror). A `4xx` moves on to the next
  URL; a connection that cannot be opened or a `5xx`/`429` also moves on, and makes the final result `network`
  (retryable) instead of `failed`. A connection that drops mid-body, or ends before its `Content-Length`, returns
  `network` right away: the `.part` keeps every byte received. `timeout_seconds` (30 s) bounds the connect and
  every read, so a connection that stays open but sends nothing also ends as `network` instead of hanging.
- Honors the standard proxy variables (`HTTPS_PROXY`, `NO_PROXY`) through `urllib`'s default `ProxyHandler`.
- Hashes while streaming (re-reading the existing `.part` first on resume). On a match the file is fsynced
  and atomically renamed to its final name; on a mismatch the `.part` is deleted.
- Calls `should_stop()` between 4 MiB blocks (the caller also checks the worker's safe boundary there) and
  `on_progress` at most every 250 ms, from the download thread.
- Privacy: the only headers are a generic `User-Agent`, `Accept-Encoding: identity` and the range headers. No
  cookies, no `Authorization`. Redirects must stay on `https`. URLs are never logged.
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import http.client
import ipaddress
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlsplit

from bento.domain.smart_search import ModelFile
from bento.ports.models import DownloadOutcome, DownloadResult, ProgressCallback, StopCheck

LOGGER = logging.getLogger("bento.models.download")

BLOCK_BYTES = 4 * 1024 * 1024
READ_BYTES = 64 * 1024
PROGRESS_INTERVAL_SECONDS = 0.25
DEFAULT_TIMEOUT_SECONDS = 30.0
PART_SUFFIX = ".part"
META_SUFFIX = ".meta"

_CONTENT_RANGE_RE = re.compile(r"^\s*bytes\s+(\d+)-(\d+)/(\d+|\*)\s*$", re.IGNORECASE)
_NO_SPACE_ERRNOS = {errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)}


class _Restart(Exception):
    """The server's answer means the `.part` must be discarded and the file fetched from zero."""


@dataclass(slots=True)
class _UrlAttempt:
    outcome: DownloadOutcome | None = None
    transient: bool = False


@dataclass(slots=True)
class _Progress:
    callback: ProgressCallback
    total: int
    interval: float
    monotonic: Callable[[], float]
    last_at: float = field(default=float("-inf"))

    def report(self, done: int, *, force: bool = False) -> None:
        now = self.monotonic()
        if force or now - self.last_at >= self.interval:
            self.last_at = now
            self.callback(done, self.total)


class HttpModelDownloader:
    def __init__(
        self,
        *,
        user_agent: str = "Bento",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        block_bytes: int = BLOCK_BYTES,
        read_bytes: int = READ_BYTES,
        progress_interval_seconds: float = PROGRESS_INTERVAL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        rewrite_url: Callable[[str], str] | None = None,
        allow_http_loopback: bool = False,
    ) -> None:
        """`rewrite_url` and `allow_http_loopback` are test seams: they point the pinned `https` URLs at a
        local fake host. Production code passes neither."""
        if block_bytes <= 0 or read_bytes <= 0:
            raise ValueError("block_bytes and read_bytes must be positive")
        self._user_agent = user_agent
        self._timeout = timeout_seconds
        self._block_bytes = block_bytes
        self._read_bytes = min(read_bytes, block_bytes)
        self._interval = progress_interval_seconds
        self._monotonic = monotonic
        self._rewrite_url = rewrite_url
        self._allow_http_loopback = allow_http_loopback
        self._opener = urllib.request.build_opener(_SafeRedirectHandler(self._url_allowed))

    async def download(
        self,
        file: ModelFile,
        dest_part: Path,
        on_progress: ProgressCallback,
        should_stop: StopCheck,
    ) -> DownloadOutcome:
        return await asyncio.to_thread(self.download_blocking, file, dest_part, on_progress, should_stop)

    def download_blocking(
        self,
        file: ModelFile,
        dest_part: Path,
        on_progress: ProgressCallback,
        should_stop: StopCheck,
    ) -> DownloadOutcome:
        if not dest_part.name.endswith(PART_SUFFIX) or len(dest_part.name) <= len(PART_SUFFIX):
            raise ValueError("dest_part must end with .part")
        final = dest_part.with_name(dest_part.name[: -len(PART_SUFFIX)])
        dest_part.parent.mkdir(parents=True, exist_ok=True)
        progress = _Progress(on_progress, file.size_bytes, self._interval, self._monotonic)
        transient = False
        for url in file.urls:
            if should_stop():
                return DownloadOutcome(DownloadResult.STOPPED, _size(dest_part))
            attempt = self._from_url(url, file, dest_part, final, progress, should_stop)
            if attempt.outcome is not None:
                return attempt.outcome
            transient = transient or attempt.transient
        result = DownloadResult.NETWORK if transient else DownloadResult.FAILED
        return DownloadOutcome(result, _size(dest_part))

    # ---------------------------------------------------------------------------------------

    def _from_url(
        self,
        url: str,
        file: ModelFile,
        part: Path,
        final: Path,
        progress: _Progress,
        should_stop: StopCheck,
    ) -> _UrlAttempt:
        target = self._rewrite_url(url) if self._rewrite_url is not None else url
        host = urlsplit(url).hostname or "?"
        if not self._url_allowed(target):
            LOGGER.warning("Model download URL rejected for %s", host)
            return _UrlAttempt()
        restarted = False
        while True:
            offset = _size(part)
            if offset > file.size_bytes:
                _discard(part)
                offset = 0
            if offset == file.size_bytes:
                return _UrlAttempt(self._finalize(file, part, final, progress, url))
            meta = _read_meta(part)
            try:
                response = self._open(target, offset, meta.get("etag") if offset else None)
            except urllib.error.HTTPError as exc:
                exc.close()
                if exc.code == 416 and offset and not restarted:
                    _discard(part)
                    restarted = True
                    continue
                LOGGER.info("Model download from %s answered HTTP %s", host, exc.code)
                return _UrlAttempt(transient=exc.code >= 500 or exc.code == 429)
            except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
                LOGGER.info("Model download from %s could not connect (%s)", host, type(exc).__name__)
                return _UrlAttempt(transient=True)
            try:
                return _UrlAttempt(self._consume(response, url, file, part, final, offset, meta, progress, should_stop))
            except _Restart:
                if restarted:
                    LOGGER.info("Model download from %s keeps answering with a different file", host)
                    return _UrlAttempt(transient=True)
                _discard(part)
                restarted = True
                continue
            finally:
                response.close()

    def _open(self, url: str, offset: int, etag: str | None) -> Any:
        headers = {"User-Agent": self._user_agent, "Accept-Encoding": "identity", "Accept": "*/*"}
        if offset > 0:
            headers["Range"] = f"bytes={offset}-"
            if etag and not etag.startswith("W/"):
                headers["If-Range"] = etag
        request = urllib.request.Request(url, headers=headers, method="GET")
        return self._opener.open(request, timeout=self._timeout)

    def _consume(
        self,
        response: Any,
        url: str,
        file: ModelFile,
        part: Path,
        final: Path,
        offset: int,
        meta: dict[str, Any],
        progress: _Progress,
        should_stop: StopCheck,
    ) -> DownloadOutcome | None:
        status = int(getattr(response, "status", 200))
        etag = response.headers.get("ETag")
        start = 0
        if status == 206:
            start = _range_start(response.headers.get("Content-Range"), file.size_bytes)
            if start is None or start not in {offset, 0}:
                raise _Restart()
            if offset and meta.get("etag") and etag and etag != meta.get("etag"):
                raise _Restart()
        elif status != 200:
            return None
        # A `200` while resuming (range ignored or If-Range mismatch) starts the file again from zero.
        if start == 0:
            offset = 0
        digest = hashlib.sha256()
        mode = "r+b" if offset else "wb"
        try:
            handle: BinaryIO = part.open(mode)
        except OSError as exc:
            return self._write_failure(exc, part)
        with handle:
            if offset:
                _hash_prefix(handle, offset, digest)
                handle.seek(offset)
                handle.truncate()
            _write_meta(part, etag, file)
            done = offset
            in_block = 0
            progress.report(done, force=True)
            while True:
                want = min(self._read_bytes, self._block_bytes - in_block)
                try:
                    chunk = response.read(want)
                except (http.client.HTTPException, OSError) as exc:
                    _flush(handle)
                    LOGGER.info("Model download interrupted at %s bytes (%s)", done, type(exc).__name__)
                    progress.report(done, force=True)
                    return DownloadOutcome(DownloadResult.NETWORK, done, url)
                if not chunk:
                    break
                if done + len(chunk) > file.size_bytes:
                    # More bytes than pinned: this is not the file we asked for.
                    handle.close()
                    _discard(part)
                    return DownloadOutcome(DownloadResult.CHECKSUM, 0, url)
                try:
                    handle.write(chunk)
                except OSError as exc:
                    return self._write_failure(exc, part, done)
                digest.update(chunk)
                done += len(chunk)
                in_block += len(chunk)
                progress.report(done)
                if in_block >= self._block_bytes:
                    in_block = 0
                    _flush(handle)
                    if should_stop():
                        progress.report(done, force=True)
                        return DownloadOutcome(DownloadResult.STOPPED, done, url)
            if done < file.size_bytes:
                _flush(handle)
                LOGGER.info("Model download ended early at %s bytes", done)
                progress.report(done, force=True)
                return DownloadOutcome(DownloadResult.NETWORK, done, url)
            try:
                handle.flush()
                os.fsync(handle.fileno())
            except OSError as exc:
                return self._write_failure(exc, part, done)
        return self._complete(digest.hexdigest(), file, part, final, progress, url)

    def _finalize(
        self, file: ModelFile, part: Path, final: Path, progress: _Progress, url: str
    ) -> DownloadOutcome:
        """The `.part` already holds every byte (a stop right at the end, or a kill before the rename)."""
        digest = hashlib.sha256()
        with part.open("rb") as handle:
            _hash_prefix(handle, file.size_bytes, digest)
        return self._complete(digest.hexdigest(), file, part, final, progress, url)

    def _complete(
        self, actual: str, file: ModelFile, part: Path, final: Path, progress: _Progress, url: str
    ) -> DownloadOutcome:
        if actual != file.sha256:
            LOGGER.warning("Model file %s failed its sha256 check; the partial file was deleted", file.name)
            _discard(part)
            return DownloadOutcome(DownloadResult.CHECKSUM, 0, url)
        os.replace(part, final)
        _fsync_dir(final.parent)
        _unlink(_meta_path(part))
        progress.report(file.size_bytes, force=True)
        return DownloadOutcome(DownloadResult.COMPLETED, file.size_bytes, url)

    def _write_failure(self, exc: OSError, part: Path, done: int | None = None) -> DownloadOutcome:
        bytes_done = _size(part) if done is None else done
        if exc.errno in _NO_SPACE_ERRNOS:
            LOGGER.warning("Model download stopped: the disk is full")
            return DownloadOutcome(DownloadResult.NO_SPACE, bytes_done)
        LOGGER.warning("Model download could not write its file (%s)", type(exc).__name__)
        return DownloadOutcome(DownloadResult.FAILED, bytes_done)

    def _url_allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme == "https" and parts.hostname:
            return True
        return parts.scheme == "http" and self._allow_http_loopback and _is_loopback(parts.hostname)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follows redirects (Hugging Face `resolve` → its CDN) only to allowed URLs; Range headers carry over."""

    def __init__(self, allowed: Callable[[str], bool]) -> None:
        super().__init__()
        self._allowed = allowed

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        if not self._allowed(newurl):
            raise urllib.error.HTTPError(newurl, 403, "Redirect to a disallowed URL", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _range_start(header: str | None, size: int) -> int | None:
    match = _CONTENT_RANGE_RE.match(header or "")
    if match is None:
        return None
    start, end, total = int(match.group(1)), int(match.group(2)), match.group(3)
    if end < start or (total != "*" and int(total) != size) or end >= size:
        return None
    return start


def _hash_prefix(handle: BinaryIO, length: int, digest: Any) -> None:
    handle.seek(0)
    remaining = length
    while remaining > 0:
        block = handle.read(min(BLOCK_BYTES, remaining))
        if not block:
            break
        digest.update(block)
        remaining -= len(block)


def _meta_path(part: Path) -> Path:
    return part.with_name(part.name + META_SUFFIX)


def _read_meta(part: Path) -> dict[str, Any]:
    try:
        data = json.loads(_meta_path(part).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_meta(part: Path, etag: str | None, file: ModelFile) -> None:
    payload = {"etag": etag, "sha256": file.sha256, "size_bytes": file.size_bytes}
    try:
        _meta_path(part).write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    except OSError:
        pass  # resume metadata is an optimisation; without it a resume just skips `If-Range`


def _flush(handle: BinaryIO) -> None:
    try:
        handle.flush()
    except OSError:
        pass


def _fsync_dir(directory: Path) -> None:
    if os.name != "posix":
        return
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _discard(part: Path) -> None:
    _unlink(part)
    _unlink(_meta_path(part))
