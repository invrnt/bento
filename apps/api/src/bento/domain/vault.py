from __future__ import annotations

import json
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
            "recovery": {
                "alg": self.recovery.alg,
                "nonce": self.recovery.nonce,
                "wrapped_keyring": self.recovery.wrapped_keyring,
            },
            "snapshot": None
            if self.snapshot is None
            else {
                "message_id": self.snapshot.message_id,
                "covers_through_message_id": self.snapshot.covers_through_message_id,
                "created_at": self.snapshot.created_at.isoformat(),
            },
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
            if payload.get("bento") != VAULT_HEADER_MARKER or payload.get("v") != VAULT_HEADER_VERSION:
                raise ValueError("not a vault header")
            layout = payload["layout"]
            recovery = payload["recovery"]
            snapshot = payload.get("snapshot")
            vault_id = str(payload["vault_id"])
            return cls(
                vault_id=vault_id,
                created_at=datetime.fromisoformat(payload["created_at"]),
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
                ),
                snapshot=None
                if snapshot is None
                else SnapshotPointer(
                    message_id=int(snapshot["message_id"]),
                    covers_through_message_id=int(snapshot["covers_through_message_id"]),
                    created_at=datetime.fromisoformat(snapshot["created_at"]),
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


def canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
