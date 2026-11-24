"""Host-device capabilities: conditions, semantic notifications, and content imports (`api/android-endpoints.md`).

Desktop/headless hosts use the permissive and no-op adapters in `adapters/device.py`; Android uses the bridge
adapters in `adapters/android/`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from bento.domain.device import DeviceConditions


class DeviceConditionsPort(Protocol):
    def snapshot(self) -> DeviceConditions: ...

    def subscribe(self, callback: Callable[[DeviceConditions], None]) -> Callable[[], None]:
        """Call `callback` (from any thread) whenever conditions change; returns an unsubscribe function."""
        ...


@dataclass(frozen=True, slots=True)
class NotifierEvent:
    """A semantic event (`transfer_progress`, `transfer_finished`, `attention`, `pairing_request`, `new_device`).

    Payloads carry ids and numbers only, never user-facing strings: the host owns text and channels.
    """

    name: str
    payload: dict[str, object] = field(default_factory=dict)


def transfer_progress(
    kind: str, *, done: int, total: int, bytes_done: int = 0, bytes_total: int = 0, paused: bool = False
) -> NotifierEvent:
    return NotifierEvent(
        "transfer_progress",
        {"kind": kind, "done": done, "total": total, "bytes_done": bytes_done, "bytes_total": bytes_total, "paused": paused},
    )


def transfer_finished(kind: str, *, count: int, failed: int) -> NotifierEvent:
    return NotifierEvent("transfer_finished", {"kind": kind, "count": count, "failed": failed})


def attention(code: str, *, count: int) -> NotifierEvent:
    return NotifierEvent("attention", {"code": code, "count": count})


def pairing_request(request_id: str, *, device_name: str, platform: str) -> NotifierEvent:
    return NotifierEvent("pairing_request", {"request_id": request_id, "device_name": device_name, "platform": platform})


def new_device(device_id: str, *, name: str) -> NotifierEvent:
    return NotifierEvent("new_device", {"device_id": device_id, "name": name})


class NotifierPort(Protocol):
    def emit(self, event: NotifierEvent) -> None:
        """Never blocks and never raises: notifications are best effort."""
        ...


@dataclass(frozen=True, slots=True)
class ContentDescription:
    display_name: str
    mime_type: str
    size_bytes: int | None = None


class ContentImportsPort(Protocol):
    def describe(self, handle: int) -> ContentDescription:
        """Metadata of a registered content handle. Raises `ContentHandleError` for unknown/consumed handles."""
        ...

    def adopt(self, handle: int) -> int:
        """The detached file descriptor behind `handle` (one-time); the caller owns and closes it."""
        ...


class ContentHandleError(LookupError):
    """The handle is unknown, already adopted, or the host could not open its content."""
