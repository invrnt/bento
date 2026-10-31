from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import parse_qs, urlsplit

from bento.domain.errors import DomainError

CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CROCKFORD_ALIASES = str.maketrans({"O": "0", "I": "1", "L": "1"})
_GROUP = re.compile(rf"^[{CROCKFORD_ALPHABET}]{{4}}$")


class PairingRole(StrEnum):
    HOST = "host"
    GUEST = "guest"


class PairingTransport(StrEnum):
    RELAY = "relay"
    TELEGRAM = "telegram"


class PairingState(StrEnum):
    WAITING = "waiting"
    CONNECTED = "connected"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVING = "approving"
    NEEDS_TELEGRAM_LOGIN = "needs_telegram_login"
    BOOTSTRAPPING = "bootstrapping"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in _TERMINAL


_TERMINAL = frozenset(
    {PairingState.COMPLETED, PairingState.REJECTED, PairingState.FAILED, PairingState.EXPIRED, PairingState.CANCELLED}
)


class PairingError(DomainError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)


class PairingCodeInvalidError(PairingError):
    def __init__(self) -> None:
        super().__init__("pairing_code_invalid", "Pairing code is invalid")


@dataclass(frozen=True, slots=True)
class PairingCode:
    """`NNNN-SSSS-SSSS`: a relay nameplate followed by the 40-bit SPAKE2 password."""

    nameplate: str
    secret: str

    def __post_init__(self) -> None:
        groups = [self.nameplate, self.secret[:4], self.secret[4:]]
        if len(self.secret) != 8 or any(_GROUP.match(group) is None for group in groups):
            raise PairingCodeInvalidError()

    def format(self) -> str:
        return f"{self.nameplate}-{self.secret[:4]}-{self.secret[4:]}"

    def link(self) -> str:
        return f"bento://join?v=1&c={self.format()}"

    def web_link(self, site_url: str) -> str:
        return f"{site_url.rstrip('/')}/join#v=1&c={self.format()}"

    @property
    def password(self) -> bytes:
        return self.secret.encode("ascii")

    @classmethod
    def parse(cls, value: str) -> PairingCode:
        """Accept a typed code, a `bento://join` link, or an https join link with the code in the fragment."""
        raw = value.strip()
        if "://" in raw:
            parts = urlsplit(raw)
            query = parse_qs(parts.query or parts.fragment)
            raw = (query.get("c") or [""])[0]
        normalized = re.sub(r"[\s-]", "", raw.upper()).translate(_CROCKFORD_ALIASES)
        if len(normalized) != 12:
            raise PairingCodeInvalidError()
        return cls(nameplate=normalized[:4], secret=normalized[4:])


@dataclass(frozen=True, slots=True)
class PairingPeer:
    device_name: str
    platform: str


@dataclass(frozen=True, slots=True)
class PairingSession:
    id: str
    role: PairingRole
    transport: PairingTransport
    state: PairingState
    expires_at: datetime
    code: PairingCode | None = None
    peer: PairingPeer | None = None
    sas: tuple[str, ...] | None = None
    needs_telegram_qr: bool = False
    error_code: str | None = None


ALLOWED_TRANSITIONS: dict[PairingState, frozenset[PairingState]] = {
    PairingState.WAITING: frozenset({PairingState.CONNECTED, *_TERMINAL}),
    PairingState.CONNECTED: frozenset(
        {PairingState.AWAITING_APPROVAL, PairingState.NEEDS_TELEGRAM_LOGIN, *_TERMINAL}
    ),
    PairingState.AWAITING_APPROVAL: frozenset(
        {PairingState.APPROVING, PairingState.NEEDS_TELEGRAM_LOGIN, *_TERMINAL}
    ),
    PairingState.NEEDS_TELEGRAM_LOGIN: frozenset(
        {PairingState.AWAITING_APPROVAL, PairingState.APPROVING, *_TERMINAL}
    ),
    PairingState.APPROVING: frozenset({PairingState.BOOTSTRAPPING, PairingState.NEEDS_TELEGRAM_LOGIN, *_TERMINAL}),
    PairingState.BOOTSTRAPPING: frozenset({PairingState.COMPLETED, PairingState.FAILED}),
}


def can_transition(current: PairingState, target: PairingState) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())
