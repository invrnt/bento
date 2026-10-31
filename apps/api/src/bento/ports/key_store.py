from __future__ import annotations

from typing import Protocol

TELEGRAM_SESSION = "telegram.session"
VAULT_KEYRING = "vault.keyring"
DEVICE_IDENTITY = "device.identity"


class KeyStorePort(Protocol):
    """Secret material created at runtime. Values are encrypted at rest and never leave the backend."""

    async def get(self, name: str) -> bytes | None: ...

    async def put(self, name: str, value: bytes) -> None: ...

    async def delete(self, name: str) -> None: ...
