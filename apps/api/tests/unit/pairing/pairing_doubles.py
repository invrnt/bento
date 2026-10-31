"""In-memory doubles for `PairingService` unit tests (no SQLite, Telegram, network, or filesystem)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from bento.adapters.security import PairingCryptoFactory, VaultCrypto, verify_commitment
from bento.application.pairing import LocalDeviceInfo, PairingService, PairingTimeouts
from bento.domain.account import AcceptedLogin, AccountStatus, LoginStep, TelegramAccount, TelegramAuthorization
from bento.domain.devices import Device, DevicePlatform
from bento.domain.errors import TelegramAccountError, VaultLockedError
from bento.domain.pairing import PairingError, PairingRole
from bento.domain.security import DeviceIdentity, VaultKeyring
from bento.domain.sync import SyncMessageKind, SyncMessageRef
from bento.domain.vault import VaultHeader, VaultLayout, VaultState, VaultStatus
from bento.ports.vault import VaultContext

LAYOUT = VaultLayout(vault_id="vlt_unit", files_channel_id=-1001, sync_channel_id=-1002, inbox_channel_id=-1003)
ACCOUNT = TelegramAccount(user_id=1, display_name="Ana")
UNIT = PairingTimeouts(
    session_ttl=10.0,
    step=1.0,
    login_token_wait=1.0,
    login_poll_interval=0.02,
    authorization_grace=0.5,
    terminal_retention=60.0,
    fallback_poll_interval=0.02,
    review_wait=1.0,
    cleanup=0.5,
)


class MemoryChannel:
    def __init__(self, room: MemoryRoom, role: PairingRole) -> None:
        self.room = room
        self.role = role
        self.inbox: asyncio.Queue[bytes | str] = asyncio.Queue()
        self.sent: list[bytes] = []
        self.closed = False

    async def wait_for_peer(self, timeout_seconds: float) -> bool:
        try:
            await asyncio.wait_for(self.room.joined.wait(), timeout_seconds)
        except TimeoutError:
            return False
        return True

    async def send(self, frame: bytes) -> None:
        if self.closed or self.room.burned:
            raise PairingError("pairing_peer_left", "peer left")
        peer = self.room.peer(self.role)
        assert peer is not None
        self.sent.append(frame)
        peer.inbox.put_nowait(frame)

    async def receive(self, timeout_seconds: float) -> bytes:
        try:
            item = await asyncio.wait_for(self.inbox.get(), timeout_seconds)
        except TimeoutError:
            raise PairingError("pairing_timeout", "timeout") from None
        if isinstance(item, str):
            self.inbox.put_nowait(item)
            raise PairingError(item, item)
        return item

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if not self.room.burned:
            self.room.burned = True
            peer = self.room.peer(self.role)
            if peer is not None:
                peer.inbox.put_nowait("pairing_peer_left")


@dataclass
class MemoryRoom:
    host: MemoryChannel | None = None
    guest: MemoryChannel | None = None
    joined: asyncio.Event = field(default_factory=asyncio.Event)
    burned: bool = False

    def peer(self, role: PairingRole) -> MemoryChannel | None:
        return self.guest if role is PairingRole.HOST else self.host


class MemoryRelay:
    def __init__(self, *, taken: int = 0) -> None:
        self.rooms: dict[str, MemoryRoom] = {}
        self.taken = taken
        self.opened: list[tuple[str, PairingRole]] = []

    async def available(self) -> bool:
        return True

    async def open_room(self, nameplate: str, role: PairingRole) -> MemoryChannel:
        self.opened.append((nameplate, role))
        if role is PairingRole.HOST:
            if self.taken > 0 or nameplate in self.rooms:
                self.taken -= 1
                raise PairingError("pairing_nameplate_taken", "taken")
            room = MemoryRoom()
            room.host = MemoryChannel(room, role)
            self.rooms[nameplate] = room
            return room.host
        room = self.rooms.get(nameplate)
        if room is None or (room.burned and room.guest is None):
            raise PairingError("pairing_room_not_found", "missing")
        if room.guest is not None:
            raise PairingError("pairing_room_full", "full")
        room.guest = MemoryChannel(room, role)
        room.joined.set()
        return room.guest


class StubAccount:
    def __init__(self, *, authorized: bool = True) -> None:
        self.authorized = authorized
        self.token_counter = 0
        self.accepted: list[bytes] = []
        self.accept_error: TelegramAccountError | None = None
        self.on_accept: Callable[[bytes], None] | None = None

    def _qr(self) -> AccountStatus:
        token = f"token-{self.token_counter}".encode()
        return AccountStatus(step=LoginStep.QR_PENDING, qr_url=f"tg://login?token={token.decode()}", qr_token=token)

    async def status(self) -> AccountStatus:
        return AccountStatus(step=LoginStep.AUTHORIZED, account=ACCOUNT) if self.authorized else AccountStatus(step=LoginStep.SIGNED_OUT)

    async def start_qr_login(self) -> AccountStatus:
        return await self.poll_login()

    async def poll_login(self) -> AccountStatus:
        return await self.status() if self.authorized else self._qr()

    def rotate_token(self) -> None:
        """What Telegram does when a QR login token expires: the next poll shows a new one."""
        self.token_counter += 1

    async def accept_login_token(self, token: bytes) -> AcceptedLogin:
        self.accepted.append(token)
        if self.on_accept is not None:
            self.on_accept(token)
        if self.accept_error is not None:
            raise self.accept_error
        return AcceptedLogin(authorization_hash=4242)

    async def list_authorizations(self) -> tuple[TelegramAuthorization, ...]:
        return ()


class MemoryTransport:
    def __init__(self) -> None:
        self.messages: list[SyncMessageRef] = []
        self.documents: dict[int, bytes] = {}
        self.header_text: str | None = None
        self.deleted: list[int] = []

    async def find_vaults(self) -> tuple[VaultLayout, ...]:
        return (LAYOUT,)

    async def read_header_text(self, layout: VaultLayout) -> str | None:
        return self.header_text

    async def post_sync_text(self, layout: VaultLayout, kind: SyncMessageKind, text: str) -> SyncMessageRef:
        ref = SyncMessageRef(len(self.messages) + 1, kind, "", len(text), datetime.now(UTC), text=text)
        self.messages.append(ref)
        return ref

    async def post_sync_document(self, layout: VaultLayout, kind: SyncMessageKind, payload: bytes) -> SyncMessageRef:
        ref = SyncMessageRef(len(self.messages) + 1, kind, f"doc{kind.suffix}", len(payload), datetime.now(UTC))
        self.messages.append(ref)
        self.documents[ref.message_id] = payload
        return ref

    async def list_sync_messages(self, layout: VaultLayout, *, after_message_id: int, limit: int = 100) -> tuple[SyncMessageRef, ...]:
        return tuple(ref for ref in self.messages if ref.message_id > after_message_id and ref.message_id not in self.deleted)[:limit]

    async def download_sync_document(self, layout: VaultLayout, message_id: int) -> bytes:
        return self.documents[message_id]

    async def delete_sync_messages(self, layout: VaultLayout, message_ids: tuple[int, ...]) -> None:
        self.deleted.extend(message_ids)


class MemoryDevices:
    def __init__(self) -> None:
        self.items: dict[str, Device] = {}

    async def list(self, *, include_removed: bool = False) -> tuple[Device, ...]:
        return tuple(item for item in self.items.values() if include_removed or item.active)

    async def get(self, device_id: str) -> Device | None:
        return self.items.get(device_id)

    async def save(self, device: Device) -> None:
        self.items[device.id] = device


class MemoryVault:
    def __init__(self, crypto: VaultCrypto, *, keyring: VaultKeyring | None = None, authorized: Callable[[], bool] = lambda: True) -> None:
        self.crypto = crypto
        self.keyring = keyring
        self.identity: DeviceIdentity = crypto.generate_device_identity()
        self.installed: list[tuple[VaultLayout, VaultKeyring]] = []
        self.install_gate: asyncio.Event | None = None
        self._authorized = authorized

    async def status(self) -> VaultStatus:
        if self.keyring is not None:
            return VaultStatus(state=VaultState.READY, vault_id=LAYOUT.vault_id)
        return VaultStatus(state=VaultState.LOCKED, vault_id=LAYOUT.vault_id)

    async def current(self) -> VaultContext | None:
        if self.keyring is None:
            return None
        return VaultContext(layout=LAYOUT, keyring=self.keyring, device=self.identity, account=ACCOUNT)

    async def require(self) -> VaultContext:
        context = await self.current()
        if context is None:
            raise VaultLockedError()
        return context

    async def device_identity(self) -> DeviceIdentity:
        return self.identity

    async def install(self, layout: VaultLayout, keyring: VaultKeyring) -> VaultStatus:
        if self.install_gate is not None:
            await self.install_gate.wait()
        if not self._authorized():
            raise TelegramAccountError("telegram_not_authorized", "not signed in")
        self.keyring = keyring
        self.installed.append((layout, keyring))
        return VaultStatus(state=VaultState.BOOTSTRAPPING, vault_id=layout.vault_id)

    async def update_keyring(self, keyring: VaultKeyring) -> None:
        self.keyring = keyring

    async def read_header(self) -> VaultHeader | None:
        return None

    async def update_header(self, mutate: Callable[[VaultHeader], VaultHeader]) -> VaultHeader:
        raise NotImplementedError


@dataclass
class UnitDevice:
    vault: MemoryVault
    account: StubAccount
    transport: MemoryTransport
    devices: MemoryDevices
    service: PairingService


def make_unit_device(
    relay: MemoryRelay,
    *,
    crypto: VaultCrypto,
    keyring: VaultKeyring | None,
    authorized: bool = True,
    transport: MemoryTransport | None = None,
    timeouts: PairingTimeouts = UNIT,
    name: str = "Equipo · Linux",
) -> UnitDevice:
    account = StubAccount(authorized=authorized)
    vault = MemoryVault(crypto, keyring=keyring, authorized=lambda: account.authorized)
    shared = transport or MemoryTransport()
    devices = MemoryDevices()
    service = PairingService(
        relay=relay,
        crypto=PairingCryptoFactory(),
        vault_crypto=crypto,
        vault=vault,
        account=account,  # type: ignore[arg-type]
        transport=shared,  # type: ignore[arg-type]
        devices=devices,
        verify_commitment=verify_commitment,
        local_device=LocalDeviceInfo(name=name, platform=DevicePlatform.LINUX, app_version="0.1.0"),
        timeouts=timeouts,
    )
    return UnitDevice(vault=vault, account=account, transport=shared, devices=devices, service=service)


def with_timeouts(base: PairingTimeouts, **changes: Any) -> PairingTimeouts:
    return replace(base, **changes)
