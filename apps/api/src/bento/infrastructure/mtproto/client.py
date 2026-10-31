"""Telethon client construction for this device."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from telethon import TelegramClient
from telethon.sessions import StringSession

from bento.infrastructure.mtproto.config import ClientIdentity, TelegramAppCredentials

TELETHON_LOGGER = "bento.telethon"
IdentityProvider = Callable[[], Awaitable[ClientIdentity]]


class TelethonClientFactory:
    """`ClientFactory`: an in-memory `StringSession` copy per process, announced as `Bento (<device suffix>)`.

    Flood waits are never slept inside Telethon (`flood_sleep_threshold=0`); `FloodWaitPolicy` owns them.
    """

    def __init__(
        self,
        credentials: TelegramAppCredentials,
        identity: IdentityProvider,
        *,
        receive_updates: bool = True,
        client_class: Callable[..., Any] = TelegramClient,
    ) -> None:
        self._credentials = credentials
        self._identity = identity
        self._receive_updates = receive_updates
        self._client_class = client_class
        logging.getLogger(TELETHON_LOGGER).setLevel(logging.WARNING)

    async def __call__(self, session_string: str) -> Any:
        identity = await self._identity()
        return self._client_class(
            StringSession(session_string or None),
            self._credentials.api_id,
            self._credentials.api_hash,
            device_model=identity.device_model,
            system_version=identity.system_version,
            app_version=identity.app_version,
            flood_sleep_threshold=0,
            receive_updates=self._receive_updates,
            catch_up=False,
            base_logger=TELETHON_LOGGER,
        )
