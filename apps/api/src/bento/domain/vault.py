from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from bento.domain.errors import ValidationFailedError
from bento.domain.security import RecoveryWrap

VAULT_HEADER_MARKER = "vault-header"
VAULT_HEADER_VERSION = 1
CHANNEL_TITLES = {"files": "Bento · Archivos", "sync": "Bento · Sync", "inbox": "Bento · Bandeja"}
CHAT_FOLDER_TITLE = "Bento"
VAULT_TITLE_PREFIX = "Bento"
CHANNEL_ABOUT_NOTICE = "Creado por Bento. No borres ni edites estos mensajes."
_MARKER_PATTERN = re.compile(r"^bento:v1:(files|sync|inbox):(vlt_[0-9A-Za-z_-]+)$")
_DIGEST_PATTERN = re.compile(r"[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]")
"""Unpadded base64url of exactly 32 bytes (the last character carries 2 zero bits)."""


class VaultState(StrEnum):
    LOCAL_ONLY = "local_only"
    SIGNED_OUT = "signed_out"
    NO_VAULT = "no_vault"
    LOCKED = "locked"
    BOOTSTRAPPING = "bootstrapping"
    READY = "ready"


class VaultChannelRole(StrEnum):
    FILES = "files"
    SYNC = "sync"
    INBOX = "inbox"


def channel_marker(role: VaultChannelRole, vault_id: str) -> str:
    return f"bento:v1:{role.value}:{vault_id}"


def channel_about(role: VaultChannelRole, vault_id: str) -> str:
    """Channel description: the machine marker line plus the human notice."""
    return f"{channel_marker(role, vault_id)}\n{CHANNEL_ABOUT_NOTICE}"


def parse_channel_marker(about: str) -> tuple[VaultChannelRole, str] | None:
    for line in about.splitlines():
        match = _MARKER_PATTERN.match(line.strip())
        if match is not None:
            return VaultChannelRole(match.group(1)), match.group(2)
    return None


@dataclass(frozen=True, slots=True)
class VaultChannelCandidate:
    """A channel seen while iterating dialogs, with its full `about` text."""

    channel_id: int
    title: str
    about: str
    creator: bool


def discover_vault_layouts(candidates: Iterable[VaultChannelCandidate]) -> tuple[VaultLayout, ...]:
    """Discovery rules: creator-owned channels titled `Bento…` whose about carries a marker; complete vaults only.

    The first candidate wins when a role is duplicated; layouts keep the order in which vaults were first seen.
    """
    roles: dict[str, dict[VaultChannelRole, int]] = {}
    for candidate in candidates:
        if not candidate.creator or not candidate.title.startswith(VAULT_TITLE_PREFIX):
            continue
        parsed = parse_channel_marker(candidate.about)
        if parsed is None:
            continue
        role, vault_id = parsed
        roles.setdefault(vault_id, {}).setdefault(role, candidate.channel_id)
    return tuple(
        VaultLayout(
            vault_id=vault_id,
            files_channel_id=channels[VaultChannelRole.FILES],
            sync_channel_id=channels[VaultChannelRole.SYNC],
            inbox_channel_id=channels[VaultChannelRole.INBOX],
        )
        for vault_id, channels in roles.items()
        if len(channels) == len(VaultChannelRole)
    )


@dataclass(frozen=True, slots=True)
class VaultLayout:
    vault_id: str
    files_channel_id: int
    sync_channel_id: int
    inbox_channel_id: int

    def channel_id(self, role: VaultChannelRole) -> int:
        if role == VaultChannelRole.FILES:
            return self.files_channel_id
        if role == VaultChannelRole.SYNC:
            return self.sync_channel_id
        return self.inbox_channel_id


@dataclass(frozen=True, slots=True)
class SnapshotPointer:
    message_id: int
    covers_through_message_id: int
    created_at: datetime
    sha256: str | None = None
    """Unpadded base64url SHA-256 of the `.bsnap` document bytes, MAC-covered. Every new pointer carries it;
    a pointer without it (headers written before the field existed) is not trusted at bootstrap."""


