"""The encrypted vault of this device: creation, discovery, unlock, recovery kit, keyring and header.

`VaultService` implements `VaultSessionPort`, the seam shared by sync, pairing, storage, and inbox. It keeps
no state that another process could make stale: every call reads the key store and `sync_state` again, so a
vault unlocked by the API is immediately visible to the worker. Only the (network-bound) discovery of vaults in
the account is cached briefly.

Header trust (architecture § Header): a header counts as current only when it is MACed with this device's
current epoch. A removed device keeps older epochs, so an older-epoch header is only ever built upon by
`update_header` one epoch back and with a fresh recovery wrap (its recovery is never carried forward, and its
snapshot pointer only when this process verified that header while its epoch was current). An edited pinned
header reads as absent (the transport refuses it), and published headers never carry a snapshot pointer without
the document digest.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from bento.application.pairing import b64url_encode
from bento.application.sync.state import DEVICE_REMOVED, REMOVED_DEVICES
from bento.domain.account import AccountStatus, TelegramAccount
from bento.domain.devices import Device, DevicePlatform
from bento.domain.errors import (
    DomainError,
    IntegrityError,
    RecoveryCodeInvalidError,
    TelegramAccountError,
    TelegramNotAvailableError,
    ValidationFailedError,
    VaultAlreadyExistsError,
    VaultLockedError,
    VaultNotFoundError,
)
from bento.domain.security import DeviceIdentity, RecoveryWrap, VaultKeyring
from bento.domain.sync import SyncMessageKind, SyncState, SyncStatus
from bento.domain.vault import (
    DEVICE_REMOVED_REASON,
    SESSION_CLOSED_REASON,
    VaultHeader,
    VaultLayout,
    VaultState,
    VaultStatus,
    VaultUsage,
)
from bento.ports.key_store import DEVICE_IDENTITY, VAULT_KEYRING, KeyStorePort
from bento.ports.pairing import DeviceRepositoryPort
from bento.ports.repositories import ClockPort
from bento.ports.security import VaultCryptoPort
from bento.ports.telegram import TelegramAccountPort, VaultTransportPort
from bento.ports.vault import VaultContext

# `sync_state` keys owned by the vault session.
LAYOUT_KEY = "vault.layout"
CREATED_AT_KEY = "vault.created_at"
OTHER_VAULTS_KEY = "vault.other_vaults"
RECOVERY_KIT_SAVED_KEY = "vault.recovery_kit_saved"
RECOVERY_KIT_CHECK_KEY = "vault.recovery_kit_check"
RECOVERY_KIT_WRAP_KEY = "vault.recovery_kit_wrap"
"""Nonce of the recovery wrap whose code this device showed, so a confirmation never marks a newer code."""
HEADER_CLEANUP_KEY_PREFIX = "vault.header_cleanup_after."
"""Sync message id below which superseded headers of the vault were already deleted by this device."""
BOOTSTRAP_PENDING_KEY = "vault.bootstrap_pending"
"""ISO time of an `install()` the sync engine has not pulled after yet (`"0"` once it has)."""
KEYRING_REVISION_KEY = "vault.keyring_revision"
"""Changes with every keyring write, so other processes drop their cached context."""

DISCOVERY_TTL_SECONDS = 30.0
ACCOUNT_RECHECK_SECONDS = 30.0
RECOVERY_KIT_RECHECK_SECONDS = 30.0
HEADER_SCAN_PAGE = 100
HEADER_SCAN_MAX_PAGES = 50
"""A first cleanup on a long Sync channel is spread over several header updates (the cursor keeps progress)."""
DELETE_CHUNK = 100
LOGGER = logging.getLogger("bento.vault")
_CROCKFORD_ALIASES = str.maketrans({"O": "0", "I": "1", "L": "1"})


class VaultStatePort(Protocol):
    """Device-local string values in `sync_state`."""

    async def get_value(self, key: str) -> str | None: ...

    async def set_value(self, key: str, value: str) -> None: ...

    async def delete_value(self, key: str) -> None: ...


class StorageBackendPreferencePort(Protocol):
    async def prefer_telegram(self) -> None:
        """Persist `storage_backend=telegram` when the saved choice is still `local` (a vault now exists)."""
        ...


class RecoveryGroupMismatchError(DomainError):
    def __init__(self) -> None:
        super().__init__("recovery_group_mismatch", "The last group does not match the newest recovery code")


class VaultUsagePort(Protocol):
    async def usage(self) -> VaultUsage:
        """Files and bytes in the library (from the catalog)."""
        ...


@dataclass(frozen=True, slots=True)
class DeviceDescription:
    name: str
    platform: DevicePlatform


@dataclass(frozen=True, slots=True)
class TelegramPorts:
    account: TelegramAccountPort
    transport: VaultTransportPort


class SyncSignalPort(Protocol):
    """The parts of `SyncStatusProviderPort` the vault session uses."""

    async def status(self) -> SyncStatus: ...

    async def request_sync(self) -> None: ...


TelegramResolver = Callable[[], TelegramPorts | None]
"""`None` in local storage mode; raises `TelegramNotAvailableError` when the build has no credentials."""

ChangeListener = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class CreatedVault:
    status: VaultStatus
    recovery_code: str


@dataclass(frozen=True, slots=True)
class _CachedContext:
    token: tuple[str | None, str | None]
    context: VaultContext
    at: float


@dataclass(frozen=True, slots=True)
class _CachedKit:
    vault_id: str
    saved: bool
    at: float
    stale: bool = False


@dataclass(frozen=True, slots=True)
class _Discovery:
    layout: VaultLayout | None
    header: VaultHeader | None
    others: int
    at: float
    candidates: tuple[tuple[VaultLayout, VaultHeader], ...] = ()
    """Every vault of the account with a parseable header, newest `created_at` first."""


class DeviceIdentityStore:
    """This device's X25519 identity, created on first use and kept in the key store."""

    def __init__(self, key_store: KeyStorePort, crypto: VaultCryptoPort) -> None:
        self._key_store = key_store
        self._crypto = crypto

    async def get(self) -> DeviceIdentity:
        raw = await self._key_store.get(DEVICE_IDENTITY)
        if raw is not None:
            return self._crypto.device_identity_from_bytes(raw)
        identity = self._crypto.generate_device_identity()
        await self._key_store.put(DEVICE_IDENTITY, self._crypto.device_identity_to_bytes(identity))
        # Another process may have won the race; everyone keeps the stored identity.
        stored = await self._key_store.get(DEVICE_IDENTITY)
        return self._crypto.device_identity_from_bytes(stored) if stored is not None else identity

    async def renew(self, previous: DeviceIdentity) -> DeviceIdentity:
        """Replace `previous` with a fresh identity (a removed device joins again under a new id)."""
        raw = await self._key_store.get(DEVICE_IDENTITY)
        if raw is not None:
            stored = self._crypto.device_identity_from_bytes(raw)
            if stored.device_id != previous.device_id:
                return stored  # another process renewed it first
        identity = self._crypto.generate_device_identity()
        await self._key_store.put(DEVICE_IDENTITY, self._crypto.device_identity_to_bytes(identity))
        return identity


