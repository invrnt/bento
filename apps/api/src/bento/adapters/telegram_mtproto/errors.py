"""Translation of Telethon failures into Bento domain errors (never echoing request payloads)."""

from __future__ import annotations

import asyncio

from telethon import errors

from bento.domain.errors import DomainError, StorageUnavailableError, TelegramAccountError, TelegramFloodWaitError
from bento.domain.storage import StorageBackend

FLOOD_ERRORS: tuple[type[BaseException], ...] = (
    errors.FloodWaitError,
    errors.FloodPremiumWaitError,
    errors.SlowModeWaitError,
)


def flood_wait_seconds(exc: BaseException) -> int | None:
    if isinstance(exc, FLOOD_ERRORS):
        return max(0, int(getattr(exc, "seconds", 0)))
    return None


def not_authorized() -> TelegramAccountError:
    return TelegramAccountError("telegram_not_authorized", "This device is not signed in to Telegram")


def network_error() -> TelegramAccountError:
    return TelegramAccountError("telegram_network", "Telegram could not be reached")


def map_telethon_error(exc: BaseException) -> DomainError | None:
    """A domain error for a Telethon/transport failure, or `None` when callers must handle it themselves."""
    if isinstance(exc, DomainError):
        return exc
    seconds = flood_wait_seconds(exc)
    if seconds is not None:
        return TelegramFloodWaitError(seconds)
    if isinstance(exc, errors.SessionPasswordNeededError):
        return None
    if isinstance(exc, (errors.UnauthorizedError, errors.AuthKeyError)):
        return not_authorized()
    if isinstance(exc, (errors.ServerError, errors.TimedOutError, ConnectionError, OSError, asyncio.TimeoutError)):
        return network_error()
    if isinstance(exc, errors.RPCError):
        error = StorageUnavailableError(StorageBackend.TELEGRAM.value)
        # RPC error names (e.g. CHANNEL_INVALID) are safe to expose; their request payloads are not.
        error.details["reason"] = str(getattr(exc, "message", "") or type(exc).__name__)
        return error
    return None
