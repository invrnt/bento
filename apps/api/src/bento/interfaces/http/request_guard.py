"""Headless-mode protection of the local API against DNS rebinding and blind cross-site requests.

- **Host**: only loopback names (`127.0.0.1`, `localhost`, `[::1]`, any port) plus the exact host names
  listed in `BENTO_ALLOWED_HOSTS` (comma-separated). A DNS-rebound page keeps its own host name.
- **CSRF**: every request other than GET/HEAD/OPTIONS must carry `X-Bento-Client: web`. Browsers only
  let a page add that header through a CORS preflight, which the API answers solely for its web origins,
  so forms, `sendBeacon`, and `no-cors` fetches from other sites are refused.

Desktop mode does not use this guard: `DesktopSecurityMiddleware` already requires its exact origin and
bearer token.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping

from starlette.types import ASGIApp, Receive, Scope, Send

ALLOWED_HOSTS_ENV = "BENTO_ALLOWED_HOSTS"
CLIENT_HEADER = b"x-bento-client"
CLIENT_HEADER_VALUE = b"web"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def host_name(value: str) -> str | None:
    """The lowercased host of `name`, `name:port`, `[v6]`, or `[v6]:port`; None when malformed."""
    text = value.strip().lower()
    if text.startswith("["):
        end = text.find("]")
        if end < 0:
            return None
        host, rest = text[: end + 1], text[end + 1 :]
    else:
        host, separator, port = text.partition(":")
        rest = separator + port
    if rest and not (rest.startswith(":") and rest[1:].isascii() and rest[1:].isdigit()):
        return None
    return host or None


def allowed_hosts_from_environ(environ: Mapping[str, str]) -> frozenset[str]:
    extra = (host_name(item) for item in environ.get(ALLOWED_HOSTS_ENV, "").split(","))
    return LOOPBACK_HOSTS | {host for host in extra if host}


class LocalRequestGuard:
    def __init__(self, app: ASGIApp, *, allowed_hosts: Iterable[str]) -> None:
        self._app = app
        self._hosts = frozenset(allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind not in {"http", "websocket"}:
            await self._app(scope, receive, send)
            return
        headers = [(key.lower(), value) for key, value in scope.get("headers", ())]
        hosts = [value for key, value in headers if key == b"host"]
        host = host_name(hosts[0].decode("latin-1")) if len(hosts) == 1 else None
        if host is None or host not in self._hosts:
            await _reject(scope, send, headers, status=400, code="host_not_allowed", message="Host is not allowed")
            return
        if kind == "http" and str(scope.get("method", "GET")).upper() not in SAFE_METHODS:
            values = [value for key, value in headers if key == CLIENT_HEADER]
            if values != [CLIENT_HEADER_VALUE]:
                await _reject(
                    scope, send, headers, status=403, code="csrf_header_missing", message="Missing X-Bento-Client header"
                )
                return
        await self._app(scope, receive, send)


async def _reject(
    scope: Scope, send: Send, headers: list[tuple[bytes, bytes]], *, status: int, code: str, message: str
) -> None:
    if scope["type"] == "websocket":
        # Closing before accepting makes the server answer the handshake with 403.
        await send({"type": "websocket.close", "code": 1008})
        return
    request_id = next((value.decode("latin-1") for key, value in headers if key == b"x-request-id"), None)
    body = json.dumps(
        {"error": {"code": code, "message": message, "details": {}, "request_id": request_id or uuid.uuid4().hex}}
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii"))],
        }
    )
    await send({"type": "http.response.body", "body": body})
