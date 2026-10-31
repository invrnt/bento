"""Device pairing (`orchestration/architecture/telegram-first.md` § Pairing Protocol).

Two transports share one session model and state machine (`domain.pairing`):

- **relay** — SPAKE2 + key confirmation + AES-GCM application messages through the pairing relay.
  The host shows a code; the guest types or scans it.
- **telegram** — the Sync-channel fallback with commit-then-reveal ephemeral X25519 keys. The guest must
  already be signed in to Telegram; hosts list pending requests and review them.

Sessions live in this process only; each runs as one background task. Codes, SAS emojis, login
tokens, and keys are never logged.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import logging
import re
import secrets
import unicodedata
import uuid
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Protocol

from bento.domain.account import LoginStep
from bento.domain.devices import Device, DevicePlatform
from bento.domain.errors import (
    DomainError,
    IntegrityError,
    TelegramAccountError,
    ValidationFailedError,
    VaultNotFoundError,
)
from bento.domain.pairing import (
    CROCKFORD_ALPHABET,
    PairingCode,
    PairingError,
    PairingPeer,
    PairingRole,
    PairingSession,
    PairingState,
    PairingTransport,
    PairingVaultInfo,
    can_transition,
)
from bento.domain.security import DeviceIdentity, VaultKeyring
from bento.domain.sync import SyncMessageKind, SyncMessageRef
from bento.domain.vault import VaultHeader, VaultLayout, VaultState, VaultStatus, canonical_json
from bento.ports.pairing import DeviceRepositoryPort, PairingChannelPort, PairingRelayPort
from bento.ports.security import (
    FallbackPairingKeysPort,
    PairingCryptoFactoryPort,
    PairingCryptoSessionPort,
    VaultCryptoPort,
)
from bento.ports.sync import SyncStateRepositoryPort
from bento.ports.telegram import TelegramAccountPort, VaultTransportPort
from bento.ports.vault import VaultContext, VaultSessionPort

logger = logging.getLogger("bento.pairing")

PAIRING_TTL_SECONDS = 600.0
FALLBACK_REQUEST_TTL_SECONDS = 900.0
MAX_DEVICE_NAME_CHARS = 64
MAX_LOGIN_TOKEN_BYTES = 512
MAX_SEALED_KEYRING_BYTES = 48 * 1024
MAX_FALLBACK_GRANT_BYTES = MAX_SEALED_KEYRING_BYTES + 28
"""A fallback grant is `nonce 12B || AES-256-GCM(sealed keyring) || tag 16B`."""
MAX_FALLBACK_MESSAGE_BYTES = 64 * 1024
MAX_FALLBACK_TEXT_CHARS = 3500
"""Longer fallback messages are posted as `.bpair` documents instead of text (Telegram allows 4096)."""
FALLBACK_PROTOCOL_VERSION = 1
MAX_PENDING_GRANTS = 16
"""Grants a Sync-channel guest keeps, unopened, until the user confirms the emojis."""
MAX_OFFERED_DEVICES = 1000

_DEVICE_ID = re.compile(r"^dev_[0-9A-Za-z_]{1,64}$")
_VAULT_ID = re.compile(r"^vlt_[0-9A-Za-z_-]{1,64}$")
_REQUEST_ID = re.compile(r"^[0-9A-Za-z_-]{16,64}$")
_REASON = re.compile(r"^[a-z0-9_]{1,64}$")
DEVICE_REMOVED_REASON = "device_removed"
"""`reason` of a `rejected` frame or `pair_reject` sent to a guest whose device id was removed."""
_B64URL = re.compile(r"^[A-Za-z0-9_-]*={0,2}$")
_MAX_CHANNEL_ID = 1 << 62

_ERROR_MESSAGES: dict[str, str] = {
    "pairing_code_mismatch": "The pairing code does not match on both devices",
    "pairing_peer_left": "The other device left the pairing",
    "pairing_timeout": "The other device did not answer in time",
    "pairing_expired": "The pairing code expired",
    "pairing_room_not_found": "No device is waiting for this code",
    "pairing_room_full": "This pairing code was already used",
    "pairing_relay_unavailable": "The pairing relay is unreachable",
    "pairing_rate_limited": "Too many pairing attempts; wait a minute",
    "pairing_protocol": "The other device sent an invalid pairing message",
    "pairing_grant_invalid": "The vault access sent by the other device is invalid",
    "pairing_commitment_mismatch": "The new device's keys do not match its request",
    "pairing_request_taken": "Another device answered this request",
    "pairing_vault_ambiguous": "This Telegram account has several Bento vaults; pair with a code or the recovery code",
    "pairing_device_removed": "This device was removed from the vault; it must join again with a new identity",
    "pairing_request_expired": "The pairing request expired",
    "pairing_internal": "Pairing failed unexpectedly",
}


def pairing_error(code: str) -> PairingError:
    return PairingError(code, _ERROR_MESSAGES.get(code, "Pairing failed"))


# Encoding helpers ---------------------------------------------------------------------------------


def b64url_encode(data: bytes) -> str:
    """Unpadded URL-safe base64, the encoding of every binary value in pairing messages and device rows."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(value: object, *, max_bytes: int) -> bytes:
    """Strict URL-safe base64 (optional padding). Raises `ValidationFailedError`."""
    if not isinstance(value, str) or len(value) > (max_bytes * 4) // 3 + 4 or _B64URL.match(value) is None:
        raise ValidationFailedError("Invalid base64url value")
    body = value.rstrip("=")
    if len(body) % 4 == 1:
        raise ValidationFailedError("Invalid base64url value")
    try:
        decoded = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except (binascii.Error, ValueError):
        raise ValidationFailedError("Invalid base64url value") from None
    if len(decoded) > max_bytes:
        raise ValidationFailedError("Value is too large")
    return decoded


def decode_public_key(value: object) -> bytes:
    """A device's X25519 public key as stored in `Device.public_key` (unpadded base64url of 32 bytes)."""
    key = b64url_decode(value, max_bytes=32)
    if len(key) != 32:
        raise ValidationFailedError("Device public keys are 32 bytes")
    return key


def generate_pairing_code() -> PairingCode:
    """Random nameplate (20 bits) and SPAKE2 secret (40 bits) from the unambiguous Crockford alphabet."""
    return PairingCode(
        nameplate="".join(secrets.choice(CROCKFORD_ALPHABET) for _ in range(4)),
        secret="".join(secrets.choice(CROCKFORD_ALPHABET) for _ in range(8)),
    )


def normalize_device_name(value: object) -> str:
    """Trimmed, single-spaced, 1..64 characters, without control or format characters."""
    if not isinstance(value, str):
        raise ValidationFailedError("Device name must be text")
    name = " ".join(value.split())
    if not name or len(name) > MAX_DEVICE_NAME_CHARS:
        raise ValidationFailedError("Device name must have 1 to 64 characters", {"max_length": MAX_DEVICE_NAME_CHARS})
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Co", "Cn"} for char in name):
        raise ValidationFailedError("Device name contains invalid characters")
    return name


def parse_platform(value: object) -> DevicePlatform:
    try:
        return DevicePlatform(value)
    except ValueError:
        return DevicePlatform.OTHER


# Relay application messages -----------------------------------------------------------------------


class MessageType(StrEnum):
    JOIN_REQUEST = "join_request"
    LOGIN_TOKEN = "login_token"
    TELEGRAM_READY = "telegram_ready"
    DONE = "done"
    NEED_LOGIN_TOKEN = "need_login_token"
    TELEGRAM_LOGIN_FAILED = "telegram_login_failed"
    VAULT_GRANT = "vault_grant"
    REJECTED = "rejected"


