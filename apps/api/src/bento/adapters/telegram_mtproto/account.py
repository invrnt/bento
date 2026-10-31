"""`TelegramAccountPort` over Telethon: QR login (refreshed automatically), phone code, 2FA, sessions.

Recoverable input mistakes come back as an `AccountStatus` on the same step with `error_code`; calls made in the
wrong state raise `TelegramAccountError('telegram_login_expired')`. The pending login lives in this process
(the API); a QR token is renewed shortly before it expires while `QRLogin.wait` runs in a background task.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from telethon import errors, functions

from bento.adapters.telegram_mtproto.errors import map_telethon_error
from bento.adapters.telegram_mtproto.session import MtprotoSession
from bento.domain.account import AcceptedLogin, AccountStatus, LoginStep, TelegramAuthorization
from bento.domain.errors import DomainError, TelegramAccountError, TelegramFloodWaitError

LOGGER = logging.getLogger("bento.telegram.account")

QR_REFRESH_MARGIN_SECONDS = 3.0
_RECOVERABLE = {"telegram_flood_wait", "telegram_network"}


class MtprotoTelegramAccount:
    def __init__(self, session: MtprotoSession, *, now: Callable[[], datetime] | None = None) -> None:
        self._session = session
        self._now = now or (lambda: datetime.now(UTC))
        self._step = LoginStep.SIGNED_OUT
        self._qr: Any = None
        self._qr_task: asyncio.Task[None] | None = None
        self._phone: str | None = None
        self._phone_code_hash: str | None = None
        self._password_hint: str | None = None
        self._error: tuple[str, int | None] | None = None

    @property
    def session(self) -> MtprotoSession:
        return self._session

    async def status(self) -> AccountStatus:
        account = await self._session.account()
        if account is not None:
            await self._reset()
            return AccountStatus(step=LoginStep.AUTHORIZED, account=account)
        return self._pending_status()

    async def start_qr_login(self) -> AccountStatus:
        status = await self.status()
        if status.authorized:
            return status
        if self._step == LoginStep.QR_PENDING and self._qr is not None and not self._qr_expired():
            self._ensure_qr_task()
            return self._pending_status()
        await self._reset()
        client = await self._session.client()
        try:
            self._qr = await self._session.call(lambda current: current.qr_login(), authorized=False)
        except TelegramFloodWaitError as exc:
            return AccountStatus(
                step=LoginStep.SIGNED_OUT, error_code=exc.code, retry_after_seconds=exc.retry_after_seconds
            )
        self._step = LoginStep.QR_PENDING
        self._ensure_qr_task(client)
        return self._pending_status()

    async def poll_login(self) -> AccountStatus:
        status = await self.status()
        if status.authorized:
            return status
        if self._step == LoginStep.QR_PENDING and self._qr is not None:
            if self._qr_expired():
                await self._recreate_qr()
            self._ensure_qr_task()
        return self._pending_status()

    async def start_phone_login(self, phone: str) -> AccountStatus:
        status = await self.status()
        if status.authorized:
            return status
        await self._reset()
        if len(re.sub(r"\D", "", phone)) < 5:
            return AccountStatus(step=LoginStep.SIGNED_OUT, error_code="telegram_phone_invalid")

        async def send(client: Any) -> Any:
            try:
                return await client.send_code_request(phone)
            except (errors.PhoneNumberInvalidError, errors.PhoneNumberBannedError, errors.PhoneNumberUnoccupiedError):
                return None

        try:
            sent = await self._session.call(send, authorized=False)
        except DomainError as exc:
            if exc.code in _RECOVERABLE:
                return _error_status(LoginStep.SIGNED_OUT, exc)
            raise
        if sent is None:
            return AccountStatus(step=LoginStep.SIGNED_OUT, error_code="telegram_phone_invalid")
        self._phone = phone
        self._phone_code_hash = getattr(sent, "phone_code_hash", None)
        self._step = LoginStep.CODE_REQUIRED
        return self._pending_status()

    async def submit_code(self, code: str) -> AccountStatus:
        if self._step != LoginStep.CODE_REQUIRED or self._phone is None:
            raise TelegramAccountError("telegram_login_expired", "No phone login is in progress")
        phone, phone_code_hash = self._phone, self._phone_code_hash
        cleaned = re.sub(r"\s", "", code)

        async def sign_in(client: Any) -> Any:
            try:
                return await client.sign_in(phone=phone, code=cleaned, phone_code_hash=phone_code_hash)
            except errors.PhoneCodeInvalidError:
                return _CODE_INVALID
            except errors.PhoneCodeExpiredError:
                return _CODE_EXPIRED
            except errors.SessionPasswordNeededError:
                return _PASSWORD_NEEDED
            except errors.PhoneNumberUnoccupiedError:
                return _PHONE_INVALID

        try:
            result = await self._session.call(sign_in, authorized=False)
        except DomainError as exc:
            if exc.code in _RECOVERABLE:
                return _error_status(LoginStep.CODE_REQUIRED, exc)
            raise
        if result is _CODE_INVALID:
            return AccountStatus(step=LoginStep.CODE_REQUIRED, error_code="telegram_code_invalid")
        if result is _CODE_EXPIRED:
            await self._reset()
            raise TelegramAccountError("telegram_login_expired", "The login code expired", {"reason": "expired"})
        if result is _PHONE_INVALID:
            await self._reset()
            return AccountStatus(step=LoginStep.SIGNED_OUT, error_code="telegram_phone_invalid")
        if result is _PASSWORD_NEEDED:
            await self._require_password()
            return self._pending_status()
        return await self._finish()

    async def submit_password(self, password: str) -> AccountStatus:
        if self._step != LoginStep.PASSWORD_REQUIRED:
            raise TelegramAccountError("telegram_login_expired", "No password is being requested")

        async def check(client: Any) -> Any:
            try:
                return await client.sign_in(password=password)
            except errors.PasswordHashInvalidError:
                return _PASSWORD_INVALID

        try:
            result = await self._session.call(check, authorized=False)
        except DomainError as exc:
            if exc.code in _RECOVERABLE:
                return _error_status(LoginStep.PASSWORD_REQUIRED, exc, hint=self._password_hint)
            raise
        if result is _PASSWORD_INVALID:
            return AccountStatus(
                step=LoginStep.PASSWORD_REQUIRED,
                password_hint=self._password_hint,
                error_code="telegram_password_invalid",
            )
        return await self._finish()

    async def accept_login_token(self, token: bytes) -> AcceptedLogin:
        async def accept(client: Any) -> Any:
            try:
                return await client(functions.auth.AcceptLoginTokenRequest(token=token))
            except errors.AuthTokenExpiredError:
                return "expired"
            except errors.AuthTokenAlreadyAcceptedError:
                return "already_accepted"
            except errors.AuthTokenInvalidError:
                return "invalid"

        result = await self._session.call(accept)
        if isinstance(result, str):
            raise TelegramAccountError(
                "telegram_login_expired", "The Telegram login token is no longer valid", {"reason": result}
            )
        return AcceptedLogin(authorization_hash=getattr(result, "hash", None), device_model=getattr(result, "device_model", None))

    async def list_authorizations(self) -> tuple[TelegramAuthorization, ...]:
        """Telegram lists the current session with hash 0 (`current=True`)."""
        result = await self._session.call(lambda client: client(functions.account.GetAuthorizationsRequest()))
        items = [
            TelegramAuthorization(
                hash=int(item.hash),
                device_model=str(item.device_model or ""),
                platform=str(item.platform or ""),
                app_name=str(item.app_name or ""),
                created_at=item.date_created,
                last_active_at=item.date_active,
                current=bool(item.current),
            )
            for item in getattr(result, "authorizations", ())
        ]
        return tuple(sorted(items, key=lambda item: (not item.current, -_timestamp(item.created_at))))

    async def terminate_authorization(self, authorization_hash: int) -> None:
        if authorization_hash == 0:
            raise TelegramAccountError("telegram_authorization_not_found", "Telegram session not found")

        async def reset(client: Any) -> str | None:
            try:
                await client(functions.account.ResetAuthorizationRequest(hash=authorization_hash))
            except errors.FreshResetAuthorisationForbiddenError:
                return "telegram_session_too_new"
            except errors.HashInvalidError:
                return "telegram_authorization_not_found"
            return None

        failure = await self._session.call(reset)
        if failure == "telegram_session_too_new":
            raise TelegramAccountError(failure, "This session is too new to sign out other devices")
        if failure is not None:
            raise TelegramAccountError(failure, "Telegram session not found")

    async def log_out(self) -> None:
        await self._reset()
        try:
            if await self._session.account() is not None:
                await self._session.call(lambda client: client.log_out())
        except DomainError as exc:
            # The local session is dropped anyway; Telegram expires unused authorizations on its own.
            LOGGER.warning("Telegram log out did not reach Telegram: %s", exc.code)
        finally:
            await self._session.forget()

    async def avatar_jpeg(self) -> bytes | None:
        if await self._session.account() is None:
            return None
        photo = await self._session.call(lambda client: client.download_profile_photo("me", file=bytes))
        return bytes(photo) if photo else None

    # Internals

    def _ensure_qr_task(self, client: Any = None) -> None:
        if self._qr_task is not None and not self._qr_task.done():
            return
        self._qr_task = asyncio.create_task(self._wait_for_qr(client))

    async def _wait_for_qr(self, client: Any) -> None:
        qr = self._qr
        while self._step == LoginStep.QR_PENDING and qr is self._qr and qr is not None:
            remaining = (qr.expires - self._now()).total_seconds() - QR_REFRESH_MARGIN_SECONDS
            try:
                user = await qr.wait(timeout=max(1.0, remaining))
            except (TimeoutError, asyncio.TimeoutError):
                if not await self._recreate_qr():
                    return
                qr = self._qr
                continue
            except errors.SessionPasswordNeededError:
                await self._require_password()
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - surfaced through the status
                mapped = map_telethon_error(exc)
                self._qr = None
                self._step = LoginStep.FAILED
                self._error = (mapped.code if mapped is not None else "telegram_login_expired", None)
                return
            del user
            current = client or await self._session.client()
            await self._session.save_session(current)
            self._qr = None
            self._step = LoginStep.AUTHORIZED
            return

    async def _recreate_qr(self) -> bool:
        qr = self._qr
        if qr is None:
            return False
        try:
            await self._session.call(lambda _client: qr.recreate(), authorized=False)
        except DomainError as exc:
            self._error = (exc.code, getattr(exc, "retry_after_seconds", None))
            return False
        self._error = None
        return True

    async def _require_password(self) -> None:
        self._qr = None
        self._step = LoginStep.PASSWORD_REQUIRED
        try:
            password = await self._session.call(
                lambda client: client(functions.account.GetPasswordRequest()), authorized=False
            )
            self._password_hint = getattr(password, "hint", None) or None
        except DomainError:
            self._password_hint = None

    async def _finish(self) -> AccountStatus:
        client = await self._session.client()
        await self._session.save_session(client)
        await self._reset()
        account = await self._session.account()
        if account is None:
            raise TelegramAccountError("telegram_login_expired", "Telegram did not complete the login")
        return AccountStatus(step=LoginStep.AUTHORIZED, account=account)

    async def _reset(self) -> None:
        task, self._qr_task = self._qr_task, None
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._qr = None
        self._step = LoginStep.SIGNED_OUT
        self._phone = None
        self._phone_code_hash = None
        self._password_hint = None
        self._error = None

    def _qr_expired(self) -> bool:
        return self._qr is None or self._qr.expires <= self._now()

    def _pending_status(self) -> AccountStatus:
        code, retry_after = self._error if self._error is not None else (None, None)
        if self._step == LoginStep.QR_PENDING and self._qr is not None:
            return AccountStatus(
                step=LoginStep.QR_PENDING,
                qr_url=self._qr.url,
                qr_token=self._qr.token,
                qr_expires_at=self._qr.expires,
                error_code=code,
                retry_after_seconds=retry_after,
            )
        if self._step == LoginStep.PASSWORD_REQUIRED:
            return AccountStatus(step=LoginStep.PASSWORD_REQUIRED, password_hint=self._password_hint)
        if self._step == LoginStep.CODE_REQUIRED:
            return AccountStatus(step=LoginStep.CODE_REQUIRED)
        if self._step == LoginStep.FAILED:
            return AccountStatus(step=LoginStep.FAILED, error_code=code or "telegram_login_expired")
        return AccountStatus(step=LoginStep.SIGNED_OUT, error_code=code, retry_after_seconds=retry_after)


_CODE_INVALID = object()
_CODE_EXPIRED = object()
_PASSWORD_NEEDED = object()
_PASSWORD_INVALID = object()
_PHONE_INVALID = object()


def _error_status(step: LoginStep, exc: DomainError, *, hint: str | None = None) -> AccountStatus:
    return AccountStatus(
        step=step,
        password_hint=hint,
        error_code=exc.code,
        retry_after_seconds=exc.retry_after_seconds if isinstance(exc, TelegramFloodWaitError) else None,
    )


def _timestamp(value: datetime | None) -> float:
    return value.timestamp() if value is not None else 0.0
