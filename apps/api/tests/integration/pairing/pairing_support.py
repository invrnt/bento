"""Test doubles for pairing: a `VaultSessionPort` over the fake Telegram cloud and a two-device builder.

The real `VaultSessionPort` is implemented by the mtproto agent; this double follows the port contract
(`ports/vault.py`) with `VaultCrypto`, `InMemoryKeyStore`, and `SQLiteDeviceRepository`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from bento.adapters.fake_telegram import FAKE_LOGIN_CODE, FakeTelegramCloud, FakeTelegramOptions
from bento.adapters.pairing import WebSocketPairingRelay
from bento.adapters.repositories.devices import SQLiteDeviceRepository
from bento.adapters.security import InMemoryKeyStore, PairingCryptoFactory, VaultCrypto, verify_commitment
from bento.application.devices import DeviceService, telegram_device_model
from bento.application.pairing import (
    LocalDeviceInfo,
    PairingService,
    PairingTimeouts,
    PairingView,
    b64url_encode,
)
from bento.domain.account import AcceptedLogin
from bento.domain.devices import Device, DevicePlatform
from bento.domain.errors import TelegramAccountError, VaultLockedError, VaultNotFoundError
from bento.domain.pairing import PairingState
from bento.domain.security import DeviceIdentity, VaultKeyring
from bento.domain.vault import VaultHeader, VaultLayout, VaultState, VaultStatus
from bento.infrastructure.runtime import TelegramRuntime, create_fake_telegram_runtime
from bento.ports.key_store import DEVICE_IDENTITY, VAULT_KEYRING
from bento.ports.vault import VaultContext
from tests.integration.db.support import migrated_session_factory

T = TypeVar("T")
VAULT_ID = "vlt_pairingtest"
FAST = PairingTimeouts(
    step=5.0,
    login_token_wait=5.0,
    login_poll_interval=0.05,
    authorization_grace=2.0,
    fallback_poll_interval=0.05,
    review_wait=3.0,
    cleanup=2.0,
)


class FakeVaultSession:
    """`VaultSessionPort` double: keyring and layout live in memory/key store, header in the fake Sync channel."""

    def __init__(
        self,
        runtime: TelegramRuntime,
        key_store: InMemoryKeyStore,
        crypto: VaultCrypto,
        devices: SQLiteDeviceRepository,
        *,
        name: str,
        platform: DevicePlatform = DevicePlatform.LINUX,
    ) -> None:
        self.runtime = runtime
        self.key_store = key_store
        self.crypto = crypto
        self.devices = devices
        self.name = name
        self.platform = platform
        self.layout: VaultLayout | None = None
        self.installs: list[tuple[VaultLayout, VaultKeyring]] = []

    async def status(self) -> VaultStatus:
        if not (await self.runtime.account.status()).authorized:
            return VaultStatus(state=VaultState.SIGNED_OUT)
        keyring = await self._keyring()
        if keyring is not None and self.layout is not None:
            return VaultStatus(state=VaultState.READY, vault_id=self.layout.vault_id)
        layouts = await self.runtime.transport.find_vaults()
        if not layouts:
            return VaultStatus(state=VaultState.NO_VAULT)
        return VaultStatus(state=VaultState.LOCKED, vault_id=layouts[0].vault_id)

    async def current(self) -> VaultContext | None:
        account = await self.runtime.account.status()
        keyring = await self._keyring()
        if not account.authorized or keyring is None or self.layout is None:
            return None
        assert account.account is not None
        return VaultContext(
            layout=self.layout, keyring=keyring, device=await self.device_identity(), account=account.account
        )

    async def require(self) -> VaultContext:
        context = await self.current()
        if context is not None:
            return context
        if not (await self.runtime.account.status()).authorized:
            raise TelegramAccountError("telegram_not_authorized", "Not signed in")
        if not await self.runtime.transport.find_vaults():
            raise VaultNotFoundError()
        raise VaultLockedError()

    async def device_identity(self) -> DeviceIdentity:
        raw = await self.key_store.get(DEVICE_IDENTITY)
        if raw is None:
            identity = self.crypto.generate_device_identity()
            await self.key_store.put(DEVICE_IDENTITY, self.crypto.device_identity_to_bytes(identity))
            return identity
        return self.crypto.device_identity_from_bytes(raw)

    async def install(self, layout: VaultLayout, keyring: VaultKeyring) -> VaultStatus:
        if not (await self.runtime.account.status()).authorized:
            raise TelegramAccountError("telegram_not_authorized", "Not signed in")
        self.layout = layout
        await self.key_store.put(VAULT_KEYRING, self.crypto.keyring_to_bytes(keyring))
        identity = await self.device_identity()
        await self.devices.save(
            Device(
                id=identity.device_id,
                name=self.name,
                platform=self.platform,
                public_key=b64url_encode(identity.public_key),
                added_at=datetime.now(UTC),
                current=True,
            )
        )
        self.installs.append((layout, keyring))
        return VaultStatus(state=VaultState.BOOTSTRAPPING, vault_id=layout.vault_id)

    async def update_keyring(self, keyring: VaultKeyring) -> None:
        current = await self._keyring()
        if current is not None:
            assert set(current.keys) <= set(keyring.keys), "rotated keyrings keep every older epoch"
        await self.key_store.put(VAULT_KEYRING, self.crypto.keyring_to_bytes(keyring))

    async def read_header(self) -> VaultHeader | None:
        assert self.layout is not None
        text = await self.runtime.transport.read_header_text(self.layout)
        if text is None:
            return None
        header = VaultHeader.from_json(text)
        keyring = await self._keyring()
        if keyring is None:
            return header
        # A header is MACed with the epoch it declares; after a local rotation that is older than ours.
        if header.current_epoch not in keyring.keys:
            return None
        at_epoch = replace(keyring, current_epoch=header.current_epoch)
        if not self.crypto.verify_header_mac(at_epoch, header.canonical_unsigned_bytes(), header.mac):
            return None
        return header

    async def update_header(self, mutate: Callable[[VaultHeader], VaultHeader]) -> VaultHeader:
        header = await self.read_header()
        assert header is not None and self.layout is not None
        keyring = await self._keyring()
        assert keyring is not None
        updated = mutate(header)
        signed = replace(updated, mac=self.crypto.header_mac(keyring, updated.canonical_unsigned_bytes()))
        await self.runtime.transport.publish_header_text(self.layout, signed.to_json())
        return signed

    async def create_vault(self, vault_id: str = VAULT_ID) -> str:
        """First device: channels, keyring, header with a recovery code; returns the code."""
        layout = await self.runtime.transport.create_vault(vault_id)
        keyring = self.crypto.generate_keyring(vault_id)
        recovery_code = self.crypto.generate_recovery_code()
        header = VaultHeader(
            vault_id=vault_id,
            created_at=datetime.now(UTC),
            layout=layout,
            current_epoch=keyring.current_epoch,
            recovery=self.crypto.wrap_for_recovery(keyring, recovery_code),
        )
        signed = replace(header, mac=self.crypto.header_mac(keyring, header.canonical_unsigned_bytes()))
        await self.runtime.transport.publish_header_text(layout, signed.to_json())
        await self.install(layout, keyring)
        return recovery_code

    async def keyring(self) -> VaultKeyring | None:
        return await self._keyring()

    async def _keyring(self) -> VaultKeyring | None:
        raw = await self.key_store.get(VAULT_KEYRING)
        return self.crypto.keyring_from_bytes(raw) if raw is not None else None


class AccountSpy:
    """Wraps a `TelegramAccountPort`, counting accepts and optionally failing them."""

    def __init__(self, inner: Any, *, accept_error: TelegramAccountError | None = None) -> None:
        self._inner = inner
        self.accept_error = accept_error
        self.accepted_tokens: list[bytes] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def accept_login_token(self, token: bytes) -> AcceptedLogin:
        self.accepted_tokens.append(token)
        if self.accept_error is not None:
            raise self.accept_error
        result: AcceptedLogin = await self._inner.accept_login_token(token)
        return result


@dataclass
class PairingDevice:
    name: str
    key_store: InMemoryKeyStore
    runtime: TelegramRuntime
    account: AccountSpy
    vault: FakeVaultSession
    devices: SQLiteDeviceRepository
    crypto: VaultCrypto
    pairing: PairingService
    device_service: DeviceService
    identity: DeviceIdentity

    @property
    def device_id(self) -> str:
        return self.identity.device_id

    async def sign_in(self) -> None:
        await self.runtime.account.start_phone_login("+57 300 000 0001")
        status = await self.runtime.account.submit_code(FAKE_LOGIN_CODE)
        assert status.authorized


def make_pairing_device(
    root: Path,
    cloud_dir: Path,
    name: str,
    *,
    relay_url: str = "",
    timeouts: PairingTimeouts = FAST,
    clock: Callable[[], float] | None = None,
    accept_error: TelegramAccountError | None = None,
    **option_overrides: Any,
) -> PairingDevice:
    """One Bento instance: its own key store and SQLite database, sharing the fake cloud directory."""
    data_dir = root / name
    data_dir.mkdir(parents=True, exist_ok=True)
    crypto = VaultCrypto()
    identity = crypto.generate_device_identity()
    key_store = InMemoryKeyStore({DEVICE_IDENTITY: crypto.device_identity_to_bytes(identity)})
    options = FakeTelegramOptions(
        device_model=telegram_device_model(identity.device_id),
        platform="linux",
        app_name="Bento test",
        manual_login=True,
        **option_overrides,
    )
    runtime = create_fake_telegram_runtime(cloud_dir, key_store, options=options, clock=clock)
    account = AccountSpy(runtime.account, accept_error=accept_error)
    devices = SQLiteDeviceRepository(migrated_session_factory(data_dir))
    vault = FakeVaultSession(runtime, key_store, crypto, devices, name=f"{name} · Linux")
    pairing = PairingService(
        relay=WebSocketPairingRelay(relay_url, open_timeout=5.0),
        crypto=PairingCryptoFactory(),
        vault_crypto=crypto,
        vault=vault,
        account=account,
        transport=runtime.transport,
        devices=devices,
        verify_commitment=verify_commitment,
        local_device=LocalDeviceInfo(name=f"{name} · Linux", platform=DevicePlatform.LINUX, app_version="0.1.0"),
        timeouts=timeouts,
    )
    device = PairingDevice(
        name=name,
        key_store=key_store,
        runtime=runtime,
        account=account,
        vault=vault,
        devices=devices,
        crypto=crypto,
        pairing=pairing,
        device_service=DeviceService(
            devices=devices, vault=vault, account=account, transport=runtime.transport, crypto=crypto
        ),
        identity=identity,
    )
    return device


async def wait_for_state(
    get: Callable[[], Awaitable[PairingView]],
    *states: PairingState,
    timeout: float = 15.0,
) -> PairingView:
    deadline = time.monotonic() + timeout
    view = await get()
    while view.session.state not in states:
        if time.monotonic() > deadline:
            raise AssertionError(f"pairing stayed in {view.session.state} (error {view.session.error_code})")
        if view.session.state.terminal:
            raise AssertionError(f"pairing ended in {view.session.state} ({view.session.error_code})")
        await asyncio.sleep(0.02)
        view = await get()
    return view


def cloud(cloud_dir: Path) -> FakeTelegramCloud:
    return FakeTelegramCloud(cloud_dir)