_SENT_BY: dict[PairingRole, frozenset[MessageType]] = {
    PairingRole.GUEST: frozenset(
        {MessageType.JOIN_REQUEST, MessageType.LOGIN_TOKEN, MessageType.TELEGRAM_READY, MessageType.DONE}
    ),
    PairingRole.HOST: frozenset(
        {
            MessageType.NEED_LOGIN_TOKEN,
            MessageType.TELEGRAM_LOGIN_FAILED,
            MessageType.VAULT_GRANT,
            MessageType.REJECTED,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class JoinRequest:
    device_id: str
    device_name: str
    platform: DevicePlatform
    public_key: bytes
    app_version: str
    telegram_authorized: bool
    login_token: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class VaultGrant:
    layout: VaultLayout
    sealed_keyring: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class PeerMessage:
    type: MessageType
    join: JoinRequest | None = None
    login_token: bytes | None = field(default=None, repr=False)
    grant: VaultGrant | None = None
    reason: str | None = None


def parse_peer_message(payload: Mapping[str, Any], *, sender: PairingRole) -> PeerMessage:
    """Validate a decrypted application message from `sender`. Raises `PairingError('pairing_protocol')`."""
    try:
        message_type = MessageType(payload.get("type"))
    except (ValueError, AttributeError):
        raise pairing_error("pairing_protocol") from None
    if message_type not in _SENT_BY[sender]:
        raise pairing_error("pairing_protocol")
    try:
        if message_type is MessageType.JOIN_REQUEST:
            return PeerMessage(message_type, join=_parse_join_request(payload))
        if message_type is MessageType.LOGIN_TOKEN:
            return PeerMessage(message_type, login_token=_login_token(payload.get("login_token_b64")))
        if message_type is MessageType.VAULT_GRANT:
            return PeerMessage(message_type, grant=_parse_grant(payload))
        if message_type is MessageType.TELEGRAM_LOGIN_FAILED:
            reason = payload.get("reason")
            return PeerMessage(message_type, reason=reason if isinstance(reason, str) and _REASON.match(reason) else "unknown")
        if message_type is MessageType.REJECTED:
            reason = payload.get("reason")
            return PeerMessage(message_type, reason=reason if isinstance(reason, str) and _REASON.match(reason) else None)
    except ValidationFailedError:
        raise pairing_error("pairing_protocol") from None
    return PeerMessage(message_type)


def join_request_message(
    identity: DeviceIdentity, *, name: str, platform: DevicePlatform, app_version: str, login_token: bytes | None
) -> dict[str, Any]:
    telegram: dict[str, Any] = {"authorized": login_token is None}
    if login_token is not None:
        telegram["login_token_b64"] = b64url_encode(login_token)
    return {
        "type": MessageType.JOIN_REQUEST.value,
        "device_id": identity.device_id,
        "device_name": name,
        "platform": platform.value,
        "public_key": b64url_encode(identity.public_key),
        "app_version": app_version,
        "telegram": telegram,
    }


def vault_grant_message(layout: VaultLayout, sealed_keyring: bytes) -> dict[str, Any]:
    return {
        "type": MessageType.VAULT_GRANT.value,
        "vault_id": layout.vault_id,
        "layout": {"files": layout.files_channel_id, "sync": layout.sync_channel_id, "inbox": layout.inbox_channel_id},
        "sealed_keyring": b64url_encode(sealed_keyring),
    }


def _parse_join_request(payload: Mapping[str, Any]) -> JoinRequest:
    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or _DEVICE_ID.match(device_id) is None:
        raise ValidationFailedError("invalid device id")
    app_version = payload.get("app_version", "")
    if not isinstance(app_version, str) or len(app_version) > 32 or not app_version.isprintable():
        raise ValidationFailedError("invalid app version")
    telegram = payload.get("telegram")
    if not isinstance(telegram, Mapping) or not isinstance(telegram.get("authorized"), bool):
        raise ValidationFailedError("invalid telegram state")
    authorized = bool(telegram["authorized"])
    token = None if authorized else _login_token(telegram.get("login_token_b64"))
    return JoinRequest(
        device_id=device_id,
        device_name=normalize_device_name(payload.get("device_name")),
        platform=parse_platform(payload.get("platform")),
        public_key=decode_public_key(payload.get("public_key")),
        app_version=app_version,
        telegram_authorized=authorized,
        login_token=token,
    )


def _login_token(value: object) -> bytes:
    token = b64url_decode(value, max_bytes=MAX_LOGIN_TOKEN_BYTES)
    if not token:
        raise ValidationFailedError("empty login token")
    return token


def _parse_grant(payload: Mapping[str, Any]) -> VaultGrant:
    vault_id = payload.get("vault_id")
    layout = payload.get("layout")
    if not isinstance(vault_id, str) or _VAULT_ID.match(vault_id) is None or not isinstance(layout, Mapping):
        raise ValidationFailedError("invalid vault grant")
    sealed = b64url_decode(payload.get("sealed_keyring"), max_bytes=MAX_SEALED_KEYRING_BYTES)
    return VaultGrant(
        layout=VaultLayout(
            vault_id=vault_id,
            files_channel_id=_channel_id(layout.get("files")),
            sync_channel_id=_channel_id(layout.get("sync")),
            inbox_channel_id=_channel_id(layout.get("inbox")),
        ),
        sealed_keyring=sealed,
    )


def _channel_id(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value == 0 or abs(value) >= _MAX_CHANNEL_ID:
        raise ValidationFailedError("invalid channel id")
    return value


# Sync-channel fallback messages -------------------------------------------------------------------


class FallbackKind(StrEnum):
    REQUEST = "pair_request"
    OFFER = "pair_offer"
    REVEAL = "pair_reveal"
    GRANT = "pair_grant"
    REJECT = "pair_reject"


@dataclass(frozen=True, slots=True)
class FallbackRequest:
    request_id: str
    device_id: str
    device_name: str
    platform: DevicePlatform
    public_key: bytes
    commitment: str
    message_id: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FallbackMessage:
    kind: FallbackKind
    request_id: str
    message_id: int
    created_at: datetime
    request: FallbackRequest | None = None
    eph_pub: bytes | None = None
    offer_eph_pub: bytes | None = None
    devices_count: int | None = None
    reason: str | None = None
    grant: bytes | None = field(default=None, repr=False)


def parse_fallback_message(text: str, *, message_id: int, created_at: datetime) -> FallbackMessage | None:
    """Parse one plaintext pairing message from the Sync channel; anything malformed is ignored (None)."""
    if len(text) > MAX_FALLBACK_MESSAGE_BYTES:
        return None
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if not isinstance(payload, dict) or payload.get("v") != FALLBACK_PROTOCOL_VERSION:
        return None
    try:
        kind = FallbackKind(payload.get("bento"))
    except ValueError:
        return None
    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or _REQUEST_ID.match(request_id) is None:
        return None
    base = {"kind": kind, "request_id": request_id, "message_id": message_id, "created_at": created_at}
    try:
        if kind is FallbackKind.REQUEST:
            device_id = payload.get("device_id")
            commitment = payload.get("commitment")
            if not isinstance(device_id, str) or _DEVICE_ID.match(device_id) is None:
                return None
            if len(b64url_decode(commitment, max_bytes=32)) != 32:
                return None
            assert isinstance(commitment, str)
            request = FallbackRequest(
                request_id=request_id,
                device_id=device_id,
                device_name=normalize_device_name(payload.get("device_name")),
                platform=parse_platform(payload.get("platform")),
                public_key=decode_public_key(payload.get("public_key")),
                commitment=commitment,
                message_id=message_id,
                created_at=created_at,
            )
            return FallbackMessage(**base, request=request)
        if kind in {FallbackKind.OFFER, FallbackKind.REVEAL}:
            offer = payload.get("offer")
            return FallbackMessage(
                **base,
                eph_pub=decode_public_key(payload.get("eph_pub")),
                offer_eph_pub=decode_public_key(offer) if kind is FallbackKind.REVEAL and offer is not None else None,
                devices_count=_devices_count(payload.get("devices")) if kind is FallbackKind.OFFER else None,
            )
        if kind is FallbackKind.GRANT:
            grant = b64url_decode(payload.get("grant"), max_bytes=MAX_FALLBACK_GRANT_BYTES)
            return FallbackMessage(**base, grant=grant) if grant else None
        if kind is FallbackKind.REJECT:
            reason = payload.get("reason")
            return FallbackMessage(**base, reason=reason if isinstance(reason, str) and _REASON.match(reason) else None)
    except ValidationFailedError:
        return None
    return FallbackMessage(**base)


def fallback_payload(kind: FallbackKind, request_id: str, **fields: Any) -> dict[str, Any]:
    return {"bento": kind.value, "v": FALLBACK_PROTOCOL_VERSION, "request_id": request_id, **fields}


def _devices_count(value: object) -> int | None:
    """The host's claimed number of active devices (a hint shown to the guest); anything odd is dropped."""
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_OFFERED_DEVICES:
        return None
    return value


# Service ------------------------------------------------------------------------------------------


class CommitmentVerifier(Protocol):
    """Host-side check of a revealed guest ephemeral key (`adapters.security.verify_commitment`)."""

    def __call__(self, commitment: str, *, eph_pub: bytes, device_public_key: bytes, request_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class LocalDeviceInfo:
    """How this device introduces itself to a host before it has a device row."""

    name: str
    platform: DevicePlatform
    app_version: str


@dataclass(frozen=True, slots=True)
class PairingTimeouts:
    """Seconds. Defaults follow the protocol; tests shrink them."""

    session_ttl: float = PAIRING_TTL_SECONDS
    step: float = 30.0
    login_token_wait: float = 30.0
    login_accept_attempts: int = 3
    login_poll_interval: float = 2.0
    authorization_grace: float = 30.0
    terminal_retention: float = 600.0
    request_ttl: float = FALLBACK_REQUEST_TTL_SECONDS
    fallback_poll_interval: float = 2.0
    review_wait: float = 10.0
    nameplate_attempts: int = 5
    cleanup: float = 5.0


@dataclass(frozen=True, slots=True)
class PairingView:
    """A pairing session as shown to the local UI. `telegram_login_url` is this device's own QR login link."""

    session: PairingSession
    telegram_login_url: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class PairingRequestView:
    id: str
    device_name: str
    platform: DevicePlatform
    created_at: datetime


@dataclass(frozen=True, slots=True)
class _Command:
    kind: Literal["approve", "reject", "confirm"]


@dataclass(frozen=True, slots=True)
class _Peer:
    message: PeerMessage


@dataclass(frozen=True, slots=True)
class _Closed:
    code: str


@dataclass(frozen=True, slots=True)
class _Fallback:
    message: FallbackMessage


_Event = _Command | _Peer | _Closed | _Fallback


class _Abort(Exception):
    def __init__(self, state: PairingState, code: str | None = None) -> None:
        super().__init__(state.value)
        self.state = state
        self.code = code


def _rejection(reason: str | None) -> _Abort:
    """How a guest ends when the other device refuses it."""
    if reason == DEVICE_REMOVED_REASON:
        return _Abort(PairingState.FAILED, "pairing_device_removed")
    return _Abort(PairingState.REJECTED)


@dataclass(eq=False)
class _Session:
    id: str
    role: PairingRole
    transport: PairingTransport
    state: PairingState
    expires_at: datetime
    deadline: float
    code: PairingCode | None = field(default=None, repr=False)
    peer: PairingPeer | None = None
    sas: tuple[str, ...] | None = field(default=None, repr=False)
    telegram_login_url: str | None = field(default=None, repr=False)
    error_code: str | None = None
    error_message: str | None = None
    request_id: str | None = None
    vault: PairingVaultInfo | None = None
    confirmed: bool = False
    events: asyncio.Queue[_Event] = field(default_factory=asyncio.Queue)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    pump: asyncio.Task[None] | None = None
    channel: PairingChannelPort | None = None
    cleanup_layout: VaultLayout | None = None
    cleanup_ids: set[int] = field(default_factory=set)
    finished_at: float | None = None
    started: bool = False
    cleaned: bool = False


@dataclass
class _GuestLogin:
    authorized: bool
    sent_token: bytes | None = field(default=None, repr=False)
    want_token: bool = False
    login_failed: bool = False
    grace_deadline: float | None = None


class _FallbackIndex:
    """Host-side cursor over pairing messages in the Sync channel, shared by listing and reviews."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.vault_id: str | None = None
        self.cursor: int | None = None
        self.requests: dict[str, FallbackRequest] = {}
        self.answered: set[str] = set()
        self.revealed: set[str] = set()
        """Requests whose guest already revealed its key, i.e. accepted some device's offer."""
        self.subscribers: dict[str, _Session] = {}

    def reset(self, vault_id: str) -> None:
        self.vault_id = vault_id
        self.cursor = None
        self.requests.clear()
        self.answered.clear()
        self.revealed.clear()


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PairingService:
    def __init__(
        self,
        *,
        relay: PairingRelayPort,
        crypto: PairingCryptoFactoryPort,
        vault_crypto: VaultCryptoPort,
        vault: VaultSessionPort,
        account: TelegramAccountPort,
        transport: VaultTransportPort,
        devices: DeviceRepositoryPort,
        verify_commitment: CommitmentVerifier,
        local_device: Callable[[], Awaitable[LocalDeviceInfo]] | LocalDeviceInfo,
        sync_state: SyncStateRepositoryPort | None = None,
        timeouts: PairingTimeouts | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._relay = relay
        self._crypto = crypto
        self._vault_crypto = vault_crypto
        self._vault = vault
        self._account = account
        self._transport = transport
        self._devices = devices
        self._verify_commitment = verify_commitment
        self._local_device = local_device
        self._sync_state = sync_state
        self._timeouts = timeouts or PairingTimeouts()
        self._clock = clock
        self._sessions: dict[str, _Session] = {}
        self._index = _FallbackIndex()
        self._closed = False

    def __repr__(self) -> str:
        return f"PairingService(sessions={len(self._sessions)})"

    # Host (relay) -----------------------------------------------------------------------------

    async def host(self) -> PairingView:
        """Open a relay room and show its code. Requires an unlocked vault on this device."""
        self._prune()
        context = await self._vault.require()
        self._cancel_active(PairingRole.HOST, PairingTransport.RELAY)
        channel: PairingChannelPort | None = None
        code = generate_pairing_code()
        for _ in range(max(1, self._timeouts.nameplate_attempts)):
            code = generate_pairing_code()
            try:
                channel = await self._relay.open_room(code.nameplate, PairingRole.HOST)
                break
            except PairingError as exc:
                if exc.code != "pairing_nameplate_taken":
                    raise
        if channel is None:
            raise pairing_error("pairing_relay_unavailable")
        session = self._new_session(PairingRole.HOST, PairingTransport.RELAY, self._timeouts.session_ttl, code=code)
        session.channel = channel
        self._start(session, self._host_relay(session, channel, context))
        return self._view(session)

    async def approve(self, pairing_id: str) -> PairingView:
        session = self._require_session(pairing_id)
        if session.role is not PairingRole.HOST or session.state is not PairingState.AWAITING_APPROVAL:
            raise PairingError("pairing_state_conflict", "This pairing cannot be approved now")
        self._set(session, PairingState.APPROVING)
        session.events.put_nowait(_Command("approve"))
        return self._view(session)

    async def reject(self, pairing_id: str) -> PairingView:
        session = self._require_session(pairing_id)
        if session.role is not PairingRole.HOST or session.state is not PairingState.AWAITING_APPROVAL:
            raise PairingError("pairing_state_conflict", "This pairing cannot be rejected now")
        session.events.put_nowait(_Command("reject"))
        await self._wait_for_change(session, self._timeouts.cleanup)
        return self._view(session)

    async def confirm(self, pairing_id: str) -> PairingView:
        """Guest of the Sync-channel fallback: the user saw the same emojis on the reviewing device.

        Until then the guest opens no grant; afterwards it accepts only a grant bound to the offer behind
        those emojis. Relay guests do not confirm: SPAKE2 with the out-of-band code already authenticates
        the host.
        """
        session = self._require_session(pairing_id)
        if (
            session.role is not PairingRole.GUEST
            or session.transport is not PairingTransport.TELEGRAM
            or session.state is not PairingState.AWAITING_APPROVAL
            or session.sas is None
        ):
            raise PairingError("pairing_state_conflict", "This pairing cannot be confirmed now")
        session.confirmed = True
        self._set(session, PairingState.APPROVING)
        session.events.put_nowait(_Command("confirm"))
        return self._view(session)

    async def cancel(self, pairing_id: str) -> PairingView:
        session = self._require_session(pairing_id)
        if session.state.terminal:
            return self._view(session)
        if not can_transition(session.state, PairingState.CANCELLED):
            raise PairingError("pairing_state_conflict", "This pairing can no longer be cancelled")
        self._finish(session, PairingState.CANCELLED)
        if session.task is not None:
            session.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(asyncio.shield(session.task), self._timeouts.cleanup + 1)
        return self._view(session)

    async def get(self, pairing_id: str) -> PairingView:
        return self._view(self._require_session(pairing_id))

    # Guest (relay) ----------------------------------------------------------------------------

    async def join(self, code_text: str) -> PairingView:
        """Join a host's room with a typed code or a `bento://`/`https` join link."""
        self._prune()
        code = PairingCode.parse(code_text)
        await self._require_not_paired()
        self._cancel_active(PairingRole.GUEST, None)
        channel = await self._relay.open_room(code.nameplate, PairingRole.GUEST)
        session = self._new_session(PairingRole.GUEST, PairingTransport.RELAY, self._timeouts.session_ttl)
        session.channel = channel
        self._start(session, self._guest_relay(session, channel, code))
        return self._view(session)

    # Fallback through the Sync channel ---------------------------------------------------------

    async def request_access(self) -> PairingView:
        """Guest: post a `pair_request` to the Sync channel. Requires Telegram sign-in."""
        self._prune()
        login = await self._account.status()
        if not login.authorized:
            raise TelegramAccountError("telegram_not_authorized", "Sign in to Telegram before asking for access")
        await self._require_not_paired()
        layout, header = await self._discover_layout()
        identity = await self._vault.device_identity()
        info = await self._local_info()
        keys = self._crypto.fallback_keys()
        request_id = secrets.token_hex(16)
        payload = fallback_payload(
            FallbackKind.REQUEST,
            request_id,
            device_id=identity.device_id,
            device_name=info.name,
            platform=info.platform.value,
            public_key=b64url_encode(identity.public_key),
            commitment=keys.commitment(device_public_key=identity.public_key, request_id=request_id),
        )
        self._cancel_active(PairingRole.GUEST, None)
        ref = await self._post_fallback(layout, payload)
        session = self._new_session(
            PairingRole.GUEST, PairingTransport.TELEGRAM, self._timeouts.request_ttl, request_id=request_id
        )
        session.cleanup_layout = layout
        session.cleanup_ids.add(ref.message_id)
        session.vault = PairingVaultInfo(created_at=header.created_at)
        self._start(session, self._guest_fallback(session, layout, header, keys, identity, request_id, ref.message_id))
        return self._view(session)

    async def list_requests(self) -> tuple[PairingRequestView, ...]:
        """Host: pending fallback requests from new devices (newest last)."""
        self._prune()
        context = await self._vault.require()
        await self._scan(context)
        now = self._clock()
        ttl = timedelta(seconds=self._timeouts.request_ttl)
        return tuple(
            PairingRequestView(
                id=request.request_id,
                device_name=request.device_name,
                platform=request.platform,
                created_at=request.created_at,
            )
            for request in sorted(self._index.requests.values(), key=lambda item: item.message_id)
            if request.request_id not in self._index.answered and request.created_at + ttl > now
        )

    async def review_request(self, request_id: str) -> PairingView:
        """Host: post a `pair_offer` and wait briefly for the guest's reveal so the SAS can be shown."""
        self._prune()
        context = await self._vault.require()
        await self._scan(context)
        existing = self._index.subscribers.get(request_id)
        if existing is not None and not existing.state.terminal:
            return self._view(existing)
        request = self._index.requests.get(request_id)
        if request is None or request_id in self._index.answered:
            raise PairingError("pairing_request_not_found", "Pairing request not found")
        remaining = (request.created_at + timedelta(seconds=self._timeouts.request_ttl) - self._clock()).total_seconds()
        if remaining <= 0:
            raise pairing_error("pairing_request_expired")
        try:
            await self._check_new_device(request.device_id, request.public_key, context)
        except PairingError as exc:
            if exc.code == "pairing_device_removed":
                await self._post_reject(context.layout, request_id, reason=DEVICE_REMOVED_REASON)
            raise
        keys = self._crypto.fallback_keys()
        offer_fields: dict[str, Any] = {"eph_pub": b64url_encode(keys.public_key())}
        devices_count = sum(1 for device in await self._devices.list() if device.active)
        if devices_count:
            offer_fields["devices"] = devices_count
        session = self._new_session(PairingRole.HOST, PairingTransport.TELEGRAM, remaining, request_id=request_id)
        session.peer = PairingPeer(device_name=request.device_name, platform=request.platform.value)
        self._index.subscribers[request_id] = session
        if request_id in self._index.revealed:
            # The guest already took someone else's offer and ignores later ones: say so instead of waiting.
            self._index.answered.add(request_id)
            self._finish(session, PairingState.FAILED, "pairing_request_taken")
            return self._view(session)
        try:
            offer = await self._post_fallback(
                context.layout, fallback_payload(FallbackKind.OFFER, request_id, **offer_fields)
            )
        except BaseException:
            self._finish(session, PairingState.FAILED, "pairing_internal")
            raise
        self._set(session, PairingState.CONNECTED)
        self._start(session, self._host_fallback(session, context, request, keys, offer.message_id))
        await self._wait_for_change(session, self._timeouts.review_wait)
        return self._view(session)

    async def approve_request(self, request_id: str) -> PairingView:
        return await self.approve(self._request_session(request_id).id)

    async def reject_request(self, request_id: str) -> PairingView:
        """Host: decline a fallback request (`pair_reject`), whether or not it was reviewed."""
        self._prune()
        session = self._index.subscribers.get(request_id)
        if session is not None and session.state is PairingState.AWAITING_APPROVAL:
            return await self.reject(session.id)
        context = await self._vault.require()
        request = self._index.requests.get(request_id)
        if request is None and session is None:
            raise PairingError("pairing_request_not_found", "Pairing request not found")
        await self._post_reject(context.layout, request_id)
        if session is None:
            assert request is not None
            session = self._new_session(PairingRole.HOST, PairingTransport.TELEGRAM, 0.0, request_id=request_id)
            session.peer = PairingPeer(device_name=request.device_name, platform=request.platform.value)
        if not session.state.terminal:
            self._finish(session, PairingState.REJECTED)
            if session.task is not None:
                session.task.cancel()
        return self._view(session)

    async def _post_reject(self, layout: VaultLayout, request_id: str, *, reason: str | None = None) -> None:
        """Tell the guest (best effort) and hide the request on this device."""
        self._index.answered.add(request_id)
        fields = {"reason": reason} if reason is not None else {}
        try:
            await self._post_fallback(layout, fallback_payload(FallbackKind.REJECT, request_id, **fields))
        except DomainError as exc:
            logger.warning("could not post a pairing rejection: %s", exc.code)

    async def close(self) -> None:
        """Cancel every running session (API shutdown)."""
        self._closed = True
        tasks = []
        for session in self._sessions.values():
            if not session.state.terminal:
                self._finish(session, PairingState.CANCELLED)
            if session.task is not None and not session.task.done():
                session.task.cancel()
                tasks.append(session.task)
        if tasks:
            await asyncio.wait(tasks, timeout=self._timeouts.cleanup + 1)

    # Relay flows ------------------------------------------------------------------------------

    async def _host_relay(self, session: _Session, channel: PairingChannelPort, context: VaultContext) -> None:
        if not await channel.wait_for_peer(self._remaining(session)):
            raise _Abort(PairingState.EXPIRED, "pairing_expired")
        self._set(session, PairingState.CONNECTED)
        assert session.code is not None
        crypto = self._crypto.host_session(session.code.password)
        await self._handshake(session, channel, crypto)
        session.pump = asyncio.create_task(self._pump(session, channel, crypto, PairingRole.GUEST))
        join = (await self._expect(session, self._step_deadline(session), MessageType.JOIN_REQUEST)).join
        assert join is not None
        await self._check_relay_guest(channel, crypto, join, context)
        session.peer = PairingPeer(device_name=join.device_name, platform=join.platform.value)
        self._set(session, PairingState.AWAITING_APPROVAL, sas=crypto.sas())

        token, authorized = join.login_token, join.telegram_authorized
        while True:
            event = await self._next(session, session.deadline)
            if isinstance(event, _Command):
                if event.kind == "approve":
                    break
                with contextlib.suppress(DomainError):
                    await self._send(channel, crypto, {"type": MessageType.REJECTED.value})
                raise _Abort(PairingState.REJECTED)
            message = self._peer_message(session, event)
            if message.type is MessageType.LOGIN_TOKEN:
                token = message.login_token
            elif message.type is MessageType.TELEGRAM_READY:
                authorized, token = True, None
            else:
                raise _Abort(PairingState.FAILED, "pairing_protocol")

        context = await self._vault.require()
        # Removal may have happened while the user looked at the emojis.
        await self._check_relay_guest(channel, crypto, join, context)
        authorization_hash = None
        if not authorized:
            authorization_hash = await self._authorize_guest(session, channel, crypto, token)
        context = await self._vault.require()
        sealed = self._vault_crypto.seal_for_device(
            join.public_key,
            self._vault_crypto.keyring_to_bytes(context.keyring),
            aad=context.layout.vault_id.encode("utf-8"),
        )
        await self._send(channel, crypto, vault_grant_message(context.layout, sealed))
        await self._record_device(join.device_id, join.device_name, join.platform, join.public_key, authorization_hash)
        logger.info("pairing %s granted vault access to a new device", session.id)
        while True:
            event = await self._next(session, session.deadline)
            if isinstance(event, _Command):
                continue
            message = self._peer_message(session, event, expired_state=PairingState.FAILED)
            if message.type is MessageType.DONE:
                self._finish(session, PairingState.COMPLETED)
                return
            if message.type not in {MessageType.LOGIN_TOKEN, MessageType.TELEGRAM_READY}:
                raise _Abort(PairingState.FAILED, "pairing_protocol")

    async def _check_relay_guest(
        self, channel: PairingChannelPort, crypto: PairingCryptoSessionPort, join: JoinRequest, context: VaultContext
    ) -> None:
        try:
            await self._check_new_device(join.device_id, join.public_key, context)
        except PairingError as exc:
            if exc.code == "pairing_device_removed":
                with contextlib.suppress(DomainError):
                    await self._send(channel, crypto, {"type": MessageType.REJECTED.value, "reason": DEVICE_REMOVED_REASON})
            raise

    async def _authorize_guest(
        self, session: _Session, channel: PairingChannelPort, crypto: PairingCryptoSessionPort, token: bytes | None
    ) -> int | None:
        """Sign the guest in with `auth.acceptLoginToken`; fall back to the guest's own QR."""
        reason = "expired"
        for _ in range(max(1, self._timeouts.login_accept_attempts)):
            if token is None:
                await self._send(channel, crypto, {"type": MessageType.NEED_LOGIN_TOKEN.value})
                token, ready = await self._await_login_token(session)
                if ready:
                    return None
                if token is None:
                    continue
            try:
                accepted = await self._account.accept_login_token(token)
            except DomainError as exc:
                reason = "expired" if exc.code == "telegram_login_expired" else exc.code
                if reason != "expired":
                    break
                token = None
                continue
            return accepted.authorization_hash
        logger.info("pairing %s could not accept the login token: %s", session.id, reason)
        await self._send(channel, crypto, {"type": MessageType.TELEGRAM_LOGIN_FAILED.value, "reason": reason})
        self._set(session, PairingState.NEEDS_TELEGRAM_LOGIN)
        while True:
            event = await self._next(session, session.deadline)
            if isinstance(event, _Command):
                continue
            message = self._peer_message(session, event)
            if message.type is MessageType.TELEGRAM_READY:
                self._set(session, PairingState.APPROVING)
                return None
            if message.type is not MessageType.LOGIN_TOKEN:
                raise _Abort(PairingState.FAILED, "pairing_protocol")

    async def _await_login_token(self, session: _Session) -> tuple[bytes | None, bool]:
        deadline = min(session.deadline, self._now() + self._timeouts.login_token_wait)
        while True:
            event = await self._next(session, deadline)
            if event is None:
                if self._now() >= session.deadline:
                    raise _Abort(PairingState.EXPIRED, "pairing_expired")
                return None, False
            if isinstance(event, _Command):
                continue
            message = self._peer_message(session, event)
            if message.type is MessageType.LOGIN_TOKEN:
                return message.login_token, False
            if message.type is MessageType.TELEGRAM_READY:
                return None, True
            raise _Abort(PairingState.FAILED, "pairing_protocol")

    async def _guest_relay(self, session: _Session, channel: PairingChannelPort, code: PairingCode) -> None:
        if not await channel.wait_for_peer(min(self._timeouts.step, self._remaining(session))):
            raise _Abort(PairingState.FAILED, "pairing_room_not_found")
        self._set(session, PairingState.CONNECTED)
        crypto = self._crypto.guest_session(code.password)
        await self._handshake(session, channel, crypto)
        session.pump = asyncio.create_task(self._pump(session, channel, crypto, PairingRole.HOST))
        identity = await self._vault.device_identity()
        status = await self._account.status()
        if not status.authorized:
            status = await self._account.start_qr_login()
        login = _GuestLogin(authorized=status.authorized)
        if not login.authorized:
            login.sent_token = status.qr_token
            if login.sent_token is None:
                raise _Abort(PairingState.FAILED, "telegram_login_expired")
        info = await self._local_info()
        await self._send(
            channel,
            crypto,
            join_request_message(
                identity, name=info.name, platform=info.platform, app_version=info.app_version, login_token=login.sent_token
            ),
        )
        self._set(session, PairingState.AWAITING_APPROVAL, sas=crypto.sas())

        grant: VaultGrant | None = None
        keyring: VaultKeyring | None = None
        next_poll = self._now() + self._timeouts.login_poll_interval
        while keyring is None or not login.authorized:
            wake = session.deadline if login.authorized else min(session.deadline, next_poll)
            event = await self._next(session, wake)
            if event is None:
                if self._now() >= session.deadline:
                    raise _Abort(PairingState.EXPIRED, "pairing_expired")
                await self._guest_poll(session, channel, crypto, login, grant_received=keyring is not None)
                interval = self._timeouts.login_poll_interval
                next_poll = self._now() + (min(interval, 0.5) if login.want_token else interval)
                continue
            if isinstance(event, _Command):
                continue
            message = self._peer_message(session, event)
            if message.type is MessageType.NEED_LOGIN_TOKEN:
                if login.authorized:
                    await self._send(channel, crypto, {"type": MessageType.TELEGRAM_READY.value})
                else:
                    login.want_token = True
                    next_poll = self._now()
            elif message.type is MessageType.TELEGRAM_LOGIN_FAILED:
                await self._guest_login_failed(session, channel, crypto, login)
                next_poll = self._now() + self._timeouts.login_poll_interval
            elif message.type is MessageType.REJECTED:
                raise _rejection(message.reason)
            elif message.type is MessageType.VAULT_GRANT and keyring is None:
                assert message.grant is not None
                grant = message.grant
                keyring = self._open_grant(identity, grant.sealed_keyring, grant.layout.vault_id, aad=grant.layout.vault_id)
                if session.state is not PairingState.APPROVING:
                    self._set(session, PairingState.APPROVING)
                if not login.authorized:
                    login.grace_deadline = self._now() + self._timeouts.authorization_grace
                    next_poll = self._now()
            else:
                raise _Abort(PairingState.FAILED, "pairing_protocol")

        assert grant is not None
        if session.state is not PairingState.APPROVING:
            self._set(session, PairingState.APPROVING)
        session.telegram_login_url = None
        self._set(session, PairingState.BOOTSTRAPPING)
        await self._vault.install(grant.layout, keyring)
        await self._send(channel, crypto, {"type": MessageType.DONE.value})
        self._finish(session, PairingState.COMPLETED)

    async def _guest_poll(
        self,
        session: _Session,
        channel: PairingChannelPort,
        crypto: PairingCryptoSessionPort,
        login: _GuestLogin,
        *,
        grant_received: bool,
    ) -> None:
        """Advance this device's own Telegram login while it waits for the host."""
        status = await self._account.poll_login()
        if status.authorized:
            login.authorized = True
            session.telegram_login_url = None
            if not grant_received and (login.login_failed or login.want_token):
                await self._send(channel, crypto, {"type": MessageType.TELEGRAM_READY.value})
            login.want_token = False
            if session.state is PairingState.NEEDS_TELEGRAM_LOGIN:
                self._set(session, PairingState.APPROVING)
            return
        own_qr = login.login_failed or (
            grant_received and login.grace_deadline is not None and self._now() >= login.grace_deadline
        )
        if status.step is LoginStep.PASSWORD_REQUIRED:
            # The host accepted the token but the account has a cloud password: the UI asks for it.
            session.telegram_login_url = None
            if session.state is not PairingState.NEEDS_TELEGRAM_LOGIN:
                self._set(session, PairingState.NEEDS_TELEGRAM_LOGIN)
            return
        if status.step is not LoginStep.QR_PENDING or status.qr_token is None:
            status = await self._account.start_qr_login()
            if status.qr_token is None:
                return
        if own_qr:
            session.telegram_login_url = status.qr_url
            if session.state is not PairingState.NEEDS_TELEGRAM_LOGIN:
                self._set(session, PairingState.NEEDS_TELEGRAM_LOGIN)
        elif not grant_received and status.qr_token != login.sent_token:
            assert status.qr_token is not None
            await self._send(
                channel,
                crypto,
                {"type": MessageType.LOGIN_TOKEN.value, "login_token_b64": b64url_encode(status.qr_token)},
            )
            login.sent_token = status.qr_token
            login.want_token = False

    async def _guest_login_failed(
        self, session: _Session, channel: PairingChannelPort, crypto: PairingCryptoSessionPort, login: _GuestLogin
    ) -> None:
        login.login_failed = True
        login.want_token = False
        if login.authorized:
            await self._send(channel, crypto, {"type": MessageType.TELEGRAM_READY.value})
            return
        status = await self._account.poll_login()
        if status.authorized:
            login.authorized = True
            await self._send(channel, crypto, {"type": MessageType.TELEGRAM_READY.value})
            return
        if status.step is not LoginStep.QR_PENDING:
            status = await self._account.start_qr_login()
        session.telegram_login_url = status.qr_url
        self._set(session, PairingState.NEEDS_TELEGRAM_LOGIN)

    async def _handshake(self, session: _Session, channel: PairingChannelPort, crypto: PairingCryptoSessionPort) -> None:
        """SPAKE2 then key confirmation; a mismatch aborts and burns the room."""
        await channel.send(crypto.start())
        try:
            crypto.finish(await channel.receive(self._step_remaining(session)))
        except IntegrityError:
            raise _Abort(PairingState.FAILED, "pairing_protocol") from None
        await channel.send(crypto.confirmation())
        try:
            crypto.verify_peer_confirmation(await channel.receive(self._step_remaining(session)))
        except IntegrityError:
            raise _Abort(PairingState.FAILED, "pairing_code_mismatch") from None

    async def _pump(
        self, session: _Session, channel: PairingChannelPort, crypto: PairingCryptoSessionPort, sender: PairingRole
    ) -> None:
        while True:
            try:
                frame = await channel.receive(3600.0)
            except PairingError as exc:
                if exc.code == "pairing_timeout":
                    continue
                session.events.put_nowait(_Closed(exc.code))
                return
            try:
                message = parse_peer_message(crypto.decrypt_message(frame), sender=sender)
            except (IntegrityError, PairingError, ValidationFailedError):
                session.events.put_nowait(_Closed("pairing_protocol"))
                return
            session.events.put_nowait(_Peer(message))

    async def _send(self, channel: PairingChannelPort, crypto: PairingCryptoSessionPort, message: dict[str, Any]) -> None:
        await channel.send(crypto.encrypt_message(message))

    async def _expect(self, session: _Session, deadline: float, message_type: MessageType) -> PeerMessage:
        while True:
            event = await self._next(session, deadline)
            if isinstance(event, _Command):
                continue
            if event is None and self._now() < session.deadline:
                raise _Abort(PairingState.FAILED, "pairing_timeout")
            message = self._peer_message(session, event)
            if message.type is not message_type:
                raise _Abort(PairingState.FAILED, "pairing_protocol")
            return message

    def _peer_message(
        self, session: _Session, event: _Event | None, *, expired_state: PairingState = PairingState.EXPIRED
    ) -> PeerMessage:
        if event is None:
            raise _Abort(expired_state, "pairing_expired")
        if isinstance(event, _Closed):
            if event.code == "pairing_expired":
                raise _Abort(expired_state, event.code)
            raise _Abort(PairingState.FAILED, event.code)
        if not isinstance(event, _Peer):
            raise _Abort(PairingState.FAILED, "pairing_protocol")
        return event.message

    def _open_grant(self, identity: DeviceIdentity, sealed: bytes, vault_id: str, *, aad: str) -> VaultKeyring:
        try:
            plaintext = self._vault_crypto.open_sealed(identity, sealed, aad=aad.encode("utf-8"))
            keyring = self._vault_crypto.keyring_from_bytes(plaintext)
        except (IntegrityError, ValidationFailedError):
            raise _Abort(PairingState.FAILED, "pairing_grant_invalid") from None
        if keyring.vault_id != vault_id:
            raise _Abort(PairingState.FAILED, "pairing_grant_invalid")
        return keyring

    # Fallback flows ---------------------------------------------------------------------------

    async def _guest_fallback(
        self,
        session: _Session,
        layout: VaultLayout,
        header: VaultHeader,
        keys: FallbackPairingKeysPort,
        identity: DeviceIdentity,
        request_id: str,
        request_message_id: int,
    ) -> None:
        """Take the first offer, show its emojis, and install a grant only after the user confirms them here.

        Anyone with channel access (Telegram itself, a removed device whose session is still alive) can
        answer first. The commitment stops them from choosing emojis, so their offer shows emojis that the
        reviewing device does not; the user's confirmation on this device is what rules them out.
        """
        cursor = request_message_id
        host_eph: bytes | None = None
        related: set[int] = {request_message_id}
        pending: list[bytes] = []
        while True:
            refs = await self._transport.list_sync_messages(layout, after_message_id=cursor, limit=100)
            for ref in refs:
                cursor = max(cursor, ref.message_id)
                message = await self._read_fallback(layout, ref)
                if message is None or message.request_id != request_id:
                    continue
                related.add(ref.message_id)
                if message.kind is FallbackKind.OFFER and host_eph is None:
                    assert message.eph_pub is not None
                    host_eph = message.eph_pub
                    sas = keys.sas_with(
                        host_eph,
                        request_id=request_id,
                        guest_device_public_key=identity.public_key,
                        guest_ephemeral_public_key=keys.public_key(),
                        host_ephemeral_public_key=host_eph,
                    )
                    reveal = await self._post_fallback(
                        layout,
                        fallback_payload(
                            FallbackKind.REVEAL,
                            request_id,
                            eph_pub=b64url_encode(keys.public_key()),
                            offer=b64url_encode(host_eph),
                        ),
                    )
                    session.cleanup_ids.add(reveal.message_id)
                    related.add(reveal.message_id)
                    session.vault = replace(session.vault or PairingVaultInfo(), devices_count=message.devices_count)
                    self._set(session, PairingState.CONNECTED)
                    self._set(session, PairingState.AWAITING_APPROVAL, sas=sas)
                elif message.kind is FallbackKind.GRANT and host_eph is not None:
                    # Kept unopened until the user confirms the emojis of the offer we answered.
                    assert message.grant is not None
                    if len(pending) < MAX_PENDING_GRANTS:
                        pending.append(message.grant)
                elif message.kind is FallbackKind.REJECT:
                    raise _rejection(message.reason)
            if session.confirmed and host_eph is not None:
                while pending:
                    keyring = self._accept_fallback_grant(session, layout, keys, identity, host_eph, pending.pop(0))
                    if keyring is None:
                        continue
                    await self._verify_granted_keyring(layout, header, keyring)
                    self._set(session, PairingState.BOOTSTRAPPING)
                    session.cleanup_ids |= related
                    await self._vault.install(layout, keyring)
                    await self._delete_fallback_messages(session)
                    self._finish(session, PairingState.COMPLETED)
                    return
            if len(refs) >= 100:
                continue
            event = await self._next(session, min(session.deadline, self._now() + self._timeouts.fallback_poll_interval))
            if event is None and self._now() >= session.deadline:
                raise _Abort(PairingState.EXPIRED, "pairing_request_expired")

    def _accept_fallback_grant(
        self,
        session: _Session,
        layout: VaultLayout,
        keys: FallbackPairingKeysPort,
        identity: DeviceIdentity,
        host_eph: bytes,
        grant: bytes,
    ) -> VaultKeyring | None:
        """The keyring in a grant made by the confirmed offer's host, or None for anyone else's grant."""
        assert session.request_id is not None
        request_id = session.request_id
        try:
            sealed = keys.open_grant(
                host_eph,
                grant,
                request_id=request_id,
                guest_device_public_key=identity.public_key,
                guest_ephemeral_public_key=keys.public_key(),
                host_ephemeral_public_key=host_eph,
            )
        except IntegrityError:
            # Anyone with channel access can post a grant: ignore it and keep waiting.
            logger.warning("pairing %s ignored a grant from someone other than the confirmed device", session.id)
            return None
        return self._open_grant(identity, sealed, layout.vault_id, aad=request_id)

    async def _verify_granted_keyring(self, layout: VaultLayout, shown: VaultHeader, keyring: VaultKeyring) -> None:
        """Defence in depth: the granted keyring must MAC the pinned header of the vault the user was shown.

        Only at the keyring's current epoch (architecture § Header): a removed device keeps older epochs and can
        MAC and pin an older header, so an older-epoch header proves nothing about the grant.
        """
        text = await self._transport.read_header_text(layout)  # None when the pinned header was edited
        if text is None:
            raise _Abort(PairingState.FAILED, "pairing_grant_invalid")
        try:
            header = VaultHeader.from_json(text)
        except ValidationFailedError:
            raise _Abort(PairingState.FAILED, "pairing_grant_invalid") from None
        valid = (
            header.vault_id == layout.vault_id
            and header.layout == layout
            and header.created_at == shown.created_at
            and header.current_epoch == keyring.current_epoch
            and self._vault_crypto.verify_header_mac(keyring, header.canonical_unsigned_bytes(), header.mac)
        )
        if not valid:
            raise _Abort(PairingState.FAILED, "pairing_grant_invalid")

    async def _host_fallback(
        self,
        session: _Session,
        context: VaultContext,
        request: FallbackRequest,
        keys: FallbackPairingKeysPort,
        offer_message_id: int,
    ) -> None:
        host_eph = keys.public_key()
        guest_eph = b""
        while session.sas is None:
            event = await self._next(session, min(session.deadline, self._now() + self._timeouts.fallback_poll_interval))
            if event is None:
                if self._now() >= session.deadline:
                    raise _Abort(PairingState.EXPIRED, "pairing_request_expired")
                await self._scan(context)
                continue
            if not isinstance(event, _Fallback):
                continue
            message = event.message
            if message.kind in {FallbackKind.GRANT, FallbackKind.REJECT}:
                raise self._request_taken(request.request_id)
            if message.kind is not FallbackKind.REVEAL:
                continue
            assert message.eph_pub is not None
            # A reveal older than our offer, or naming another offer, answers someone else's offer.
            if message.message_id < offer_message_id or (
                message.offer_eph_pub is not None and message.offer_eph_pub != host_eph
            ):
                raise self._request_taken(request.request_id)
            if not self._verify_commitment(
                request.commitment,
                eph_pub=message.eph_pub,
                device_public_key=request.public_key,
                request_id=request.request_id,
            ):
                raise _Abort(PairingState.FAILED, "pairing_commitment_mismatch")
            guest_eph = message.eph_pub
            sas = keys.sas_with(
                guest_eph,
                request_id=request.request_id,
                guest_device_public_key=request.public_key,
                guest_ephemeral_public_key=guest_eph,
                host_ephemeral_public_key=host_eph,
            )
            self._set(session, PairingState.AWAITING_APPROVAL, sas=sas)

        while True:
            event = await self._next(session, session.deadline)
            if event is None:
                raise _Abort(PairingState.EXPIRED, "pairing_request_expired")
            if isinstance(event, _Fallback):
                if event.message.kind in {FallbackKind.GRANT, FallbackKind.REJECT}:
                    raise self._request_taken(request.request_id)
                continue
            if not isinstance(event, _Command):
                continue
            if event.kind == "reject":
                await self._post_reject(context.layout, request.request_id)
                raise _Abort(PairingState.REJECTED)
            context = await self._vault.require()
            try:
                await self._check_new_device(request.device_id, request.public_key, context)
            except PairingError as exc:
                if exc.code == "pairing_device_removed":
                    await self._post_reject(context.layout, request.request_id, reason=DEVICE_REMOVED_REASON)
                raise
            sealed = self._vault_crypto.seal_for_device(
                request.public_key,
                self._vault_crypto.keyring_to_bytes(context.keyring),
                aad=request.request_id.encode("utf-8"),
            )
            # Sealed to the device key and authenticated by the exchange whose SAS the user just compared.
            grant = keys.seal_grant(
                guest_eph,
                sealed,
                request_id=request.request_id,
                guest_device_public_key=request.public_key,
                guest_ephemeral_public_key=guest_eph,
                host_ephemeral_public_key=host_eph,
            )
            await self._post_fallback(
                context.layout, fallback_payload(FallbackKind.GRANT, request.request_id, grant=b64url_encode(grant))
            )
            self._index.answered.add(request.request_id)
            await self._record_device(request.device_id, request.device_name, request.platform, request.public_key, None)
            logger.info("pairing %s granted vault access through the Sync channel", session.id)
            self._finish(session, PairingState.COMPLETED)
            return

    def _request_taken(self, request_id: str) -> _Abort:
        """Another device (maybe not the user's) answered first: stop listing the request and say so here."""
        self._index.answered.add(request_id)
        return _Abort(PairingState.FAILED, "pairing_request_taken")

    async def _scan(self, context: VaultContext) -> None:
        """Advance the host cursor over pairing messages, indexing requests and notifying reviews."""
        layout = context.layout
        async with self._index.lock:
            if self._index.vault_id != layout.vault_id:
                self._index.reset(layout.vault_id)
            if self._index.cursor is None:
                self._index.cursor = await self._initial_cursor(layout)
            for _ in range(50):
                refs = await self._transport.list_sync_messages(layout, after_message_id=self._index.cursor, limit=100)
                for ref in refs:
                    self._index.cursor = max(self._index.cursor, ref.message_id)
                    message = await self._read_fallback(layout, ref)
                    if message is not None:
                        self._index_message(message, own_device_id=context.device.device_id)
                if len(refs) < 100:
                    break

    def _index_message(self, message: FallbackMessage, *, own_device_id: str) -> None:
        index = self._index
        if message.kind is FallbackKind.REQUEST:
            request = message.request
            if request is not None and request.device_id != own_device_id and request.request_id not in index.requests:
                index.requests[request.request_id] = request
            return
        if message.kind in {FallbackKind.GRANT, FallbackKind.REJECT}:
            index.answered.add(message.request_id)
        elif message.kind is FallbackKind.REVEAL:
            index.revealed.add(message.request_id)
        subscriber = index.subscribers.get(message.request_id)
        if subscriber is not None and not subscriber.state.terminal:
            subscriber.events.put_nowait(_Fallback(message))

    async def _initial_cursor(self, layout: VaultLayout) -> int:
        """Largest message id older than the request TTL: galloping then binary search on message dates."""
        since = self._clock() - timedelta(seconds=self._timeouts.request_ttl + 60)

        async def first_after(message_id: int) -> SyncMessageRef | None:
            refs = await self._transport.list_sync_messages(layout, after_message_id=message_id, limit=1)
            return refs[0] if refs else None

        first = await first_after(0)
        if first is None or first.created_at >= since:
            return 0
        low, step, high = first.message_id, 64, None
        while high is None:
            probe = await first_after(low + step)
            if probe is None or probe.created_at >= since:
                high = low + step
            else:
                low, step = probe.message_id, step * 2
        while high - low > 1:
            middle = (low + high) // 2
            probe = await first_after(middle)
            if probe is None or probe.created_at >= since or probe.message_id > high:
                high = middle
            else:
                low = probe.message_id
        return low

    async def _read_fallback(self, layout: VaultLayout, ref: SyncMessageRef) -> FallbackMessage | None:
        if ref.kind is not SyncMessageKind.PAIRING:
            return None
        if ref.edited:
            # Bento never edits pairing messages; an edited one may say anything (an offer swapped for another).
            logger.warning("Integrity: ignored the edited pairing message %s", ref.message_id)
            return None
        text = ref.text
        if text is None:
            if not ref.filename.endswith(SyncMessageKind.PAIRING.suffix):
                return None
            if not 0 < ref.size_bytes <= MAX_FALLBACK_MESSAGE_BYTES:
                return None
            try:
                text = (await self._transport.download_sync_document(layout, ref.message_id)).decode("utf-8")
            except (DomainError, UnicodeDecodeError):
                return None
        return parse_fallback_message(text, message_id=ref.message_id, created_at=ref.created_at)

    async def _post_fallback(self, layout: VaultLayout, payload: dict[str, Any]) -> SyncMessageRef:
        text = canonical_json(payload).decode("utf-8")
        if len(text) <= MAX_FALLBACK_TEXT_CHARS:
            return await self._transport.post_sync_text(layout, SyncMessageKind.PAIRING, text)
        return await self._transport.post_sync_document(layout, SyncMessageKind.PAIRING, text.encode("utf-8"))

    async def _discover_layout(self) -> tuple[VaultLayout, VaultHeader]:
        """The only vault of this account with a readable header. Several vaults are never chosen between:
        whoever can create channels in the account (Telegram itself) could otherwise steer the new device."""
        candidates: list[tuple[VaultLayout, VaultHeader]] = []
        for layout in await self._transport.find_vaults():
            text = await self._transport.read_header_text(layout)
            try:
                header = VaultHeader.from_json(text) if text is not None else None
            except ValidationFailedError:
                header = None
            # Same rules as `VaultService` discovery: the parser refuses naive timestamps, `created_at` orders
            # nothing, and the header must name the layout it is pinned in.
            if header is not None and header.vault_id == layout.vault_id and header.layout == layout:
                candidates.append((layout, header))
        if not candidates:
            raise VaultNotFoundError()
        if len(candidates) > 1:
            raise pairing_error("pairing_vault_ambiguous")
        return candidates[0]

    # Shared helpers ---------------------------------------------------------------------------

    async def _check_new_device(self, device_id: str, public_key: bytes, context: VaultContext) -> None:
        """A guest may not impersonate this device or an active device with another key, nor reuse a removed id."""
        if device_id == context.device.device_id:
            raise pairing_error("pairing_protocol")
        existing = await self._devices.get(device_id)
        if existing is not None and existing.active and existing.public_key != b64url_encode(public_key):
            raise pairing_error("pairing_protocol")
        await self._refuse_removed_device(device_id, existing)

    async def _refuse_removed_device(self, device_id: str, existing: Device | None) -> None:
        """Removal is final for a device id: re-adding it would revive the grants and access other devices
        already refuse. The guest has to join with a new identity, i.e. a new id."""
        if existing is not None and not existing.active:
            raise pairing_error("pairing_device_removed")
        if device_id in await self._remembered_removed_device_ids():
            raise pairing_error("pairing_device_removed")

    async def _remembered_removed_device_ids(self) -> frozenset[str]:
        """Ids listed as removed by accepted keys messages (`sync_state`), even without a registry row."""
        if self._sync_state is None:
            return frozenset()
        from bento.application.sync.state import REMOVED_DEVICES  # the sync package imports this module

        raw = await self._sync_state.get_value(REMOVED_DEVICES)
        try:
            stored = json.loads(raw) if raw else []
        except ValueError:
            return frozenset()
        return frozenset(item for item in stored if isinstance(item, str)) if isinstance(stored, list) else frozenset()

    async def _record_device(
        self,
        device_id: str,
        name: str,
        platform: DevicePlatform,
        public_key: bytes,
        authorization_hash: int | None,
    ) -> None:
        existing = await self._devices.get(device_id)
        # Never clears `removed_at`: checked before every grant, and again here.
        await self._refuse_removed_device(device_id, existing)
        now = self._clock()
        await self._devices.save(
            Device(
                id=device_id,
                name=name,
                platform=platform,
                public_key=b64url_encode(public_key),
                added_at=now,
                telegram_auth_hash=authorization_hash
                if authorization_hash is not None
                else (existing.telegram_auth_hash if existing is not None else None),
                last_seen_at=now,
                removed_at=None,
                current=False,
            )
        )

    async def _require_not_paired(self) -> VaultStatus:
        status = await self._vault.status()
        if status.state in {VaultState.READY, VaultState.BOOTSTRAPPING}:
            raise PairingError("pairing_already_paired", "This device already has access to the vault")
        return status

    async def _local_info(self) -> LocalDeviceInfo:
        info = self._local_device if isinstance(self._local_device, LocalDeviceInfo) else await self._local_device()
        for device in await self._devices.list():
            if device.current:
                return LocalDeviceInfo(name=device.name, platform=device.platform, app_version=info.app_version)
        return info

    def _new_session(
        self,
        role: PairingRole,
        transport: PairingTransport,
        ttl_seconds: float,
        *,
        code: PairingCode | None = None,
        request_id: str | None = None,
    ) -> _Session:
        session = _Session(
            id=f"pair_{uuid.uuid4().hex}",
            role=role,
            transport=transport,
            state=PairingState.WAITING,
            expires_at=self._clock() + timedelta(seconds=ttl_seconds),
            deadline=self._now() + ttl_seconds,
            code=code,
            request_id=request_id,
        )
        self._sessions[session.id] = session
        return session

    def _start(self, session: _Session, flow: Coroutine[Any, Any, None]) -> None:
        session.task = asyncio.create_task(self._run(session, flow), name=f"pairing-{session.role.value}")
        session.task.add_done_callback(lambda _task: self._after_task(session, flow))

    def _after_task(self, session: _Session, flow: Coroutine[Any, Any, None]) -> None:
        """A task cancelled before its first step never ran `_run`: close the flow and clean up here."""
        if session.started:
            return
        flow.close()
        self._finish(session, PairingState.CANCELLED)
        if not session.cleaned and not self._closed:
            with contextlib.suppress(RuntimeError):
                asyncio.get_running_loop().create_task(self._cleanup(session))

    async def _run(self, session: _Session, flow: Coroutine[Any, Any, None]) -> None:
        """Run a flow; cleanup (channel close, Sync message deletion) happens before the final state is shown."""
        session.started = True
        outcome: tuple[PairingState, str | None, str | None] | None = None
        try:
            await flow
        except _Abort as abort:
            outcome = (abort.state, abort.code, None)
        except asyncio.CancelledError:
            outcome = (PairingState.CANCELLED, None, None)
        except PairingError as exc:
            expired = exc.code in {"pairing_expired", "pairing_request_expired"}
            outcome = (PairingState.EXPIRED if expired else PairingState.FAILED, exc.code, exc.message)
        except DomainError as exc:
            outcome = (PairingState.FAILED, exc.code, exc.message)
        except Exception:
            logger.exception("pairing %s failed unexpectedly", session.id)
            outcome = (PairingState.FAILED, "pairing_internal", None)
        finally:
            try:
                await self._cleanup(session)
            finally:
                if outcome is not None:
                    self._finish(session, *outcome)
                elif not session.state.terminal:
                    self._finish(session, PairingState.FAILED, "pairing_internal")

    async def _cleanup(self, session: _Session) -> None:
        if session.pump is not None:
            session.pump.cancel()
        if session.channel is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(session.channel.close(), self._timeouts.cleanup)
        await self._delete_fallback_messages(session)
        session.cleaned = True

    async def _delete_fallback_messages(self, session: _Session) -> None:
        """The guest removes its pairing messages (and, once paired, the whole exchange) from the Sync channel."""
        if session.cleanup_layout is None or not session.cleanup_ids:
            return
        ids = tuple(sorted(session.cleanup_ids))
        session.cleanup_ids.clear()
        try:
            await asyncio.wait_for(self._transport.delete_sync_messages(session.cleanup_layout, ids), self._timeouts.cleanup)
        except Exception:
            logger.warning("pairing %s could not delete its Sync messages", session.id)

    def _set(self, session: _Session, state: PairingState, *, sas: tuple[str, ...] | None = None) -> None:
        if session.state.terminal:
            raise _Abort(session.state, session.error_code)
        if not can_transition(session.state, state):
            logger.error("pairing %s: invalid transition %s -> %s", session.id, session.state.value, state.value)
            raise _Abort(PairingState.FAILED, "pairing_internal")
        logger.info("pairing %s: %s -> %s", session.id, session.state.value, state.value)
        session.state = state
        if sas is not None:
            session.sas = tuple(sas)
        self._notify(session)

    def _finish(self, session: _Session, state: PairingState, code: str | None = None, message: str | None = None) -> None:
        if session.state.terminal:
            return
        if not can_transition(session.state, state):
            state, code = PairingState.FAILED, code or "pairing_internal"
        logger.info("pairing %s: %s -> %s%s", session.id, session.state.value, state.value, f" ({code})" if code else "")
        session.state = state
        if state is not PairingState.COMPLETED and code is not None:
            session.error_code = code
            session.error_message = message or _ERROR_MESSAGES.get(code, "Pairing failed")
        session.telegram_login_url = None
        session.finished_at = self._now()
        self._notify(session)

    def _notify(self, session: _Session) -> None:
        session.changed.set()
        session.changed = asyncio.Event()

    async def _wait_for_change(self, session: _Session, timeout: float) -> None:
        changed = session.changed
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(changed.wait(), max(0.0, timeout))

    async def _next(self, session: _Session, deadline: float) -> _Event | None:
        remaining = deadline - self._now()
        if remaining <= 0:
            return None
        try:
            return await asyncio.wait_for(session.events.get(), remaining)
        except TimeoutError:
            return None

    def _view(self, session: _Session) -> PairingView:
        show_code = (
            session.role is PairingRole.HOST and session.transport is PairingTransport.RELAY and not session.state.terminal
        )
        login_url = session.telegram_login_url if session.state is PairingState.NEEDS_TELEGRAM_LOGIN else None
        return PairingView(
            session=PairingSession(
                id=session.id,
                role=session.role,
                transport=session.transport,
                state=session.state,
                expires_at=session.expires_at,
                code=session.code if show_code else None,
                peer=session.peer,
                sas=session.sas if session.state in _SAS_STATES else None,
                needs_telegram_qr=login_url is not None,
                error_code=session.error_code,
                vault=session.vault,
            ),
            telegram_login_url=login_url,
            error_message=session.error_message,
        )

    def _require_session(self, pairing_id: str) -> _Session:
        self._prune()
        session = self._sessions.get(pairing_id)
        if session is None:
            raise PairingError("pairing_not_found", "Pairing not found")
        return session

    def _request_session(self, request_id: str) -> _Session:
        session = self._index.subscribers.get(request_id)
        if session is None:
            raise PairingError("pairing_not_found", "Review this request first")
        return session

    def _cancel_active(self, role: PairingRole, transport: PairingTransport | None) -> None:
        for session in list(self._sessions.values()):
            if session.role is not role or (transport is not None and session.transport is not transport):
                continue
            if session.state.terminal or not can_transition(session.state, PairingState.CANCELLED):
                continue
            if session.transport is PairingTransport.TELEGRAM and session.role is PairingRole.HOST:
                continue
            self._finish(session, PairingState.CANCELLED)
            if session.task is not None:
                session.task.cancel()

    def _prune(self) -> None:
        now = self._now()
        for session_id, session in list(self._sessions.items()):
            if session.finished_at is not None and now - session.finished_at > self._timeouts.terminal_retention:
                del self._sessions[session_id]
                if session.request_id is not None and self._index.subscribers.get(session.request_id) is session:
                    del self._index.subscribers[session.request_id]
        cutoff = self._clock() - timedelta(seconds=self._timeouts.request_ttl)
        for request_id, request in list(self._index.requests.items()):
            if request.created_at < cutoff and request_id not in self._index.subscribers:
                del self._index.requests[request_id]
                self._index.answered.discard(request_id)
                self._index.revealed.discard(request_id)

    def _remaining(self, session: _Session) -> float:
        return max(0.0, session.deadline - self._now())

    def _step_remaining(self, session: _Session) -> float:
        return min(self._timeouts.step, self._remaining(session))

    def _step_deadline(self, session: _Session) -> float:
        return min(session.deadline, self._now() + self._timeouts.step)

    @staticmethod
    def _now() -> float:
        return asyncio.get_running_loop().time()


_SAS_STATES = frozenset(
    {
        PairingState.AWAITING_APPROVAL,
        PairingState.APPROVING,
        PairingState.NEEDS_TELEGRAM_LOGIN,
        PairingState.BOOTSTRAPPING,
    }
)
