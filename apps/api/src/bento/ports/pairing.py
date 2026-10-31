from __future__ import annotations

from typing import Protocol

from bento.domain.devices import Device
from bento.domain.pairing import PairingRole


class PairingChannelPort(Protocol):
    """An open relay room. Binary frames are opaque to the relay."""

    async def wait_for_peer(self, timeout_seconds: float) -> bool: ...

    async def send(self, frame: bytes) -> None: ...

    async def receive(self, timeout_seconds: float) -> bytes:
        """Raises `PairingError('pairing_peer_left'|'pairing_timeout'|'pairing_expired', ...)`."""
        ...

    async def close(self) -> None: ...


class PairingRelayPort(Protocol):
    async def available(self) -> bool: ...

    async def open_room(self, nameplate: str, role: PairingRole) -> PairingChannelPort:
        """Raises `PairingError('pairing_nameplate_taken'|'pairing_room_not_found'|'pairing_relay_unavailable', ...)`."""
        ...


class DeviceRepositoryPort(Protocol):
    async def list(self, *, include_removed: bool = False) -> tuple[Device, ...]: ...

    async def get(self, device_id: str) -> Device | None: ...

    async def save(self, device: Device) -> None:
        """Persists the synced device entity; change capture emits the `device` op."""
        ...
