"""HTTP client for the local Bento API: auth headers, error mapping, and retries for idempotent GETs."""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import httpx

from bento.interfaces.cli.errors import EXIT_UNREACHABLE, CliError

CLIENT_HEADER = "X-Bento-Client"
CLIENT_HEADER_VALUE = "web"
_RETRY_STATUSES = frozenset({502, 503, 504})
_ROUTE_MISSING = "endpoint_not_available"
_AUTH_CODES = frozenset({"api_token_required", "desktop_auth_required", "desktop_origin_rejected"})


class BentoClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        version: str = "0",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        get_retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {CLIENT_HEADER: CLIENT_HEADER_VALUE, "User-Agent": f"bento-cli/{version}"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._get_retries = get_retries
        self._http = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> BentoClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # JSON calls -------------------------------------------------------------------------------

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: Any = None, params: Mapping[str, Any] | None = None) -> Any:
        return self.request("POST", path, json=json, params=params)

    def patch(self, path: str, json: Any = None) -> Any:
        return self.request("PATCH", path, json=json)

    def delete(self, path: str, json: Any = None) -> Any:
        return self.request("DELETE", path, json=json)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        files: Any = None,
        data: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        response = self.send(method, path, params=params, json=json, files=files, data=data, timeout=timeout)
        return decode_json(response)

    def send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        files: Any = None,
        data: Mapping[str, Any] | None = None,
        timeout: float | None = None,
        raise_for_status: bool = True,
    ) -> httpx.Response:
        attempts = 1 + (self._get_retries if method.upper() == "GET" else 0)
        clean_params = _clean_params(params)
        for attempt in range(attempts):
            try:
                extra: dict[str, Any] = {}
                if timeout is not None:
                    extra["timeout"] = timeout
                if json is not None and method.upper() != "GET":
                    extra["json"] = json
                response = self._http.request(
                    method, api_path(path), params=clean_params, files=files, data=data, **extra
                )
            except httpx.TransportError as exc:
                if attempt + 1 < attempts:
                    time.sleep(0.3 * (attempt + 1))
                    continue
                raise unreachable(self.base_url, exc) from exc
            if response.status_code in _RETRY_STATUSES and attempt + 1 < attempts:
                time.sleep(0.3 * (attempt + 1))
                continue
            if raise_for_status and response.status_code >= 400:
                raise api_error(response)
            return response
        raise AssertionError("unreachable")

    @contextmanager
    def stream(self, method: str, path: str, *, params: Mapping[str, Any] | None = None) -> Iterator[httpx.Response]:
        try:
            with self._http.stream(method, api_path(path), params=_clean_params(params)) as response:
                if response.status_code >= 400:
                    response.read()
                    raise api_error(response)
                yield response
        except httpx.TransportError as exc:
            raise unreachable(self.base_url, exc) from exc


def api_path(path: str) -> str:
    if path.startswith("/api/") or path == "/api":
        return path
    return "/api" + (path if path.startswith("/") else "/" + path)


def _clean_params(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if params is None:
        return None
    clean: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        clean[key] = ("true" if value else "false") if isinstance(value, bool) else value
    return clean


def decode_json(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return {"content": response.text}


def unreachable(base_url: str, exc: Exception | None = None) -> CliError:
    details: dict[str, Any] = {"url": base_url}
    if exc is not None:
        details["reason"] = type(exc).__name__
    return CliError("bento_unreachable", "Bento is not reachable", details, EXIT_UNREACHABLE)


def api_error(response: httpx.Response) -> CliError:
    status = response.status_code
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("code"), str):
            raw_details = error.get("details")
            details: dict[str, Any] = dict(raw_details) if isinstance(raw_details, dict) else {}
            if status == 429 and "retry_after_seconds" not in details and response.headers.get("Retry-After"):
                try:
                    details = {**details, "retry_after_seconds": int(response.headers["Retry-After"])}
                except ValueError:
                    pass
            code = str(error["code"])
            exit_code = EXIT_UNREACHABLE if code in _AUTH_CODES else None
            return CliError(code, str(error.get("message") or code), details, exit_code, status=status)
        detail = body.get("detail")
        if isinstance(detail, dict) and isinstance(detail.get("code"), str):
            code = str(detail["code"])
            exit_code = EXIT_UNREACHABLE if code in _AUTH_CODES else None
            return CliError(code, str(detail.get("message") or code), {}, exit_code, status=status)
        if (status == 404 and detail == "Not Found") or (status == 405 and detail == "Method Not Allowed"):
            return CliError(
                _ROUTE_MISSING,
                "This Bento version does not provide this endpoint; update Bento",
                {"path": response.request.url.path},
                1,
                status=status,
            )
        if status == 422 and isinstance(detail, list):
            fields = [
                ".".join(str(part) for part in item.get("loc", ()) if part != "body")
                for item in detail
                if isinstance(item, dict)
            ]
            return CliError("request_validation_failed", "The API rejected the request", {"fields": fields}, 2, status=status)
    return CliError("http_error", f"HTTP {status}", {"status": status}, status=status)
