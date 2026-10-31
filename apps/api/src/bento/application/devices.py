"""Devices of the vault: listing, renaming, and removal with key rotation.

Removal (`orchestration/architecture/telegram-first.md` § Devices, Removal, Key Rotation):

1. mark the device `removed_at` (a synced `device` op);
2. close its Telegram session, matched by authorization hash or by `device_model = "Bento (<id suffix>)"`;
   a "session too new" refusal is reported as `telegram_session_closed = False` and removal continues;
3. rotate keys: new epoch, a `.bkeys` Sync message (v2, sender-authenticated, listing every removed device)
   with grants for every remaining active device, the local keyring update, and a new header wrapped with a
   **new recovery code** returned once.

The registry decides who gets the new keys, and any device holding the vault keys can add rows to it through
sync. `removal_preview` lists the devices that would receive them, and `remove(..., exclude_device_ids=...)`
leaves unknown ones out: excluded devices are marked removed and listed in `removed_device_ids` too (their
Telegram sessions are not closed: a forged row may carry another device's session hash or model).

Removing an already removed device runs steps 2 and 3 again, so a failed rotation can be retried.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from bento.application.pairing import decode_public_key, normalize_device_name
from bento.application.sync.keys import build_keys_message, is_device_id
from bento.domain.account import TelegramAuthorization
from bento.domain.devices import Device, DeviceRemoval
from bento.domain.errors import DeviceNotFoundError, DomainError, ValidationFailedError
from bento.domain.security import VaultKeyring
from bento.domain.sync import SyncMessageKind
from bento.domain.vault import VaultHeader
from bento.ports.pairing import DeviceRepositoryPort
from bento.ports.security import VaultCryptoPort
from bento.ports.telegram import TelegramAccountPort, VaultTransportPort
from bento.ports.vault import RecoveryKitRecorderPort, VaultContext, VaultSessionPort

logger = logging.getLogger("bento.devices")

TELEGRAM_DEVICE_MODEL_PREFIX = "Bento"
DEVICE_ID_SUFFIX_CHARS = 6


def telegram_device_model(device_id: str) -> str:
    """`device_model` every Bento client announces to Telegram, e.g. `Bento (a1b2c3)`."""
    return f"{TELEGRAM_DEVICE_MODEL_PREFIX} ({device_id[-DEVICE_ID_SUFFIX_CHARS:]})"


def match_authorizations(
    device: Device, authorizations: Iterable[TelegramAuthorization]
) -> tuple[TelegramAuthorization, ...]:
    """Other sessions that belong to `device`: its recorded hash and every session announcing its `device_model`.

    The current session (reported with hash 0) is never a match.
    """
    model = telegram_device_model(device.id)
    return tuple(
        item
        for item in authorizations
        if not item.current
        and item.hash != 0
        and ((device.telegram_auth_hash and item.hash == device.telegram_auth_hash) or item.device_model == model)
    )


class DeviceIsCurrentError(DomainError):
    def __init__(self, device_id: str) -> None:
        super().__init__("device_is_current", "This device cannot remove itself", {"device_id": device_id})


class DeviceRemovedError(DomainError):
    def __init__(self, device_id: str) -> None:
        super().__init__("device_removed", "This device was removed", {"device_id": device_id})


class DeviceExclusionInvalidError(DomainError):
    def __init__(self, device_id: str) -> None:
        super().__init__(
            "device_exclusion_invalid",
            "Only other registered devices can be left out of the new keys",
            {"device_id": device_id},
        )


class DeviceRotationIncompleteError(DomainError):
    """Keys were rotated but the new header could not be published; retry the removal."""

    def __init__(self, device_id: str, cause: str) -> None:
        super().__init__(
            "device_rotation_incomplete",
            "The device was removed but the new recovery code could not be saved; try again",
            {"device_id": device_id, "cause": cause},
        )


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DeviceService:
    def __init__(
        self,
        *,
        devices: DeviceRepositoryPort,
        vault: VaultSessionPort,
        account: TelegramAccountPort,
        transport: VaultTransportPort,
        crypto: VaultCryptoPort,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._devices = devices
        self._vault = vault
        self._account = account
        self._transport = transport
        self._crypto = crypto
        self._clock = clock
        self._removal_lock = asyncio.Lock()

    def __repr__(self) -> str:
        return "DeviceService()"

    async def list(self, *, include_removed: bool = False) -> tuple[Device, ...]:
        """Devices ordered by `added_at`; this device's `last_seen_at` is now."""
        now = self._clock()
        return tuple(
            replace(device, last_seen_at=now) if device.current else device
            for device in await self._devices.list(include_removed=include_removed)
        )

    async def rename(self, device_id: str, name: str) -> Device:
        normalized = normalize_device_name(name)
        device = await self._require(device_id)
        if not device.active:
            raise DeviceRemovedError(device_id)
        renamed = replace(device, name=normalized)
        await self._devices.save(renamed)
        return replace(renamed, last_seen_at=self._clock()) if renamed.current else renamed

    async def acknowledge(self, device_id: str) -> Device:
        """The person reviewed a device this one first saw through sync (Activity's new-device item)."""
        device = await self._require(device_id)
        if device.reviewed_at is None:
            device = replace(device, reviewed_at=self._clock())
            await self._devices.save(device)
        return replace(device, last_seen_at=self._clock()) if device.current else device

    async def removal_preview(self, device_id: str) -> tuple[Device, ...]:
        """Active devices that would receive the new keys if `device_id` were removed now (this device first)."""
        device = await self._require(device_id)
        context = await self._vault.require()
        if device.current or context.device.device_id == device_id:
            raise DeviceIsCurrentError(device_id)
        plan = await self._plan_grants(context, removed_ids={device_id})
        return plan.recipients

    async def remove(self, device_id: str, *, exclude_device_ids: Iterable[str] = ()) -> DeviceRemoval:
        async with self._removal_lock:
            device = await self._require(device_id)
            if device.current:
                raise DeviceIsCurrentError(device_id)
            context = await self._vault.require()
            if context.device.device_id == device_id:
                raise DeviceIsCurrentError(device_id)
            excluded = await self._excluded(context, device_id, exclude_device_ids)
            now = self._clock()
            if device.removed_at is None:
                device = replace(device, removed_at=now)
                await self._devices.save(device)
            for index, other in enumerate(excluded):
                if other.removed_at is None:
                    excluded[index] = replace(other, removed_at=now)
                    await self._devices.save(excluded[index])
            logger.info("removing device %s (%s more left out of the new keys)", device_id, len(excluded))
            closed = await self._close_telegram_session(device)
            recovery_code = await self._rotate(
                context, removed_device_id=device_id, also_removed={other.id for other in excluded}
            )
            return DeviceRemoval(
                device=device, telegram_session_closed=closed, recovery_code=recovery_code, excluded=tuple(excluded)
            )

    async def _excluded(self, context: VaultContext, device_id: str, device_ids: Iterable[str]) -> list[Device]:
        excluded: list[Device] = []
        for other_id in dict.fromkeys(device_ids):
            if other_id == device_id:
                continue
            other = await self._devices.get(other_id)
            if other is None or other.current or other_id == context.device.device_id:
                raise DeviceExclusionInvalidError(other_id)
            excluded.append(other)
        return excluded

    async def _require(self, device_id: str) -> Device:
        device = await self._devices.get(device_id)
        if device is None:
            raise DeviceNotFoundError(device_id)
        return device

    async def _close_telegram_session(self, device: Device) -> bool:
        try:
            matches = match_authorizations(device, await self._account.list_authorizations())
            if not matches:
                logger.info("no Telegram session matches device %s", device.id)
                return False
            for authorization in matches:
                await self._account.terminate_authorization(authorization.hash)
        except DomainError as exc:
            # `telegram_session_too_new`: Telegram only lets sessions older than 24 h close others.
            logger.info("Telegram session of device %s was not closed: %s", device.id, exc.code)
            return False
        return True

    async def _rotate(
        self, context: VaultContext, *, removed_device_id: str, also_removed: Iterable[str] = ()
    ) -> str:
        removed_device_ids = {removed_device_id, *also_removed}
        # Verified at the epoch that is still current, so the new header may keep its snapshot pointer.
        await self._vault.read_header()
        keyring = self._crypto.rotate_keyring(context.keyring)
        await self._publish_grants(context, keyring, removed_ids=removed_device_ids)
        await self._vault.update_keyring(keyring)
        recovery_code = self._crypto.generate_recovery_code()
        wrap = self._crypto.wrap_for_recovery(keyring, recovery_code)

        def mutate(header: VaultHeader) -> VaultHeader:
            return replace(header, current_epoch=keyring.current_epoch, recovery=wrap, mac=None)

        try:
            await self._vault.update_header(mutate)
        except DomainError as exc:
            logger.warning("key rotation for removed device %s left the header unchanged: %s", removed_device_id, exc.code)
            raise DeviceRotationIncompleteError(removed_device_id, exc.code) from exc
        if isinstance(self._vault, RecoveryKitRecorderPort):
            await self._vault.remember_recovery_kit(recovery_code, wrap)
        logger.info("vault keys rotated to epoch %s", keyring.current_epoch)
        return recovery_code

    async def _plan_grants(self, context: VaultContext, *, removed_ids: set[str]) -> _GrantPlan:
        """Who gets the new keys: this device and every other active, keyed device not being removed.

        Every device this registry knows as removed is listed too, so peers that missed an earlier
        removal still refuse grants from it.
        """
        keys: dict[str, bytes] = {context.device.device_id: context.device.public_key}
        recipients: list[Device] = []
        removed = set(removed_ids)
        for device in await self._devices.list(include_removed=True):
            if device.id in removed_ids:
                continue
            if device.id == context.device.device_id:
                recipients.insert(0, device)
                continue
            if not is_device_id(device.id):
                logger.warning("device %s has an invalid id; it is left out of the key grants", device.id)
                continue
            if not device.active:
                removed.add(device.id)
                continue
            try:
                keys[device.id] = decode_public_key(device.public_key)
            except ValidationFailedError:
                logger.warning("device %s has no usable public key; it gets no key grant", device.id)
                continue
            recipients.append(device)
        return _GrantPlan(recipients=tuple(recipients), keys=keys, removed=frozenset(removed))

    async def _publish_grants(self, context: VaultContext, keyring: VaultKeyring, *, removed_ids: set[str]) -> None:
        """Grants for every remaining active device, authenticated with this device's identity."""
        plan = await self._plan_grants(context, removed_ids=removed_ids)
        await self._transport.post_sync_document(
            context.layout,
            SyncMessageKind.KEYS,
            build_keys_message(self._crypto, context.device, keyring, plan.keys, removed_device_ids=plan.removed),
        )


@dataclass(frozen=True, slots=True)
class _GrantPlan:
    recipients: tuple[Device, ...]
    keys: dict[str, bytes]
    removed: frozenset[str]
