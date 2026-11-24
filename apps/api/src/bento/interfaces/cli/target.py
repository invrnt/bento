"""Which Bento the CLI talks to (`architecture/cli-runtime.md` § Target resolution)."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from bento.interfaces.cli.client import CLIENT_HEADER, CLIENT_HEADER_VALUE, api_path
from bento.interfaces.cli.errors import EXIT_UNREACHABLE, CliError
from bento.interfaces.cli.profiles import Endpoint, Profile, desktop_endpoint_path, pid_alive, read_endpoint

TARGETS = ("auto", "desktop", "daemon")


@dataclass(frozen=True, slots=True)
class Target:
    kind: str  # url | desktop | daemon
    url: str
    token: str | None
    endpoint: Endpoint | None = None
    started: bool = False

    def public(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind, "url": self.url, "started": self.started}
        if self.endpoint is not None:
            data.update({key: value for key, value in self.endpoint.public().items() if key not in {"kind", "url"}})
        return data


@dataclass(frozen=True, slots=True)
class TargetOptions:
    target: str = "auto"
    api_url: str | None = None
    api_token: str | None = None
    profile: Profile | None = None
    profile_explicit: bool = False
    no_start: bool = False
    start_timeout: float = 60.0


def health_ok(url: str, token: str | None, *, timeout: float = 3.0, transport: httpx.BaseTransport | None = None) -> bool:
    headers = {CLIENT_HEADER: CLIENT_HEADER_VALUE}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            response = client.get(url.rstrip("/") + api_path("/health"), headers=headers)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def live_endpoint(path: os.PathLike[str] | str, *, check: Callable[[str, str | None], bool] = health_ok) -> Endpoint | None:
    from pathlib import Path

    endpoint = read_endpoint(Path(path))
    if endpoint is None or not pid_alive(endpoint.pid):
        return None
    if not check(endpoint.url, endpoint.token):
        return None
    return endpoint


def resolve_target(
    options: TargetOptions,
    *,
    environ: Mapping[str, str] | None = None,
    start_daemon: Callable[[Profile, float], Endpoint] | None = None,
    check: Callable[[str, str | None], bool] = health_ok,
) -> Target:
    env = os.environ if environ is None else environ
    api_url = options.api_url or env.get("BENTO_API_URL", "").strip() or None
    if api_url:
        token = options.api_token or env.get("BENTO_API_TOKEN", "").strip() or None
        return Target(kind="url", url=api_url.rstrip("/"), token=token)

    if options.target in {"auto", "desktop"} and not (options.target == "auto" and options.profile_explicit):
        desktop = live_endpoint(desktop_endpoint_path(env), check=check)
        if desktop is not None:
            return Target(kind="desktop", url=desktop.url, token=desktop.token, endpoint=desktop)
        if options.target == "desktop":
            raise CliError(
                "desktop_not_running",
                "The Bento desktop app is not running",
                {"endpoint_file": "cli-endpoint.json"},
                EXIT_UNREACHABLE,
            )

    profile = options.profile
    if profile is None:
        raise AssertionError("a profile is required for daemon targets")
    daemon = live_endpoint(profile.endpoint_file, check=check)
    if daemon is not None:
        return Target(kind="daemon", url=daemon.url, token=daemon.token, endpoint=daemon)
    if options.no_start:
        raise CliError(
            "daemon_not_running",
            "Bento is not running for this profile",
            {"profile": profile.name, "next": "bento daemon start"},
            EXIT_UNREACHABLE,
        )
    if start_daemon is None:
        from bento.interfaces.cli.daemon import start_daemon as default_start

        start_daemon = default_start
    endpoint = start_daemon(profile, options.start_timeout)
    return Target(kind="daemon", url=endpoint.url, token=endpoint.token, endpoint=endpoint, started=True)