@dataclass(frozen=True, slots=True)
class VaultHeader:
    vault_id: str
    created_at: datetime
    layout: VaultLayout
    current_epoch: int
    recovery: RecoveryWrap
    snapshot: SnapshotPointer | None = None
    mac: str | None = None

    def unsigned_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "bento": VAULT_HEADER_MARKER,
            "v": VAULT_HEADER_VERSION,
            "vault_id": self.vault_id,
            "created_at": self.created_at.isoformat(),
            "layout": {
                "files": self.layout.files_channel_id,
                "sync": self.layout.sync_channel_id,
                "inbox": self.layout.inbox_channel_id,
            },
            "current_epoch": self.current_epoch,
            "recovery": _recovery_payload(self.recovery),
            "snapshot": None if self.snapshot is None else _snapshot_payload(self.snapshot),
        }
        return payload

    def canonical_unsigned_bytes(self) -> bytes:
        """Bytes covered by the header MAC: canonical JSON without the `mac` field."""
        return canonical_json(self.unsigned_payload())

    def to_json(self) -> str:
        payload = self.unsigned_payload()
        payload["mac"] = self.mac
        return canonical_json(payload).decode("utf-8")

    @classmethod
    def from_json(cls, text: str) -> VaultHeader:
        try:
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError("not a vault header")
            if payload.get("bento") != VAULT_HEADER_MARKER or payload.get("v") != VAULT_HEADER_VERSION:
                raise ValueError("not a vault header")
            layout = payload["layout"]
            recovery = payload["recovery"]
            snapshot = payload.get("snapshot")
            vault_id = str(payload["vault_id"])
            return cls(
                vault_id=vault_id,
                created_at=_aware(payload["created_at"]),
                layout=VaultLayout(
                    vault_id=vault_id,
                    files_channel_id=int(layout["files"]),
                    sync_channel_id=int(layout["sync"]),
                    inbox_channel_id=int(layout["inbox"]),
                ),
                current_epoch=int(payload["current_epoch"]),
                recovery=RecoveryWrap(
                    alg=str(recovery["alg"]),
                    nonce=str(recovery["nonce"]),
                    wrapped_keyring=str(recovery["wrapped_keyring"]),
                    confirmed_at=_optional_datetime(recovery.get("confirmed_at")),
                ),
                snapshot=None
                if snapshot is None
                else SnapshotPointer(
                    message_id=int(snapshot["message_id"]),
                    covers_through_message_id=int(snapshot["covers_through_message_id"]),
                    created_at=_aware(snapshot["created_at"]),
                    sha256=_optional_digest(snapshot.get("sha256")),
                ),
                mac=payload.get("mac"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationFailedError("Invalid vault header") from exc


@dataclass(frozen=True, slots=True)
class VaultUsage:
    files: int = 0
    bytes: int = 0


@dataclass(frozen=True, slots=True)
class VaultStatus:
    state: VaultState
    vault_id: str | None = None
    created_at: datetime | None = None
    recovery_kit_saved: bool = False
    devices_count: int = 0
    usage: VaultUsage = VaultUsage()
    other_vaults: int = 0
    recovery_kit_stale: bool = False
    """The pinned header carries a recovery wrap of an older key epoch: a new kit must be generated."""
    reason: str | None = None
    """Why the vault is `locked` (`device_removed`) or `signed_out` (`session_closed`, `device_removed`) here."""


DEVICE_REMOVED_REASON = "device_removed"
SESSION_CLOSED_REASON = "session_closed"


def _recovery_payload(recovery: RecoveryWrap) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "alg": recovery.alg,
        "nonce": recovery.nonce,
        "wrapped_keyring": recovery.wrapped_keyring,
    }
    # Omitted until confirmed, so headers written before the field existed keep their MAC.
    if recovery.confirmed_at is not None:
        payload["confirmed_at"] = recovery.confirmed_at.isoformat()
    return payload


def _snapshot_payload(snapshot: SnapshotPointer) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "message_id": snapshot.message_id,
        "covers_through_message_id": snapshot.covers_through_message_id,
        "created_at": snapshot.created_at.isoformat(),
    }
    # Omitted only for pointers written before the field existed, so their MAC still verifies.
    if snapshot.sha256 is not None:
        payload["sha256"] = snapshot.sha256
    return payload


def _optional_digest(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError("snapshot sha256 must be unpadded base64url of 32 bytes")
    return value


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    return _aware(value)


def _aware(value: Any) -> datetime:
    """Header timestamps are unauthenticated until the MAC is checked: only timezone-aware ISO-8601 is accepted."""
    if not isinstance(value, str):
        raise ValueError("expected an ISO-8601 string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("header timestamps must carry a timezone")
    return parsed


def canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
