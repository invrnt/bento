"""Telegram sign-in of this device (API process).

Login runs in the API process; after the session changes the worker is asked to reload (`account_reload`).
Logging out keeps the local library and keys, which simply stops sync until the account signs in again.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from bento.domain.account import AccountStatus, LoginStep
from bento.domain.errors import TelegramNotAvailableError
from bento.domain.jobs import JobPriority, JobType
from bento.ports.jobs import JobQueuePort
from bento.ports.telegram import TelegramAccountPort

AccountResolver = Callable[[], TelegramAccountPort | None]
ChangeListener = Callable[[], Awaitable[None]]


class AccountService:
    """HTTP-facing sign-in flow. Recoverable input mistakes come back as `AccountStatus.error_code`."""

    def __init__(
        self,
        *,
        account: AccountResolver,
        jobs: JobQueuePort | None = None,
        on_change: ChangeListener | None = None,
    ) -> None:
        self._resolve = account
        self._jobs = jobs
        self._on_change = on_change
        self._authorized: bool | None = None

    async def status(self) -> AccountStatus:
        """Advance a pending login (a new QR token replaces an expired one) and report the state."""
        return await self._observe(await self._account().poll_login())

    async def start_qr_login(self) -> AccountStatus:
        return await self._observe(await self._account().start_qr_login())

    async def start_phone_login(self, phone: str) -> AccountStatus:
        return await self._observe(await self._account().start_phone_login(phone))

    async def submit_code(self, code: str) -> AccountStatus:
        return await self._observe(await self._account().submit_code(code))

    async def submit_password(self, password: str) -> AccountStatus:
        return await self._observe(await self._account().submit_password(password))

    async def log_out(self) -> AccountStatus:
        await self._account().log_out()
        self._authorized = False
        await self._changed()
        return AccountStatus(step=LoginStep.SIGNED_OUT)

    async def avatar_jpeg(self) -> bytes | None:
        account = self._resolve()
        if account is None:
            return None
        return await account.avatar_jpeg()

    def _account(self) -> TelegramAccountPort:
        account = self._resolve()
        if account is None:
            raise TelegramNotAvailableError()
        return account

    async def _observe(self, status: AccountStatus) -> AccountStatus:
        authorized = status.authorized
        previous, self._authorized = self._authorized, authorized
        # Only a login observed by this process is a change; an already signed-in session at startup is not.
        if authorized and previous is False:
            await self._changed()
        return status

    async def _changed(self) -> None:
        if self._jobs is not None:
            await self._jobs.enqueue(
                type=JobType.ACCOUNT_RELOAD, priority=int(JobPriority.BLOB_ASSET), payload={}, max_attempts=1
            )
        if self._on_change is not None:
            await self._on_change()


FLOOD_WAIT_UNTIL_KEY = "telegram.flood_wait_until"
"""`sync_state` key: ISO time until which Telegram asked this device to wait (written for waits over a minute)."""
