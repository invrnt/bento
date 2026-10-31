from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from bento.domain.account import TelegramAccount
from bento.domain.security import DeviceIdentity, VaultKeyring
from bento.domain.vault import VaultHeader, VaultLayout, VaultStatus


@dataclass(frozen=True, slots=True)
class VaultContext:
    layout: VaultLayout
    keyring: VaultKeyring
    device: DeviceIdentity
    account: TelegramAccount


class VaultSessionPort(Protocol):
    """Unlocked vault state of this device, shared by sync, pairing, storage, and inbox services."""

    async def status(self) -> VaultStatus: ...

    async def current(self) -> VaultContext | None:
        """None when local-only, signed out, without vault, or locked."""
        ...

    async def require(self) -> VaultContext:
        """Raises `VaultLockedError`, `VaultNotFoundError`, or `TelegramAccountError('telegram_not_authorized', ...)`."""
        ...

    async def device_identity(self) -> DeviceIdentity:
        """This device's identity; created and persisted in the key store on first use."""
        ...

    async def install(self, layout: VaultLayout, keyring: VaultKeyring) -> VaultStatus:
        """Persist a granted keyring and layout (pairing guest, recovery), register this device, start bootstrap."""
        ...

    async def update_keyring(self, keyring: VaultKeyring) -> None:
        """Persist a rotated or received keyring. Must contain every older epoch."""
        ...

    async def read_header(self) -> VaultHeader | None:
        """Latest pinned header; MAC-verified when a keyring is available (invalid MAC → None)."""
        ...

    async def update_header(self, mutate: Callable[[VaultHeader], VaultHeader]) -> VaultHeader:
        """Read the latest header, apply `mutate`, MAC with the current keyring, publish, and return it.

        Nothing is published when the header does not change. After publishing, older header messages are deleted
        (best effort): they carry the keyring wrapped by superseded recovery codes.
        """
        ...
