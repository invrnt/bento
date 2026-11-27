"""A local fake of the model download hosts (Hugging Face pinned URL + Bento mirror) for Stage 24 tests.

`FakeModelHost` serves a 3 MB synthetic blob over plain HTTP on 127.0.0.1 with `Range`/`206`/`ETag`/
`If-Range` support, and injects the failures the downloader must survive:

- `drop_at`: close the connection once the body reaches this absolute byte offset (one-shot by default;
  with `drop_once=False` every request at or past it is cut too);
  `next_drops` lists the offsets that arm `drop_at` again after each one-shot drop (a flaky link);
- `reset`: drops are TCP resets (`SO_LINGER` 0) instead of an orderly shutdown;
- `stall_at`/`stall_seconds`: once the body reaches this offset, send nothing for that long (one-shot), with the
  connection left open;
- `short_body_at`: one-shot, end the response cleanly (FIN) at this offset although `Content-Length` promised more;
- `ignore_range`: answer `200` with the whole body when a range was asked;
- `missing`: paths that answer `404` (the primary URL → mirror fallback);
- `trickle_delay`: sleep between 64 KiB chunks (slow link, for pause/cancel mid-download);
- `wrong_body`: serve bytes that do not match the pinned sha256 (same length);
- `etag`: change it between requests to simulate a replaced file.

Pinned URLs stay `https://<host>/<path>`; `rewrite()` maps them onto this server
(`http://127.0.0.1:<port>/<host>/<path>`), which the downloader accepts only with `allow_http_loopback`.
Nothing here touches the network beyond loopback.
"""

from __future__ import annotations

import hashlib
import random
import re
import socket
import struct
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

BLOB_SIZE = 3 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
PRIMARY_URL = "https://primary.bento.example/models/resolve/abc1234/tiny-model.gguf"
MIRROR_URL = "https://mirror.bento.example/releases/download/models-tiny/tiny-model.gguf"

_RANGE_RE = re.compile(r"^bytes=(\d+)-(\d*)$")


def synthetic_blob(size: int = BLOB_SIZE, seed: int = 24) -> bytes:
    return random.Random(seed).randbytes(size)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def host_path(url: str) -> str:
    """The path a pinned `https` URL is served at on the fake host."""
    parts = urlsplit(url)
    return f"/{parts.hostname}{parts.path}"


@dataclass
class RecordedRequest:
    path: str
    range: str | None
    if_range: str | None
    user_agent: str | None
    authorization: str | None
    cookie: str | None
    status: int = 0


@dataclass
class HostBehavior:
    etag: str = '"tiny-v1"'
    drop_at: int | None = None
    drop_once: bool = True
    next_drops: list[int] = field(default_factory=list)
    reset: bool = False
    stall_at: int | None = None
    stall_seconds: float = 0.0
    short_body_at: int | None = None
    ignore_range: bool = False
    missing: set[str] = field(default_factory=set)
    trickle_delay: float = 0.0
    wrong_body: bool = False


class FakeModelHost:
    def __init__(self, blob: bytes | None = None) -> None:
        self.blob = synthetic_blob() if blob is None else blob
        self.behavior = HostBehavior()
        self.requests: list[RecordedRequest] = []
        self._files: dict[str, bytes] = {}
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="fake-model-host", daemon=True)

    # -- lifecycle -------------------------------------------------------------------------

    def start(self) -> FakeModelHost:
        self.serve(PRIMARY_URL, self.blob)
        self.serve(MIRROR_URL, self.blob)
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def serve(self, url: str, data: bytes) -> None:
        with self._lock:
            self._files[host_path(url)] = data

    def rewrite(self, url: str) -> str:
        return self.base_url + host_path(url)

    def fail_primary(self) -> None:
        self.behavior.missing.add(host_path(PRIMARY_URL))

    def requests_for(self, url: str) -> list[RecordedRequest]:
        path = host_path(url)
        with self._lock:
            return [item for item in self.requests if item.path == path]

    # -- request handling ------------------------------------------------------------------

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        host = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
                return None

            def do_GET(self) -> None:  # noqa: N802 - stdlib name
                host._handle(self)

        return Handler

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        path = urlsplit(handler.path).path
        record = RecordedRequest(
            path=path,
            range=handler.headers.get("Range"),
            if_range=handler.headers.get("If-Range"),
            user_agent=handler.headers.get("User-Agent"),
            authorization=handler.headers.get("Authorization"),
            cookie=handler.headers.get("Cookie"),
        )
        with self._lock:
            self.requests.append(record)
            behavior = self.behavior
            data = self._files.get(path)
        if data is None or path in behavior.missing:
            record.status = 404
            _send_empty(handler, 404)
            return
        if behavior.wrong_body:
            data = bytes(byte ^ 0x5A for byte in data)
        size = len(data)
        start = 0
        status = 200
        match = _RANGE_RE.match(record.range or "")
        range_applies = match is not None and not behavior.ignore_range
        if range_applies and record.if_range is not None and record.if_range != behavior.etag:
            range_applies = False  # If-Range mismatch: the whole (new) file
        if range_applies and match is not None:
            start = int(match.group(1))
            if start >= size:
                record.status = 416
                _send_empty(handler, 416, {"Content-Range": f"bytes */{size}"})
                return
            status = 206
        record.status = status
        handler.send_response(status)
        handler.send_header("Content-Type", "application/octet-stream")
        handler.send_header("Content-Length", str(size - start))
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("ETag", behavior.etag)
        if status == 206:
            handler.send_header("Content-Range", f"bytes {start}-{size - 1}/{size}")
        handler.end_headers()
        offset = start
        try:
            while offset < size:
                end = min(size, offset + CHUNK_BYTES)
                drop_at = behavior.drop_at
                # A repeating drop (`drop_once=False`) also cuts a request that starts at or past it: the link is
                # down from that byte on.
                if drop_at is not None and (offset < drop_at <= end or (not behavior.drop_once and offset >= drop_at)):
                    handler.wfile.write(data[offset:drop_at])
                    handler.wfile.flush()
                    if behavior.drop_once:
                        behavior.drop_at = behavior.next_drops.pop(0) if behavior.next_drops else None
                    _drop(handler, reset=behavior.reset)
                    return
                short_at = behavior.short_body_at
                if short_at is not None and offset < short_at <= end:
                    behavior.short_body_at = None
                    handler.wfile.write(data[offset:short_at])
                    handler.wfile.flush()
                    _drop(handler)
                    return
                stall_at = behavior.stall_at
                if stall_at is not None and offset < stall_at <= end:
                    behavior.stall_at = None
                    handler.wfile.write(data[offset:stall_at])
                    handler.wfile.flush()
                    time.sleep(behavior.stall_seconds)  # the connection stays open, silent
                    handler.close_connection = True
                    return
                handler.wfile.write(data[offset:end])
                offset = end
                if behavior.trickle_delay:
                    handler.wfile.flush()
                    time.sleep(behavior.trickle_delay)
            handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            handler.close_connection = True


def _send_empty(handler: BaseHTTPRequestHandler, status: int, headers: dict[str, str] | None = None) -> None:
    handler.send_response(status)
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def _drop(handler: BaseHTTPRequestHandler, *, reset: bool = False) -> None:
    handler.close_connection = True
    if reset:
        try:
            handler.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            handler.connection.close()
        except OSError:
            pass
        return
    try:
        handler.connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


@contextmanager
def running_model_host(blob: bytes | None = None) -> Iterator[FakeModelHost]:
    host = FakeModelHost(blob).start()
    try:
        yield host
    finally:
        host.close()
