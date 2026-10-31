"""Relay wire format (`orchestration/api/pairing-relay-contract.md` § Frames).

Server → client control frames are small JSON text frames; everything Bento sends between the
devices travels as opaque binary frames (`type u8 || payload`, built by the pairing crypto session).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit

from bento.domain.pairing import PairingRole

MAX_FRAME_BYTES = 64 * 1024
"""Largest binary frame the relay forwards."""
MAX_FRAMES_PER_SIDE = 128
"""Binary frames one side may send per room."""
MAX_CONTROL_FRAME_BYTES = 1024
CLOSE_COMMAND = '{"type":"close"}'
CLOSE_NORMAL = 1000
CLOSE_EXPIRED = 4000
CLOSE_ERROR = 4001

NAMEPLATE_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{4}$")

RELAY_ERROR_CODES: dict[str, str] = {
    "nameplate_taken": "pairing_nameplate_taken",
    "room_not_found": "pairing_room_not_found",
    "room_full": "pairing_room_full",
    "expired": "pairing_expired",
    "rate_limited": "pairing_rate_limited",
    "message_too_large": "pairing_protocol",
    "protocol": "pairing_protocol",
}
"""Relay error code → `PairingError` code."""


class RelayFrameType(StrEnum):
    WELCOME = "welcome"
    PEER_JOINED = "peer_joined"
    PEER_LEFT = "peer_left"
    ERROR = "error"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class RelayEvent:
    type: RelayFrameType
    role: PairingRole | None = None
    expires_at: datetime | None = None
    code: str | None = None
    reason: str | None = None


class RelayFrameError(ValueError):
    """A control frame that does not follow the relay contract."""


def parse_control_frame(text: str) -> RelayEvent:
    if len(text.encode("utf-8")) > MAX_CONTROL_FRAME_BYTES:
        raise RelayFrameError("control frame too large")
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise RelayFrameError("control frame is not JSON") from exc
    if not isinstance(payload, dict):
        raise RelayFrameError("control frame is not an object")
    try:
        frame_type = RelayFrameType(payload.get("type"))
    except ValueError as exc:
        raise RelayFrameError("unknown control frame") from exc
    if frame_type is RelayFrameType.WELCOME:
        try:
            role = PairingRole(payload.get("role"))
            expires_at = datetime.fromisoformat(str(payload.get("expires_at")).replace("Z", "+00:00"))
        except ValueError as exc:
            raise RelayFrameError("invalid welcome frame") from exc
        if expires_at.tzinfo is None:
            raise RelayFrameError("welcome expiry has no time zone")
        return RelayEvent(frame_type, role=role, expires_at=expires_at)
    if frame_type is RelayFrameType.ERROR:
        code = payload.get("code")
        if not isinstance(code, str):
            raise RelayFrameError("invalid error frame")
        return RelayEvent(frame_type, code=code)
    if frame_type is RelayFrameType.CLOSED:
        reason = payload.get("reason")
        if not isinstance(reason, str):
            raise RelayFrameError("invalid closed frame")
        return RelayEvent(frame_type, reason=reason)
    return RelayEvent(frame_type)


def pairing_error_code(relay_code: str | None) -> str:
    return RELAY_ERROR_CODES.get(relay_code or "", "pairing_protocol")


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def normalize_relay_url(relay_url: str) -> str:
    """`wss://host[:port]` without query or trailing slash; `""` when unset.

    Plain `ws://` is accepted only for loopback hosts (local `npm run dev` of `apps/relay`).
    Raises `ValueError` for anything else.
    """
    value = relay_url.strip()
    if not value:
        return ""
    parts = urlsplit(value)
    try:
        host = parts.hostname
        parts.port  # noqa: B018 - validates the port
    except ValueError as exc:
        raise ValueError("relay_url has an invalid port") from exc
    if not host or parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ValueError("relay_url must be a plain wss:// origin")
    if parts.scheme == "ws" and host.lower() not in LOOPBACK_HOSTS:
        raise ValueError("relay_url must use wss:// (ws:// is only allowed for loopback hosts)")
    if parts.scheme not in {"ws", "wss"}:
        raise ValueError("relay_url must be a wss:// origin")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def room_url(relay_url: str, nameplate: str, role: PairingRole) -> str:
    if NAMEPLATE_PATTERN.match(nameplate) is None:
        raise ValueError("nameplate must be four upper-case Crockford Base32 characters")
    return f"{relay_url}/v1/rooms/{nameplate}?role={PairingRole(role).value}"


def health_url(relay_url: str) -> str:
    parts = urlsplit(relay_url)
    scheme = "https" if parts.scheme == "wss" else "http"
    return urlunsplit((scheme, parts.netloc, f"{parts.path}/v1/health", "", ""))
