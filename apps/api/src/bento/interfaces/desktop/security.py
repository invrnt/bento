from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bento.infrastructure import process_secrets
from bento.interfaces.http.request_guard import MIN_TOKEN_LENGTH, bearer_credential

TOKEN_ENV = "BENTO_DESKTOP_API_TOKEN"
CLI_TOKEN_ENV = "BENTO_DESKTOP_CLI_TOKEN"
ORIGIN_ENV = "BENTO_DESKTOP_ORIGIN"


@dataclass(frozen=True, slots=True)
class DesktopSecurityConfig:
    token: str
    origin: str
    cli_token: str | None = None

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> DesktopSecurityConfig:
        """The per-launch token comes from the process-private holder (the sidecar launcher moves it
        out of the environment), falling back to `environ` for embedders and tests."""
        token = process_secrets.get(TOKEN_ENV) or environ.get(TOKEN_ENV, "")
        cli_token = process_secrets.get(CLI_TOKEN_ENV) or environ.get(CLI_TOKEN_ENV, "")
        origin = environ.get(ORIGIN_ENV, "")
        if len(token) < MIN_TOKEN_LENGTH:
            raise RuntimeError(f"{TOKEN_ENV} must contain at least {MIN_TOKEN_LENGTH} characters in desktop mode")
        if cli_token.strip() and len(cli_token) < MIN_TOKEN_LENGTH:
            raise RuntimeError(f"{CLI_TOKEN_ENV} must contain at least {MIN_TOKEN_LENGTH} characters")
        if not _valid_origin(origin):
            raise RuntimeError(f"{ORIGIN_ENV} must contain one exact origin in desktop mode")
        return cls(token=token, origin=origin, cli_token=cli_token if cli_token.strip() else None)


class DesktopSecurityMiddleware:
    """Authenticate every desktop API request without retaining secrets in app state.

    Accepted: the exact renderer `Origin` with the desktop token, or (when configured) **no** `Origin` header
    with the CLI token. Browsers always send `Origin` on cross-origin and non-GET requests, so a page cannot
    use the CLI path; an `Origin` together with the CLI token is rejected outright.
    """

    def __init__(self, app: ASGIApp, *, config: DesktopSecurityConfig) -> None:
        self._app = app
        self._token = config.token.encode("utf-8")
        self._cli_token = config.cli_token.encode("utf-8") if config.cli_token else None
        self._origin = config.origin.encode("ascii")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = tuple((key.lower(), value) for key, value in scope.get("headers", ()))
        credential = bearer_credential(headers)
        has_origin = any(key == b"origin" for key, _ in headers)
        if self._cli_token is not None:
            is_cli_token = credential is not None and hmac.compare_digest(credential, self._cli_token)
            if is_cli_token and not has_origin:
                await self._app(scope, receive, send)
                return
            if is_cli_token:
                await _json_error(send, status=403, code="desktop_origin_rejected")
                return
            if not has_origin:
                await _json_error(send, status=401, code="desktop_auth_required", authenticate=True)
                return
        origin = _unique_header(headers, b"origin")
        if origin is None or not hmac.compare_digest(origin, self._origin):
            await _json_error(send, status=403, code="desktop_origin_rejected")
            return

        # Browser CORS preflight requests cannot carry the requested bearer token.
        # Exact-origin validation still prevents an untrusted renderer from probing it.
        if scope.get("method") == "OPTIONS":
            await self._app(scope, receive, send)
            return

        if credential is None or not hmac.compare_digest(credential, self._token):
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
