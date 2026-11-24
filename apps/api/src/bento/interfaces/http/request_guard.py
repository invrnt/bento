"""Headless-mode protection of the local API against DNS rebinding and blind cross-site requests.

- **Host**: only loopback names (`127.0.0.1`, `localhost`, `[::1]`, any port) plus the exact host names
  listed in `BENTO_ALLOWED_HOSTS` (comma-separated). A DNS-rebound page keeps its own host name.
- **CSRF**: every request other than GET/HEAD/OPTIONS must carry `X-Bento-Client: web`. Browsers only
  let a page add that header through a CORS preflight, which the API answers solely for its web origins,
  so forms, `sendBeacon`, and `no-cors` fetches from other sites are refused.
- **API token** (optional, `BENTO_API_TOKEN`): when set, every HTTP and WebSocket request must carry
  `Authorization: Bearer <token>`. A valid bearer token replaces the CSRF header, since browsers cannot attach
  one cross-site without a preflight.

Desktop mode does not use this guard: `DesktopSecurityMiddleware` already requires its exact origin and
bearer token.
"""

from __future__ import annotations

import hmac
import json
import uuid
from collections.abc import Iterable, Mapping

from starlette.types import ASGIApp, Receive, Scope, Send

from bento.infrastructure import process_secrets

ALLOWED_HOSTS_ENV = "BENTO_ALLOWED_HOSTS"
API_TOKEN_ENV = "BENTO_API_TOKEN"
MIN_TOKEN_LENGTH = 32
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


def api_token_from_environ(environ: Mapping[str, str]) -> str | None:
    """The headless API token: the process-private holder first (the sidecar launcher moves it out of the
    environment), then `environ` (plain `uvicorn` runs and tests). Too short a token fails closed."""
    token = process_secrets.get(API_TOKEN_ENV) or environ.get(API_TOKEN_ENV, "")
    if not token.strip():
        return None
    if len(token) < MIN_TOKEN_LENGTH:
        raise RuntimeError(f"{API_TOKEN_ENV} must contain at least {MIN_TOKEN_LENGTH} characters")
    return token


def bearer_credential(headers: Iterable[tuple[bytes, bytes]]) -> bytes | None:
    """The credential of the single `Authorization: Bearer <credential>` header (lowercased header names)."""
    values = [value for key, value in headers if key == b"authorization"]
    if len(values) != 1:
        return None
    scheme, separator, credential = values[0].partition(b" ")
    if separator != b" " or scheme.lower() != b"bearer" or not credential:
        return None
    return credential


class LocalRequestGuard:
    def __init__(self, app: ASGIApp, *, allowed_hosts: Iterable[str], api_token: str | None = None) -> None:
        self._app = app
        self._hosts = frozenset(allowed_hosts)
        self._token = api_token.encode("utf-8") if api_token else None

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
        if self._token is not None:
            credential = bearer_credential(headers)
            if credential is None or not hmac.compare_digest(credential, self._token):
                await _reject(
                    scope,
                    send,
                    headers,
                    status=401,
                    code="api_token_required",
                    message="A valid API token is required",
                    authenticate=True,
                )
                return
            # A bearer token cannot be attached cross-site without a preflight: it replaces the CSRF header.
            await self._app(scope, receive, send)
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
    scope: Scope,
    send: Send,
    headers: list[tuple[bytes, bytes]],
    *,
    status: int,
    code: str,
    message: str,
    authenticate: bool = False,
) -> None:
    if scope["type"] == "websocket":
        # Closing before accepting makes the server answer the handshake with 403.
        await send({"type": "websocket.close", "code": 1008})
        return
    request_id = next((value.decode("latin-1") for key, value in headers if key == b"x-request-id"), None)
    body = json.dumps(
        {"error": {"code": code, "message": message, "details": {}, "request_id": request_id or uuid.uuid4().hex}}
    ).encode("utf-8")
    response_headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii"))]
    if authenticate:
        response_headers.append((b"www-authenticate", b"Bearer"))
    await send({"type": "http.response.start", "status": status, "headers": response_headers})
    await send({"type": "http.response.body", "body": body})