class VaultService:
    def __init__(
        self,
        *,
        telegram: TelegramResolver,
        crypto: VaultCryptoPort,
        key_store: KeyStorePort,
        state: VaultStatePort,
        devices: DeviceRepositoryPort,
        usage: VaultUsagePort,
        device: DeviceDescription,
        clock: ClockPort,
        identities: DeviceIdentityStore | None = None,
        on_change: ChangeListener | None = None,
        backend_preference: StorageBackendPreferencePort | None = None,
        sync: Callable[[], SyncSignalPort | None] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._telegram = telegram
        self._crypto = crypto
        self._key_store = key_store
        self._state = state
        self._devices = devices
        self._usage = usage
        self._device = device
        self._clock = clock
        self._identities = identities or DeviceIdentityStore(key_store, crypto)
        self._on_change = on_change
        self._backend_preference = backend_preference
        self._sync = sync
        self._monotonic = monotonic
        self._discovery: _Discovery | None = None
        self._context: _CachedContext | None = None
        self._kit: _CachedKit | None = None
        self._current_header: VaultHeader | None = None
        """Last header `read_header` verified at this device's current epoch, or that this process published."""

    # VaultSessionPort

    async def status(self) -> VaultStatus:
        try:
            ports = self._telegram()
        except TelegramNotAvailableError:
            # Without build credentials nobody can sign in; the library keeps working locally.
            return VaultStatus(state=VaultState.SIGNED_OUT)
        if ports is None:
            return VaultStatus(state=VaultState.LOCAL_ONLY)
        account = await ports.account.status()
        if not account.authorized or account.account is None:
            # A device that was attached to a vault and lost its Telegram session (logged out, or closed from
            # another device) is not a new user: the app offers to reconnect instead of the first-run welcome.
            if await self._state.get_value(LAYOUT_KEY) is not None:
                removed = await self._removal_flag() is not None
                return VaultStatus(
                    state=VaultState.SIGNED_OUT, reason=DEVICE_REMOVED_REASON if removed else SESSION_CLOSED_REASON
                )
            return VaultStatus(state=VaultState.SIGNED_OUT)
        local = await self._local(account.account)
        if local is not None:
            layout, keyring = local
            created_at = await self._state.get_value(CREATED_AT_KEY)
            kit = await self._recovery_kit_state(ports, layout, keyring)
            return VaultStatus(
                state=VaultState.BOOTSTRAPPING if await self._bootstrapping() else VaultState.READY,
                vault_id=layout.vault_id,
                created_at=datetime.fromisoformat(created_at) if created_at else None,
                recovery_kit_saved=kit.saved,
                recovery_kit_stale=kit.stale,
                devices_count=len(await self._devices.list()),
                usage=await self._usage.usage(),
                other_vaults=int(await self._state.get_value(OTHER_VAULTS_KEY) or 0),
            )
        if await self._removal_flag() is not None:
            raw = await self._state.get_value(LAYOUT_KEY)
            created_at = await self._state.get_value(CREATED_AT_KEY)
            return VaultStatus(
                state=VaultState.LOCKED,
                vault_id=_layout_from_json(raw)[0].vault_id if raw is not None else None,
                created_at=datetime.fromisoformat(created_at) if created_at else None,
                reason=DEVICE_REMOVED_REASON,
            )
        discovery = await self._discover(ports)
        if discovery.layout is None or discovery.header is None:
            return VaultStatus(state=VaultState.NO_VAULT)
        return VaultStatus(
            state=VaultState.LOCKED,
            vault_id=discovery.layout.vault_id,
            created_at=discovery.header.created_at,
            other_vaults=discovery.others,
        )

    async def current(self) -> VaultContext | None:
        """Cached in-process; re-read when the stored layout or keyring revision changes (and every 30 s)."""
        token = (await self._state.get_value(LAYOUT_KEY), await self._state.get_value(KEYRING_REVISION_KEY))
        cached = self._context
        if cached is not None and cached.token == token and self._monotonic() - cached.at < ACCOUNT_RECHECK_SECONDS:
            return cached.context
        self._context = None
        ports = self._optional_ports()
        if ports is None:
            return None
        account = await ports.account.status()
        if not account.authorized or account.account is None:
            return None
        local = await self._local(account.account)
        if local is None:
            return None
        layout, keyring = local
        context = VaultContext(layout=layout, keyring=keyring, device=await self._identities.get(), account=account.account)
        self._context = _CachedContext(token=token, context=context, at=self._monotonic())
        return context

    async def require(self) -> VaultContext:
        context = await self.current()
        if context is not None:
            return context
        ports = self._telegram()
        if ports is None:
            raise VaultNotFoundError()
        account = _authorized(await ports.account.status())
        local = await self._local(account)
        if local is not None:
            layout, keyring = local
            return VaultContext(layout=layout, keyring=keyring, device=await self._identities.get(), account=account)
        if await self._removal_flag() is not None:
            raise VaultLockedError()
        discovery = await self._discover(ports)
        if discovery.layout is None or discovery.header is None:
            raise VaultNotFoundError()
        raise VaultLockedError()

    async def device_identity(self) -> DeviceIdentity:
        """This device's identity. A removed device without usable vault keys gets a fresh one, so it joins
        again (pairing, recovery code) under a new id that peers have never seen removed."""
        identity = await self._identities.get()
        locked_out = await self._key_store.get(VAULT_KEYRING) is None or await self._removal_flag() is not None
        if locked_out and await self._identity_removed(identity):
            identity = await self._renew_identity(identity)
        return identity

    async def install(self, layout: VaultLayout, keyring: VaultKeyring) -> VaultStatus:
        ports = self._require_ports()
        account = _authorized(await ports.account.status())
        if keyring.vault_id != layout.vault_id:
            raise ValidationFailedError("The keyring belongs to another vault")
        identity = await self._identities.get()
        rejoining = await self._removal_flag() is not None
        if await self._identity_removed(identity):
            await self._renew_identity(identity)
        installed = await self._local(account)
        existing = await self._stored_keyring()
        if existing is not None and existing.vault_id == keyring.vault_id:
            keyring = _merge_keyrings(existing, keyring)
        await self._write_keyring(keyring)
        if installed is None or installed[0] != layout:
            await self._state.set_value(BOOTSTRAP_PENDING_KEY, self._clock.now().isoformat())
        await self._save_layout(layout, account)
        if rejoining:
            # Sync stopped right before the keys message that removed this device; it is read again now.
            await self._state.delete_value(DEVICE_REMOVED)
        header = await self._verified_header(ports, layout, keyring)
        if header is not None:
            await self._state.set_value(CREATED_AT_KEY, header.created_at.isoformat())
        await self._register_device()
        await self._changed()
        return await self.status()

    async def update_keyring(self, keyring: VaultKeyring) -> None:
        context = await self.require()
        current = context.keyring
        if keyring.vault_id != current.vault_id:
            raise ValidationFailedError("The keyring belongs to another vault")
        if not set(current.keys) <= set(keyring.keys):
            raise ValidationFailedError("A rotated keyring must keep every older epoch")
        if any(keyring.keys[epoch] != key for epoch, key in current.keys.items()):
            raise IntegrityError("vault_keyring")
        if keyring.current_epoch < current.current_epoch:
            raise ValidationFailedError("The keyring epoch cannot go back")
        await self._write_keyring(keyring)

    async def read_header(self) -> VaultHeader | None:
        """The pinned header, only when MACed with this device's current epoch (None otherwise)."""
        ports = self._optional_ports()
        if ports is None:
            return None
        account = await ports.account.status()
        if not account.authorized or account.account is None:
            return None
        local = await self._local(account.account)
        if local is not None:
            header = await self._verified_header(ports, *local)
            # Remembered for a rotation that follows (`update_header` may keep this header's snapshot pointer).
            self._current_header = header
            return header
        discovery = await self._discover(ports)
        return discovery.header

    async def update_header(self, mutate: Callable[[VaultHeader], VaultHeader]) -> VaultHeader:
        """Publish the mutated header (nothing is posted when it does not change), then delete superseded headers.

        The base is the pinned header at this device's current epoch, or one epoch back when the mutation brings a
        fresh recovery wrap (the device that rotated, or anyone generating a new kit after an unfinished rotation).
        """
        context = await self.require()
        ports = self._require_ports()
        keyring = context.keyring
        header = await self._pinned_header(ports, context.layout, keyring)
        if header is None or header.current_epoch < keyring.current_epoch - 1:
            raise IntegrityError("vault_header")
        updated = mutate(header)
        if updated.vault_id != header.vault_id or updated.layout != header.layout:
            raise ValidationFailedError("The vault id and layout of a header cannot change")
        if header.current_epoch < keyring.current_epoch:
            if updated.recovery == header.recovery:
                # Its wrap holds an older keyring: carrying it forward would leave a kit that cannot open the vault.
                LOGGER.warning("The vault header is one key epoch behind; a new recovery kit is needed")
                self._kit = None
                raise IntegrityError("vault_header_stale")
            if updated.snapshot is not None and updated.snapshot == header.snapshot and header != self._current_header:
                LOGGER.warning("Dropped the snapshot pointer of an older-epoch header that this device did not verify")
                updated = replace(updated, snapshot=None)
        if updated.snapshot is not None and updated.snapshot.sha256 is None:
            # Written before pointers carried the document digest: never trusted at bootstrap, never published again.
            LOGGER.info("Dropped a snapshot pointer without a digest from the vault header")
            updated = replace(updated, snapshot=None)
        signed = self._sign(replace(updated, current_epoch=keyring.current_epoch, mac=None), keyring)
        if signed == header:
            return header
        message_id = await ports.transport.publish_header_text(context.layout, signed.to_json())
        self._current_header = signed
        await self._mirror_kit(signed)
        await self._delete_superseded_headers(ports, context.layout, message_id)
        return signed

    async def remember_recovery_kit(self, recovery_code: str, wrap: RecoveryWrap) -> None:
        """Record the check of a recovery code this process generated elsewhere (key rotation), so the person can
        confirm that kit with its last group."""
        context = await self.require()
        await self._remember_kit(context.layout.vault_id, recovery_code, wrap)
        self._kit = None

    async def forget_keys_after_removal(self) -> None:
        """This device was removed (sync saw a rotation without it): drop the vault keys, keep the local library."""
        await self._key_store.delete(VAULT_KEYRING)
        await self._state.set_value(KEYRING_REVISION_KEY, secrets.token_hex(8))
        self.invalidate()

    # Vault use cases

    async def create(self) -> CreatedVault:
        """First device: channels, folder, keys, header with the recovery wrap, device registration.

        Safe to retry after a crash: keys are stored before anything is published and the layout only after the
        header, so a half-created vault of this device is resumed (with a fresh recovery code) instead of duplicated.
        """
        ports = self._require_ports()
        account = _authorized(await ports.account.status())
        if await self._local(account) is not None:
            raise VaultAlreadyExistsError((await self._local_layout_id()) or "")
        discovery = await self._discover(ports, fresh=True)
        stored = await self._stored_keyring()
        created_at = self._clock.now()
        if discovery.layout is not None and discovery.header is not None:
            adopt = stored is not None and stored.vault_id == discovery.layout.vault_id
            if not adopt or stored is None or not self._verify(stored, discovery.header):
                raise VaultAlreadyExistsError(discovery.layout.vault_id)
            keyring, created_at = stored, discovery.header.created_at
        elif stored is not None and await self._find_layout(ports, stored.vault_id) is not None:
            keyring = stored
        else:
            keyring = self._crypto.generate_keyring(f"vlt_{secrets.token_hex(8)}")
            await self._write_keyring(keyring)
        layout = await ports.transport.create_vault(keyring.vault_id)
        recovery_code = self._crypto.generate_recovery_code()
        header = self._sign(
            VaultHeader(
                vault_id=keyring.vault_id,
                created_at=created_at,
                layout=layout,
                current_epoch=keyring.current_epoch,
                recovery=self._crypto.wrap_for_recovery(keyring, recovery_code),
            ),
            keyring,
        )
        await ports.transport.publish_header_text(layout, header.to_json())
        await self._state.set_value(CREATED_AT_KEY, header.created_at.isoformat())
        await self._state.set_value(OTHER_VAULTS_KEY, str(discovery.others if discovery.header is not None else 0))
        await self._state.set_value(BOOTSTRAP_PENDING_KEY, "0")
        await self._remember_kit(keyring.vault_id, recovery_code, header.recovery)
        await self._save_layout(layout, account)
        await self._register_device()
        await self._changed()
        return CreatedVault(status=await self.status(), recovery_code=recovery_code)

    async def unlock(self, recovery_code: str) -> VaultStatus:
        """Open the account's vault on this device with the recovery kit."""
        ports = self._require_ports()
        _authorized(await ports.account.status())
        code = self._crypto.normalize_recovery_code(recovery_code)
        discovery = await self._discover(ports, fresh=True)
        if discovery.layout is None or discovery.header is None:
            raise VaultNotFoundError()
        layout, header, keyring = self._unwrap_any(discovery, code)
        await self._state.set_value(OTHER_VAULTS_KEY, str(discovery.others))
        await self.install(layout, keyring)
        await self._remember_kit(header.vault_id, code, header.recovery)
        if header.recovery.confirmed_at is None:
            # Opening the vault with the code proves it was saved; tell every device. Unlock succeeded anyway.
            try:
                await self.update_header(self._confirming(header.recovery.nonce))
            except DomainError as exc:
                LOGGER.warning("Could not mark the recovery kit as saved after unlocking: %s", exc.code)
        return await self.status()

    async def rotate_recovery_code(self) -> str:
        """A new recovery code wrapped into a new header; the previous code no longer opens the vault.

        Also the way out of a stale kit: it may build on a header one epoch back (see `update_header`).
        """
        context = await self.require()
        code = self._crypto.generate_recovery_code()
        wrap = self._crypto.wrap_for_recovery(context.keyring, code)
        await self.update_header(lambda header: replace(header, recovery=wrap))
        await self._remember_kit(context.layout.vault_id, code, wrap)
        self._kit = None
        return code

    async def confirm_recovery_kit(self, last_group: str) -> VaultStatus:
        """Mark the kit as saved, for every device, when the person types the last group of the newest code.

        The mark lives in the MAC-covered header (`recovery.confirmed_at`). It is only set while the header still
        carries the wrap whose code this device showed: a code rotated elsewhere in the meantime stays unconfirmed.
        """
        context = await self.require()
        expected = await self._state.get_value(RECOVERY_KIT_CHECK_KEY)
        if expected is None or not secrets.compare_digest(expected, _kit_check(context.layout.vault_id, last_group)):
            raise RecoveryGroupMismatchError()
        await self.update_header(self._confirming(await self._state.get_value(RECOVERY_KIT_WRAP_KEY)))
        return await self.status()

    async def verify_recovery_code(self, recovery_code: str) -> bool:
        """Whether the code opens the current kit; a stale kit (older-epoch header) opens nothing current."""
        found, header = await self._recovery_header()
        if not found:
            raise VaultNotFoundError()
        if header is None:
            return False
        try:
            self._crypto.unwrap_with_recovery(header.recovery, recovery_code, vault_id=header.vault_id)
        except (RecoveryCodeInvalidError, IntegrityError, ValidationFailedError):
            return False
        return True

    def invalidate(self) -> None:
        """Forget cached discovery, context, and recovery kit state (account changes, tests)."""
        self._discovery = None
        self._context = None
        self._kit = None
        self._current_header = None

    # Internals

    def _optional_ports(self) -> TelegramPorts | None:
        try:
            return self._telegram()
        except TelegramNotAvailableError:
            return None

    def _require_ports(self) -> TelegramPorts:
        ports = self._telegram()
        if ports is None:
            raise VaultNotFoundError()
        return ports

    async def _write_keyring(self, keyring: VaultKeyring) -> None:
        await self._key_store.put(VAULT_KEYRING, self._crypto.keyring_to_bytes(keyring))
        await self._state.set_value(KEYRING_REVISION_KEY, secrets.token_hex(8))
        self._context = None

    async def _bootstrapping(self) -> bool:
        """The sync engine reports a bootstrap, or it has not pulled since this device installed the vault."""
        sync = self._sync_signal()
        status = None
        if sync is not None:
            try:
                status = await sync.status()
            except DomainError:
                status = None
        if status is not None and status.state == SyncState.BOOTSTRAPPING:
            return True
        pending = await self._state.get_value(BOOTSTRAP_PENDING_KEY)
        if pending is None or pending == "0":
            return False
        if status is None:
            return True
        try:
            installed_at = datetime.fromisoformat(pending)
        except ValueError:
            installed_at = None
        if installed_at is not None and status.last_pull_at is not None and status.last_pull_at >= installed_at:
            await self._state.set_value(BOOTSTRAP_PENDING_KEY, "0")
            return False
        return True

    def _sync_signal(self) -> SyncSignalPort | None:
        if self._sync is None:
            return None
        try:
            return self._sync()
        except (DomainError, NotImplementedError):
            return None

    async def _stored_keyring(self) -> VaultKeyring | None:
        raw = await self._key_store.get(VAULT_KEYRING)
        return self._crypto.keyring_from_bytes(raw) if raw is not None else None

    async def _local(self, account: TelegramAccount) -> tuple[VaultLayout, VaultKeyring] | None:
        raw = await self._state.get_value(LAYOUT_KEY)
        if raw is None:
            return None
        layout, user_id = _layout_from_json(raw)
        if user_id != account.user_id:
            return None
        keyring = await self._stored_keyring()
        if keyring is None or keyring.vault_id != layout.vault_id:
            return None
        if await self._removal_flag() is not None:
            return None
        return layout, keyring

    async def _local_layout_id(self) -> str | None:
        raw = await self._state.get_value(LAYOUT_KEY)
        return _layout_from_json(raw)[0].vault_id if raw is not None else None

    async def _save_layout(self, layout: VaultLayout, account: TelegramAccount) -> None:
        await self._state.set_value(LAYOUT_KEY, _layout_to_json(layout, account.user_id))
        self._discovery = None
        self._context = None

    async def _discover(self, ports: TelegramPorts, *, fresh: bool = False) -> _Discovery:
        cached = self._discovery
        if not fresh and cached is not None and self._monotonic() - cached.at < DISCOVERY_TTL_SECONDS:
            return cached
        candidates: list[tuple[VaultLayout, VaultHeader]] = []
        layouts = await ports.transport.find_vaults()
        for layout in layouts:
            header = _parse_header(await ports.transport.read_header_text(layout))
            # `created_at` is unauthenticated here; the parser already refused naive timestamps.
            if header is not None and header.vault_id == layout.vault_id and header.layout == layout:
                candidates.append((layout, header))
        candidates.sort(key=lambda item: _sort_key(item[1]), reverse=True)
        stored = await self._stored_keyring()
        # A device that holds keys picks the vault whose header its keyring authenticates.
        verified = [item for item in candidates if stored is not None and self._verify(stored, item[1])]
        chosen = verified[0] if verified else (candidates[0] if candidates else None)
        discovery = _Discovery(
            layout=chosen[0] if chosen else None,
            header=chosen[1] if chosen else None,
            others=max(len(candidates) - 1, 0),
            at=self._monotonic(),
            candidates=tuple(candidates),
        )
        self._discovery = discovery
        return discovery

    async def _find_layout(self, ports: TelegramPorts, vault_id: str) -> VaultLayout | None:
        return next((layout for layout in await ports.transport.find_vaults() if layout.vault_id == vault_id), None)

    async def _verified_header(
        self, ports: TelegramPorts, layout: VaultLayout, keyring: VaultKeyring
    ) -> VaultHeader | None:
        """The pinned header when MACed with this device's current epoch: older epochs are held by removed devices."""
        header = await self._pinned_header(ports, layout, keyring)
        if header is None or header.current_epoch != keyring.current_epoch:
            return None
        return header

    async def _pinned_header(
        self, ports: TelegramPorts, layout: VaultLayout, keyring: VaultKeyring
    ) -> VaultHeader | None:
        """The pinned header MACed with any epoch this device holds (callers decide which epochs they accept)."""
        header = _parse_header(await ports.transport.read_header_text(layout))
        if header is None or header.vault_id != layout.vault_id or header.layout != layout:
            return None
        return header if self._verify(keyring, header) else None

    async def _recovery_header(self) -> tuple[bool, VaultHeader | None]:
        """`(vault found, header whose wrap a code must open)`: the current-epoch header when unlocked here."""
        ports = self._optional_ports()
        if ports is None:
            return False, None
        account = await ports.account.status()
        if not account.authorized or account.account is None:
            return False, None
        local = await self._local(account.account)
        if local is not None:
            return True, await self._verified_header(ports, *local)
        header = (await self._discover(ports)).header
        return header is not None, header

    def _unwrap_any(self, discovery: _Discovery, code: str) -> tuple[VaultLayout, VaultHeader, VaultKeyring]:
        """The candidate whose recovery wrap this code opens and whose MAC the unwrapped keyring verifies at its own
        current epoch; that, not the unauthenticated `created_at`, is what identifies the vault."""
        failure: DomainError = RecoveryCodeInvalidError()
        for layout, header in discovery.candidates or ((discovery.layout, discovery.header),):  # type: ignore[assignment]
            if layout is None or header is None:
                continue
            try:
                keyring = self._crypto.unwrap_with_recovery(header.recovery, code, vault_id=header.vault_id)
            except (RecoveryCodeInvalidError, IntegrityError, ValidationFailedError) as exc:
                failure = exc
                continue
            if header.current_epoch != keyring.current_epoch or not self._verify(keyring, header):
                failure = IntegrityError("vault_header")
                continue
            return layout, header, keyring
        raise failure

    async def _removal_flag(self) -> dict[str, object] | None:
        """The `sync_state` mark the sync engine leaves when this device was removed; cleared by `install`."""
        raw = await self._state.get_value(DEVICE_REMOVED)
        if raw is None:
            return None
        try:
            flag = json.loads(raw)
        except ValueError:
            flag = None
        return flag if isinstance(flag, dict) else {}

    async def _identity_removed(self, identity: DeviceIdentity) -> bool:
        flag = await self._removal_flag()
        if flag is not None and flag.get("device_id") == identity.device_id:
            return True
        row = await self._devices.get(identity.device_id)
        if row is not None and row.removed_at is not None:
            return True
        raw = await self._state.get_value(REMOVED_DEVICES)
        try:
            removed = json.loads(raw) if raw is not None else []
        except ValueError:
            removed = []
        return isinstance(removed, list) and identity.device_id in removed

    async def _renew_identity(self, previous: DeviceIdentity) -> DeviceIdentity:
        identity = await self._identities.renew(previous)
        LOGGER.info("This device was removed from the vault; it joins again with a new device identity")
        self._context = None
        return identity

    def _verify(self, keyring: VaultKeyring, header: VaultHeader) -> bool:
        if header.current_epoch not in keyring.keys:
            return False
        scoped = VaultKeyring(vault_id=keyring.vault_id, current_epoch=header.current_epoch, keys=keyring.keys)
        return self._crypto.verify_header_mac(scoped, header.canonical_unsigned_bytes(), header.mac)

    def _sign(self, header: VaultHeader, keyring: VaultKeyring) -> VaultHeader:
        unsigned = replace(header, current_epoch=keyring.current_epoch, mac=None)
        return replace(unsigned, mac=self._crypto.header_mac(keyring, unsigned.canonical_unsigned_bytes()))

    async def _remember_kit(self, vault_id: str, recovery_code: str, wrap: RecoveryWrap) -> None:
        last_group = self._crypto.normalize_recovery_code(recovery_code).rsplit("-", 1)[-1]
        await self._state.set_value(RECOVERY_KIT_CHECK_KEY, _kit_check(vault_id, last_group))
        await self._state.set_value(RECOVERY_KIT_WRAP_KEY, wrap.nonce)
        await self._state.set_value(RECOVERY_KIT_SAVED_KEY, "1" if wrap.confirmed_at is not None else "0")

    def _confirming(self, wrap_nonce: str | None) -> Callable[[VaultHeader], VaultHeader]:
        confirmed_at = self._clock.now()

        def mutate(header: VaultHeader) -> VaultHeader:
            recovery = header.recovery
            if recovery.confirmed_at is not None or (wrap_nonce is not None and recovery.nonce != wrap_nonce):
                return header
            return replace(header, recovery=replace(recovery, confirmed_at=confirmed_at))

        return mutate

    async def _recovery_kit_state(self, ports: TelegramPorts, layout: VaultLayout, keyring: VaultKeyring) -> _CachedKit:
        """Vault-wide: the current header's wrap is confirmed. The local mirror answers when Telegram cannot.

        A pinned header of an older epoch (a rotation whose header never got published) wraps a keyring without the
        current key: its kit is stale and reported as not saved until a new kit is generated.
        """
        cached = self._kit
        if (
            cached is not None
            and cached.vault_id == layout.vault_id
            and self._monotonic() - cached.at < RECOVERY_KIT_RECHECK_SECONDS
        ):
            return cached
        try:
            header = await self._pinned_header(ports, layout, keyring)
        except DomainError as exc:
            LOGGER.debug("Vault header unavailable for the recovery kit state: %s", exc.code)
            header = None
        if header is not None and header.current_epoch < keyring.current_epoch:
            self._kit = _CachedKit(vault_id=layout.vault_id, saved=False, at=self._monotonic(), stale=True)
            return self._kit
        if header is None or header.current_epoch != keyring.current_epoch:
            # Cached as well, so an unreachable or rate-limited Telegram is not asked again on every status call.
            saved = await self._state.get_value(RECOVERY_KIT_SAVED_KEY) == "1"
            self._kit = _CachedKit(vault_id=layout.vault_id, saved=saved, at=self._monotonic())
            return self._kit
        await self._mirror_kit(header)
        assert self._kit is not None
        return self._kit

    async def _mirror_kit(self, header: VaultHeader) -> bool:
        """Cache the header's recovery kit state and keep the local fallback flag in step with it."""
        saved = header.recovery.confirmed_at is not None
        self._kit = _CachedKit(vault_id=header.vault_id, saved=saved, at=self._monotonic())
        flag = "1" if saved else "0"
        if await self._state.get_value(RECOVERY_KIT_SAVED_KEY) != flag:
            await self._state.set_value(RECOVERY_KIT_SAVED_KEY, flag)
        return saved

    async def _delete_superseded_headers(self, ports: TelegramPorts, layout: VaultLayout, current_message_id: int) -> None:
        """Best effort: older headers carry the keyring wrapped by older recovery codes, so they must not linger.

        Scans the Sync channel from where this device's last cleanup stopped and deletes every header posted before
        `current_message_id`; the current header and anything newer (another device's) are never touched.
        """
        cursor_key = HEADER_CLEANUP_KEY_PREFIX + layout.vault_id
        cursor = int(await self._state.get_value(cursor_key) or 0)
        scanned_through = current_message_id - 1
        stale: list[int] = []
        try:
            for _ in range(HEADER_SCAN_MAX_PAGES):
                refs = await ports.transport.list_sync_messages(layout, after_message_id=cursor, limit=HEADER_SCAN_PAGE)
                stale.extend(
                    ref.message_id
                    for ref in refs
                    if ref.kind == SyncMessageKind.HEADER and ref.message_id < current_message_id
                )
                if len(refs) < HEADER_SCAN_PAGE or refs[-1].message_id >= current_message_id:
                    break
                cursor = refs[-1].message_id
            else:
                scanned_through = cursor
            for offset in range(0, len(stale), DELETE_CHUNK):
                await ports.transport.delete_sync_messages(layout, tuple(stale[offset : offset + DELETE_CHUNK]))
        except DomainError as exc:
            LOGGER.warning("Could not delete %s superseded vault header(s): %s", len(stale), exc.code)
            return
        except Exception as exc:  # noqa: BLE001 - the new header is already published; cleanup retries next time
            LOGGER.warning("Could not delete %s superseded vault header(s): %s", len(stale), exc.__class__.__name__)
            return
        if stale:
            LOGGER.info("Deleted %s superseded vault header(s)", len(stale))
        # The current header stays above the cursor, so the next update finds and deletes it.
        await self._state.set_value(cursor_key, str(scanned_through))

    async def _register_device(self) -> None:
        identity = await self.device_identity()
        existing = await self._devices.get(identity.device_id)
        now = self._clock.now()
        await self._devices.save(
            Device(
                id=identity.device_id,
                name=existing.name if existing is not None else self._device.name,
                platform=existing.platform if existing is not None else self._device.platform,
                public_key=b64url_encode(identity.public_key),
                added_at=existing.added_at if existing is not None else now,
                telegram_auth_hash=existing.telegram_auth_hash if existing is not None else None,
                last_seen_at=now,
                removed_at=None,
                current=True,
            )
        )

    async def _changed(self) -> None:
        self._discovery = None
        self._context = None
        if self._backend_preference is not None:
            await self._backend_preference.prefer_telegram()
        sync = self._sync_signal()
        if sync is not None:
            try:
                await sync.request_sync()
            except DomainError:
                pass
        if self._on_change is not None:
            await self._on_change()


def _authorized(status: AccountStatus) -> TelegramAccount:
    if not status.authorized or status.account is None:
        raise TelegramAccountError("telegram_not_authorized", "This device is not signed in to Telegram")
    return status.account


def _merge_keyrings(first: VaultKeyring, second: VaultKeyring) -> VaultKeyring:
    for epoch in set(first.keys) & set(second.keys):
        if first.keys[epoch] != second.keys[epoch]:
            raise IntegrityError("vault_keyring")
    return VaultKeyring(
        vault_id=first.vault_id,
        current_epoch=max(first.current_epoch, second.current_epoch),
        keys={**first.keys, **second.keys},
    )


def _sort_key(header: VaultHeader) -> float:
    try:
        return header.created_at.timestamp()
    except (OverflowError, OSError, ValueError):
        return float("-inf")


def _parse_header(text: str | None) -> VaultHeader | None:
    if text is None:
        return None
    try:
        return VaultHeader.from_json(text)
    except ValidationFailedError:
        return None


def _layout_to_json(layout: VaultLayout, user_id: int) -> str:
    return json.dumps(
        {
            "vault_id": layout.vault_id,
            "files": layout.files_channel_id,
            "sync": layout.sync_channel_id,
            "inbox": layout.inbox_channel_id,
            "account_user_id": user_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _layout_from_json(raw: str) -> tuple[VaultLayout, int | None]:
    try:
        data = json.loads(raw)
        layout = VaultLayout(
            vault_id=str(data["vault_id"]),
            files_channel_id=int(data["files"]),
            sync_channel_id=int(data["sync"]),
            inbox_channel_id=int(data["inbox"]),
        )
        user_id = data.get("account_user_id")
        return layout, int(user_id) if user_id is not None else None
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationFailedError("Stored vault layout is invalid") from exc


def _kit_check(vault_id: str, last_group: str) -> str:
    normalized = "".join(last_group.split()).replace("-", "").upper().translate(_CROCKFORD_ALIASES)
    return hashlib.sha256(f"bento/v1/recovery-kit-check:{vault_id}:{normalized}".encode()).hexdigest()
