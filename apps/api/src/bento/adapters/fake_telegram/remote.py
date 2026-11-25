"""The fake Telegram cloud over HTTP (debug only, `api/android-endpoints.md` §9).

`bento-sidecar fake-telegram-serve --dir <dir> --port <p>` serves one fake-cloud directory; processes configured
with `BENTO_FAKE_TELEGRAM_URL` use `RemoteFakeTelegramCloud` instead of opening the directory, so an emulator
(`http://10.0.2.2:<p>`) and host processes act as devices of one account. The protocol is a small JSON RPC over
`FakeTelegramCloud`'s public methods plus a document download; values use a closed type registry (no pickle).
Stdlib only on both sides (no extra dependency on Android). Never enabled in production builds.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from bento.adapters.fake_telegram.cloud import (
    FAKE_USER,
    DocumentUpload,
    FakeAuthorization,
    FakeChat,
    FakeLoginToken,
    FakeMedia,
    FakeMessage,
    FakeTelegramCloud,
)
from bento.adapters.fake_telegram.options import FakeTelegramOptions
from bento.domain import errors as domain_errors
from bento.domain.account import TelegramAccount
from bento.domain.errors import DomainError, StorageUnavailableError
from bento.domain.storage import StorageBackend
from bento.domain.telegram import TelegramChatKind, TelegramMediaKind

LOGGER = logging.getLogger("bento.fake_telegram.remote")

_DATACLASSES: dict[str, type] = {
    cls.__name__: cls
    for cls in (FakeMedia, FakeMessage, FakeChat, FakeAuthorization, FakeLoginToken, DocumentUpload, TelegramAccount, FakeTelegramOptions)
}
_ENUMS: dict[str, type[Enum]] = {cls.__name__: cls for cls in (TelegramChatKind, TelegramMediaKind)}
# Every method a remote client may call (all of `FakeTelegramCloud`'s public data operations).
REMOTE_METHODS = frozenset(
    {
        "authorizations", "authorization", "create_authorization", "remove_authorization", "touch_authorization",
        "issue_login_token", "login_token", "approve_login_token", "approve_pending_logins", "claim_login_token",
        "discard_login_token", "dialogs", "chat", "read_chat", "message", "last_message_id", "create_channel",
        "update_chat", "add_to_folder", "folders", "post_message", "edit_message", "delete_messages", "set_reaction",
        "inject_fault", "clear_fault", "active_fault", "chat_signature", "ensure_ready",
    }
)
LEASE_SECONDS = 30.0
MAX_REQUEST_BYTES = 2 * 1024 * 1024 * 1024


# codec ----------------------------------------------------------------------------------------------------


def encode(value: Any) -> Any:
    if isinstance(value, Enum):  # before `str`: the domain enums are StrEnums
        return {"__enum": type(value).__name__, "v": value.value}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return {"__bytes": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, datetime):
        return {"__dt": value.isoformat()}
    if isinstance(value, Path):
        return {"__bytes": base64.b64encode(value.read_bytes()).decode("ascii")}  # uploads travel as bytes
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        name = type(value).__name__
        if name not in _DATACLASSES:
            raise TypeError(f"Unsupported value {name}")
        return {"__dc": name, "f": {field.name: encode(getattr(value, field.name)) for field in dataclasses.fields(value)}}
    if isinstance(value, dict):
        return {"__dict": [[encode(key), encode(item)] for key, item in value.items()]}
    if isinstance(value, (list, tuple, set, frozenset)) or type(value).__name__ in {"dict_values", "dict_keys", "generator"}:
        return {"__tuple": [encode(item) for item in value]}
    raise TypeError(f"Unsupported value {type(value).__name__}")


def decode(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if "__enum" in value:
        return _ENUMS[value["__enum"]](value["v"])
    if "__bytes" in value:
        return base64.b64decode(value["__bytes"])
    if "__dt" in value:
        return datetime.fromisoformat(value["__dt"])
    if "__dc" in value:
        cls = _DATACLASSES[value["__dc"]]
        return cls(**{key: decode(item) for key, item in value["f"].items()})
    if "__dict" in value:
        return {decode(key): decode(item) for key, item in value["__dict"]}
    if "__tuple" in value:
        return tuple(decode(item) for item in value["__tuple"])
    raise ValueError("Malformed value")


def _encode_error(exc: DomainError) -> dict[str, Any]:
    return {"class": type(exc).__name__, "code": exc.code, "message": exc.message, "details": exc.details}


def _decode_error(payload: dict[str, Any]) -> DomainError:
    cls = getattr(domain_errors, str(payload.get("class")), None)
    if not (isinstance(cls, type) and issubclass(cls, DomainError)):
        cls = DomainError
    error = cls.__new__(cls)
    DomainError.__init__(error, str(payload["code"]), str(payload["message"]), dict(payload.get("details") or {}))
    if "retry_after_seconds" in error.details:
        error.retry_after_seconds = int(error.details["retry_after_seconds"])  # type: ignore[attr-defined]
    return error


# server ---------------------------------------------------------------------------------------------------


class FakeTelegramServer:
    """Serves one directory. Calls run under the directory's file lock, so local processes can share it too;
    a client lease (`locked()` on the remote side) serializes multi-call sections across remote clients."""

    def __init__(self, directory: Path | str) -> None:
        self.cloud = FakeTelegramCloud(directory)
        self._condition = threading.Condition()
        self._lease: tuple[str, float] | None = None

    def call(self, method: str, args: list[Any], kwargs: dict[str, Any], lease: str | None) -> Any:
        if method not in REMOTE_METHODS:
            raise PermissionError(method)
        self._enter(lease)
        try:
            with self.cloud.locked():
                return getattr(self.cloud, method)(*args, **kwargs)
        finally:
            self._exit(lease)

    def acquire(self) -> str:
        token = uuid.uuid4().hex
        with self._condition:
            while self._lease is not None and self._lease[1] > time.monotonic():
                self._condition.wait(timeout=0.5)
            self._lease = (token, time.monotonic() + LEASE_SECONDS)
        return token

    def release(self, token: str) -> None:
        with self._condition:
            if self._lease is not None and self._lease[0] == token:
                self._lease = None
                self._condition.notify_all()

    def document(self, chat_id: int, message_id: int) -> Path:
        with self.cloud.locked():
            return self.cloud.document_path(chat_id, message_id)

    def _enter(self, lease: str | None) -> None:
        with self._condition:
            while self._lease is not None and self._lease[0] != lease and self._lease[1] > time.monotonic():
                self._condition.wait(timeout=0.5)
            if self._lease is not None and self._lease[0] == lease:
                self._lease = (self._lease[0], time.monotonic() + LEASE_SECONDS)

    def _exit(self, lease: str | None) -> None:
        return None


def make_http_server(directory: Path | str, *, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    backend = FakeTelegramServer(directory)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - BaseHTTPRequestHandler API
            LOGGER.debug("fake-telegram %s", format % args)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0 or length > MAX_REQUEST_BYTES:
                self._send(413, {"error": {"class": "ValidationFailedError", "code": "too_large", "message": "too large"}})
                return
            try:
                request = json.loads(self.rfile.read(length) or b"{}")
                path = urlparse(self.path).path
                if path == "/lease":
                    self._send(200, {"lease": backend.acquire()})
                elif path == "/release":
                    backend.release(str(request.get("lease")))
                    self._send(200, {"ok": True})
                elif path == "/call":
                    result = backend.call(
                        str(request["method"]),
                        [decode(item) for item in request.get("args", [])],
                        {key: decode(item) for key, item in (request.get("kwargs") or {}).items()},
                        request.get("lease"),
                    )
                    self._send(200, {"result": encode(result)})
                else:
                    self._send(404, {"error": {"class": "DomainError", "code": "not_found", "message": "not found"}})
            except DomainError as exc:
                self._send(200, {"error": _encode_error(exc)})
            except PermissionError:
                self._send(403, {"error": {"class": "DomainError", "code": "method_not_allowed", "message": "forbidden"}})
            except Exception as exc:  # noqa: BLE001 - debug server: report, keep serving
                LOGGER.exception("fake-telegram call failed")
                self._send(500, {"error": {"class": "DomainError", "code": "fake_server_error", "message": type(exc).__name__}})

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send(200, {"ok": True})
                return
            if parsed.path != "/document":
                self._send(404, {"error": {"class": "DomainError", "code": "not_found", "message": "not found"}})
                return
            query = parse_qs(parsed.query)
            try:
                path = backend.document(int(query["chat_id"][0]), int(query["message_id"][0]))
            except DomainError as exc:
                self._send(200, {"error": _encode_error(exc)})
                return
            size = path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    self.wfile.write(chunk)

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


# client ---------------------------------------------------------------------------------------------------


class RemoteFakeTelegramCloud:
    """Drop-in for `FakeTelegramCloud` backed by `fake-telegram-serve`. Documents are downloaded into
    `cache_dir` on demand (`document_path` returns a local file, as the directory-backed cloud does)."""

    def __init__(self, url: str, cache_dir: Path | str, *, clock: Callable[[], float] = time.time, timeout: float = 600.0) -> None:
        self.url = url.rstrip("/")
        self.root = Path(cache_dir)
        self._clock = clock
        self._timeout = timeout
        self._local = threading.local()

    def now(self) -> datetime:
        return datetime.fromtimestamp(self._clock(), UTC)

    @property
    def user(self) -> TelegramAccount:
        return FAKE_USER  # the simulated account is a constant of the fake cloud

    @contextmanager
    def locked(self) -> Iterator[None]:
        if getattr(self._local, "lease", None) is not None:
            yield
            return
        lease = self._post("/lease", {})["lease"]
        self._local.lease = lease
        try:
            yield
        finally:
            self._local.lease = None
            self._post("/release", {"lease": lease})

    def document_path(self, chat_id: int, message_id: int) -> Path:
        target = self.root / "documents" / str(chat_id) / str(message_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(f".{target.name}.{uuid.uuid4().hex}.partial")
        url = f"{self.url}/document?chat_id={int(chat_id)}&message_id={int(message_id)}"
        try:
            with urllib.request.urlopen(url, timeout=self._timeout) as response:
                if response.headers.get("Content-Type", "").startswith("application/json"):
                    payload = json.loads(response.read())
                    raise _decode_error(payload["error"])
                with staged.open("wb") as handle:
                    while chunk := response.read(1024 * 1024):
                        handle.write(chunk)
            os.replace(staged, target)
        except urllib.error.URLError:
            raise StorageUnavailableError(StorageBackend.TELEGRAM.value) from None
        finally:
            staged.unlink(missing_ok=True)
        return target

    def chat_log_path(self, chat_id: int) -> Path:
        raise NotImplementedError("Remote fake clouds expose chat_signature() instead of chat files")

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name not in REMOTE_METHODS:
            raise AttributeError(name)

        def remote(*args: Any, **kwargs: Any) -> Any:
            return self._call(name, args, kwargs)

        return remote

    def _call(self, method: str, args: Iterable[Any], kwargs: dict[str, Any]) -> Any:
        payload = {
            "method": method,
            "args": [encode(item) for item in args],
            "kwargs": {key: encode(item) for key, item in kwargs.items()},
            "lease": getattr(self._local, "lease", None),
        }
        return decode(self._post("/call", payload).get("result"))

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{self.url}{path}", data=body, method="POST", headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            result = json.loads(exc.read() or b"{}")
        except urllib.error.URLError:
            raise StorageUnavailableError(StorageBackend.TELEGRAM.value) from None
        if "error" in result:
            raise _decode_error(result["error"])
        return result


def serve(directory: Path | str, *, host: str = "127.0.0.1", port: int = 0, on_ready: Callable[[int], None] | None = None) -> None:
    server = make_http_server(directory, host=host, port=port)
    if on_ready is not None:
        on_ready(int(server.server_address[1]))
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
