from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bento.infrastructure import process_secrets

TOKEN_ENV = "BENTO_DESKTOP_API_TOKEN"
ORIGIN_ENV = "BENTO_DESKTOP_ORIGIN"


@dataclass(frozen=True, slots=True)
class DesktopSecurityConfig:
    token: str
    origin: str

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> DesktopSecurityConfig:
        """The per-launch token comes from the process-private holder (the sidecar launcher moves it
        out of the environment), falling back to `environ` for embedders and tests."""
        token = process_secrets.get(TOKEN_ENV) or environ.get(TOKEN_ENV, "")
        origin = environ.get(ORIGIN_ENV, "")
        if len(token) < 32:
            raise RuntimeError(f"{TOKEN_ENV} must contain at least 32 characters in desktop mode")
        if not _valid_origin(origin):
            raise RuntimeError(f"{ORIGIN_ENV} must contain one exact origin in desktop mode")
        return cls(token=token, origin=origin)


class DesktopSecurityMiddleware:
    """Authenticate every desktop API request without retaining secrets in app state."""

    def __init__(self, app: ASGIApp, *, config: DesktopSecurityConfig) -> None:
        self._app = app
        self._token = config.token.encode("utf-8")
        self._origin = config.origin.encode("ascii")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = tuple((key.lower(), value) for key, value in scope.get("headers", ()))
        origin = _unique_header(headers, b"origin")
        if origin is None or not hmac.compare_digest(origin, self._origin):
            await _json_error(send, status=403, code="desktop_origin_rejected")
            return

        # Browser CORS preflight requests cannot carry the requested bearer token.
        # Exact-origin validation still prevents an untrusted renderer from probing it.
        if scope.get("method") == "OPTIONS":
            await self._app(scope, receive, send)
            return

        authorization = _unique_header(headers, b"authorization") or b""
        scheme, separator, credential = authorization.partition(b" ")
        authorized = (
            separator == b" "
            and scheme.lower() == b"bearer"
            and bool(credential)
            and hmac.compare_digest(credential, self._token)
        )
        if not authorized:
            await _json_error(send, status=401, code="desktop_auth_required", authenticate=True)
            return
        await self._app(scope, receive, send)


def _unique_header(headers: tuple[tuple[bytes, bytes], ...], name: bytes) -> bytes | None:
    values = [value for key, value in headers if key == name]
    return values[0] if len(values) == 1 else None


def _valid_origin(value: str) -> bool:
    if not value or not value.isascii():
        return False
    parsed = urlsplit(value)
    return bool(
        parsed.scheme
        and parsed.netloc
        and not parsed.username
        and not parsed.password
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
        and value == value.rstrip("/")
    )


async def _json_error(
    send: Send,
    *,
    status: int,
    code: str,
    authenticate: bool = False,
) -> None:
    body = f'{{"detail":{{"code":"{code}","message":"Request rejected"}}}}'.encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    if authenticate:
        headers.append((b"www-authenticate", b"Bearer"))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
