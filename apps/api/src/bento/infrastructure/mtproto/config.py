"""Bento's own Telegram application and how this device presents itself to Telegram."""

from __future__ import annotations

import platform
from dataclasses import dataclass, field

from bento.domain.errors import TelegramNotAvailableError
from bento.infrastructure.settings import Settings


@dataclass(frozen=True, slots=True)
class TelegramAppCredentials:
    """Build configuration (`BENTO_TELEGRAM_API_ID`, `BENTO_TELEGRAM_API_HASH`); never shown to people."""

    api_id: int
    api_hash: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ClientIdentity:
    device_model: str
    system_version: str
    app_version: str


def load_credentials(settings: Settings) -> TelegramAppCredentials:
    """Raises `TelegramNotAvailableError` when the build has no (valid) credentials."""
    api_id = (settings.telegram_api_id or "").strip()
    api_hash = (settings.telegram_api_hash or "").strip()
    if not api_id.isdigit() or not api_hash:
        raise TelegramNotAvailableError()
    return TelegramAppCredentials(api_id=int(api_id), api_hash=api_hash)


def system_version() -> str:
    """The operating system as Telegram lists it under the session (e.g. `Linux 6.8`)."""
    name = {"Darwin": "macOS"}.get(platform.system(), platform.system()) or "Unknown"
    release = platform.release() if name != "macOS" else platform.mac_ver()[0]
    return f"{name} {release}".strip()
