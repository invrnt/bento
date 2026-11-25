"""Per-invocation state shared by command handlers: parsed flags, output, profile, and the lazily resolved API."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx

from bento.interfaces.cli import cli_version
from bento.interfaces.cli.client import BentoClient
from bento.interfaces.cli.errors import CliError, confirmation_required
from bento.interfaces.cli.output import Output
from bento.interfaces.cli.profiles import Endpoint, Profile, cli_home
from bento.interfaces.cli.target import Target, TargetOptions, health_ok, resolve_target


class Context:
    def __init__(
        self,
        args: argparse.Namespace,
        out: Output,
        *,
        environ: Mapping[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        start_daemon: Callable[[Profile, float], Endpoint] | None = None,
    ) -> None:
        self.args = args
        self.out = out
        self.t = out.t
        self.environ: Mapping[str, str] = os.environ if environ is None else environ
        self._transport = transport
        self._start_daemon = start_daemon
        profile_name = getattr(args, "profile", None) or self.environ.get("BENTO_PROFILE", "").strip() or "default"
        self.profile_explicit = bool(getattr(args, "profile", None) or self.environ.get("BENTO_PROFILE", "").strip())
        self.profile = Profile.load(profile_name, _home(self.environ))
        self._client: BentoClient | None = None
        self._target: Target | None = None

    # Flags -------------------------------------------------------------------------------------

    def flag(self, name: str, default: Any = None) -> Any:
        return getattr(self.args, name, default)

    @property
    def timeout(self) -> float:
        value = self.flag("timeout")
        return float(value) if value else 30.0

    @property
    def yes(self) -> bool:
        return bool(self.flag("yes", False))

    # Target ------------------------------------------------------------------------------------

    def target_options(self, *, no_start: bool | None = None) -> TargetOptions:
        return TargetOptions(
            target=self.flag("target") or "auto",
            api_url=self.flag("api_url"),
            api_token=None,
            profile=self.profile,
            profile_explicit=self.profile_explicit,
            no_start=bool(self.flag("no_start", False)) if no_start is None else no_start,
            start_timeout=max(self.timeout, 60.0),
        )

    @property
    def target(self) -> Target:
        if self._target is None:
            start = self._start_daemon
            if start is None:
                from bento.interfaces.cli.daemon import start_daemon

                def start(profile: Profile, timeout: float) -> Endpoint:
                    return start_daemon(profile, timeout, environ=self.environ)

            self._target = resolve_target(
                self.target_options(),
                environ=self.environ,
                start_daemon=start,
                check=self._health_check,
            )
            if self._target.started:
                self.out.note(self.t("target.started", profile=self.profile.name))
        return self._target

    def try_target(self) -> Target | None:
        """The target without starting anything (for `version`, `doctor`)."""
        try:
            return resolve_target(
                self.target_options(no_start=True), environ=self.environ, check=self._health_check
            )
        except Exception:
            return None

    def _health_check(self, url: str, token: str | None) -> bool:
        return health_ok(url, token, transport=self._transport)

    @property
    def api(self) -> BentoClient:
        if self._client is None:
            target = self.target
            self._client = BentoClient(
                target.url,
                target.token,
                version=cli_version(),
                timeout=self.timeout,
                transport=self._transport,
            )
        return self._client

    def client_for(self, target: Target) -> BentoClient:
        return BentoClient(target.url, target.token, version=cli_version(), timeout=self.timeout, transport=self._transport)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    # Confirmation ------------------------------------------------------------------------------

    def require_confirmation(self, command: str, question: str) -> None:
        """Irreversible actions: `--yes`, or an explicit yes on a TTY; otherwise a usage error (exit 2)."""
        if self.yes:
            return
        if not self.out.interactive or self.out.json_mode:
            raise confirmation_required(command)
        if not self.out.confirm(question):
            raise CliError("cancelled", "Cancelled", {"command": command}, 1)


def _home(environ: Mapping[str, str]) -> Path:
    return cli_home(environ)
