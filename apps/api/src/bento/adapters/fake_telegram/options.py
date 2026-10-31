from __future__ import annotations

import socket
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

MANUAL_LOGIN_ENV = "BENTO_FAKE_TELEGRAM_MANUAL_LOGIN"
TWO_FACTOR_ENV = "BENTO_FAKE_TELEGRAM_2FA"
SESSION_TOO_NEW_ENV = "BENTO_FAKE_TELEGRAM_SESSION_TOO_NEW"

FAKE_LOGIN_CODE = "12345"
FAKE_PASSWORD = "bento-demo"
FAKE_PASSWORD_HINT = "demo"


def default_platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return "other"


@dataclass(frozen=True, slots=True)
class FakeTelegramOptions:
    """Behavior of one simulated Bento instance (each process reads its own environment)."""

    manual_login: bool = False
    two_factor: bool = False
    session_too_new: bool = False
    device_model: str = field(default_factory=socket.gethostname)
    platform: str = field(default_factory=default_platform)
    app_name: str = "Bento"
    auto_approve_seconds: float = 2.0
    qr_ttl_seconds: float = 30.0
    poll_interval_seconds: float = 0.2

    @classmethod
    def from_environ(cls, environ: Mapping[str, str], **overrides: Any) -> FakeTelegramOptions:
        options = cls(
            manual_login=_flag(environ, MANUAL_LOGIN_ENV),
            two_factor=_flag(environ, TWO_FACTOR_ENV),
            session_too_new=_flag(environ, SESSION_TOO_NEW_ENV),
        )
        return replace(options, **overrides)


def _flag(environ: Mapping[str, str], name: str) -> bool:
    return environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
