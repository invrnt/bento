"""A tiny blocking HTTP/1.1 JSON client for the local embedding server.

Speaks to `http://127.0.0.1:<port>` and to `http+unix://<socket path>` (Linux/macOS). Callers run it in a
thread. Errors carry the status and at most the server's short error message, never the request body.
"""

from __future__ import annotations

import http.client
import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlsplit

UNIX_SCHEME = "http+unix://"
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_MAX_ERROR_MESSAGE = 200


class LocalHttpError(RuntimeError):
    """The server could not be reached (`status is None`) or answered with an unusable body."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LocalHttpError("The server answered with invalid JSON", status=self.status) from exc

    def error_message(self) -> str:
        """The server's own short error message (llama-server: `{"error": {"message": ...}}`)."""
        try:
            payload = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ""
        error = payload.get("error") if isinstance(payload, dict) else None
        message = error.get("message") if isinstance(error, dict) else error
        return str(message)[:_MAX_ERROR_MESSAGE] if message else ""


def unix_base_url(socket_path: str) -> str:
    return f"{UNIX_SCHEME}{socket_path}"


def is_unix_url(base_url: str) -> bool:
    return base_url.startswith(UNIX_SCHEME)


def request(
    base_url: str,
    method: str,
    path: str,
    *,
    body: Any | None = None,
    api_key: str | None = None,
    timeout: float = 30.0,
) -> HttpResponse:
    """Send one request; returns any HTTP status. Raises `LocalHttpError` only when unreachable."""
    connection, prefix = _connection(base_url, timeout)
    headers = {"Accept": "application/json", "Connection": "close"}
    payload: bytes | None = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        connection.request(method, f"{prefix}{path}", body=payload, headers=headers)
        response = connection.getresponse()
        data = response.read(_MAX_RESPONSE_BYTES + 1)
        status = response.status
    except (OSError, http.client.HTTPException) as exc:
        raise LocalHttpError(f"The embedding server is unreachable ({exc.__class__.__name__})") from exc
    finally:
        connection.close()
    if len(data) > _MAX_RESPONSE_BYTES:
        raise LocalHttpError("The embedding server response is too large", status=status)
    return HttpResponse(status=status, body=data)


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self._socket_path)
        except OSError:
            sock.close()
            raise
        self.sock = sock


def _connection(base_url: str, timeout: float) -> tuple[http.client.HTTPConnection, str]:
    if is_unix_url(base_url):
        socket_path = unquote(base_url[len(UNIX_SCHEME) :])
        if not socket_path:
            raise LocalHttpError("Malformed unix socket URL")
        return _UnixHTTPConnection(socket_path, timeout), ""
    parts = urlsplit(base_url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise LocalHttpError("Unsupported embedding server URL")
    prefix = parts.path.rstrip("/")
    if parts.scheme == "https":
        return http.client.HTTPSConnection(parts.hostname, parts.port, timeout=timeout), prefix
    return http.client.HTTPConnection(parts.hostname, parts.port, timeout=timeout), prefix
