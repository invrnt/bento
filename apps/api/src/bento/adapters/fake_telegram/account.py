"""`TelegramAccountPort` over the fake cloud.

Recoverable input mistakes (wrong code/password, malformed phone) come back as an `AccountStatus` on the same
step with `error_code`; calls made in the wrong state or without a session raise `TelegramAccountError`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from bento.adapters.fake_telegram import media
from bento.adapters.fake_telegram.cloud import PHONE_AUTHORIZATION_ID, FakeLoginToken
from bento.adapters.fake_telegram.options import FAKE_LOGIN_CODE, FAKE_PASSWORD, FAKE_PASSWORD_HINT
from bento.adapters.fake_telegram.session import FakeTelegramSession
from bento.domain.account import AcceptedLogin, AccountStatus, LoginStep, TelegramAuthorization
from bento.domain.errors import TelegramAccountError

_FRESH_SESSION = timedelta(hours=24)
_AVATAR_COLORS = [(42, 157, 143), (233, 196, 106), (244, 162, 97), (231, 111, 81)]


@dataclass(frozen=True, slots=True)
class _PendingLogin:
    step: LoginStep
    token: FakeLoginToken | None = None
    authorization_id: str | None = None


class FakeTelegramAccount:
    def __init__(self, session: FakeTelegramSession) -> None:
        self._session = session
        self._cloud = session.cloud
        self._options = session.options
        self._pending: _PendingLogin | None = None

    async def status(self) -> AccountStatus:
        return await self._advance(refresh=False)

    async def start_qr_login(self) -> AccountStatus:
        if await self._session.authorization_id() is not None:
            return await self._advance(refresh=False)
        pending = self._pending
        if pending is None or pending.step != LoginStep.QR_PENDING or self._expired(pending.token):
            await self._issue_qr()
        return await self._advance(refresh=True)

    async def poll_login(self) -> AccountStatus:
        return await self._advance(refresh=True)

    async def start_phone_login(self, phone: str) -> AccountStatus:
        if await self._session.authorization_id() is not None:
            return await self._advance(refresh=False)
        await self._discard_qr()
        if len(re.sub(r"\D", "", phone)) < 5:
            self._pending = None
            return AccountStatus(step=LoginStep.SIGNED_OUT, error_code="telegram_phone_invalid")
        self._pending = _PendingLogin(step=LoginStep.CODE_REQUIRED)
        return AccountStatus(step=LoginStep.CODE_REQUIRED)

    async def submit_code(self, code: str) -> AccountStatus:
        if self._pending is None or self._pending.step != LoginStep.CODE_REQUIRED:
            raise TelegramAccountError("telegram_login_expired", "No phone login is in progress")
        if re.sub(r"\s", "", code) != FAKE_LOGIN_CODE:
            return AccountStatus(step=LoginStep.CODE_REQUIRED, error_code="telegram_code_invalid")
        authorization = await self._session.run(self._cloud.create_authorization, self._options)
        return await self._finish(authorization.id)

    async def submit_password(self, password: str) -> AccountStatus:
        pending = self._pending
        if pending is None or pending.step != LoginStep.PASSWORD_REQUIRED or pending.authorization_id is None:
            raise TelegramAccountError("telegram_login_expired", "No password is being requested")
        if password != FAKE_PASSWORD:
            return replace(self._pending_status(pending), error_code="telegram_password_invalid")
        await self._session.store(pending.authorization_id)
        self._pending = None
        return await self._advance(refresh=False)

    async def accept_login_token(self, token: bytes) -> AcceptedLogin:
        authorization_id = await self._session.require()
        accepted = await self._session.run(self._cloud.approve_login_token, token, authorization_id)
        return AcceptedLogin(authorization_hash=accepted.hash, device_model=accepted.device_model)

    async def list_authorizations(self) -> tuple[TelegramAuthorization, ...]:
        """Like Telegram, the current session is reported with hash 0."""
        current_id = await self._session.require()
        records = await self._session.run(self._cloud.authorizations)
        items = [
            TelegramAuthorization(
                hash=0 if record.id == current_id else record.hash,
                device_model=record.device_model,
                platform=record.platform,
                app_name=record.app_name,
                created_at=record.created_at,
                last_active_at=record.last_active_at,
                current=record.id == current_id,
            )
            for record in records
        ]
        return tuple(sorted(items, key=lambda item: (not item.current, -_timestamp(item.created_at))))

    async def terminate_authorization(self, authorization_hash: int) -> None:
        current_id = await self._session.require()
        current = await self._session.run(self._cloud.authorization, current_id)
        if self._options.session_too_new and current is not None and self._cloud.now() - current.created_at < _FRESH_SESSION:
            raise TelegramAccountError(
                "telegram_session_too_new", "This session is too new to sign out other devices"
            )
        removed = None
        if authorization_hash != 0:
            removed = await self._session.run(self._cloud.remove_authorization, authorization_hash=authorization_hash)
        if removed is None:
            raise TelegramAccountError("telegram_authorization_not_found", "Telegram session not found")

    async def log_out(self) -> None:
        authorization_id = await self._session.authorization_id()
        if authorization_id is not None:
            await self._session.run(self._cloud.remove_authorization, authorization_id=authorization_id)
        await self._discard_qr()
        self._pending = None
        await self._session.clear()

    async def avatar_jpeg(self) -> bytes | None:
        if await self._session.authorization_id() is None:
            return None
        return media.jpeg_bytes(96, 96, _AVATAR_COLORS)

    async def approve_pending_login(self) -> AccountStatus:
        """Fake only: approve this instance's QR as if the phone scanned it."""
        pending = self._pending
        if pending is not None and pending.step == LoginStep.QR_PENDING and pending.token is not None:
            await self._session.run(self._cloud.approve_login_token, pending.token.token, PHONE_AUTHORIZATION_ID)
        return await self._advance(refresh=False)

    async def _advance(self, *, refresh: bool) -> AccountStatus:
        if await self._session.authorization_id() is not None:
            self._pending = None
            return AccountStatus(step=LoginStep.AUTHORIZED, account=self._cloud.user)
        pending = self._pending
        if pending is None:
            return AccountStatus(step=LoginStep.SIGNED_OUT)
        if pending.step != LoginStep.QR_PENDING or pending.token is None:
            return self._pending_status(pending)
        token = pending.token
        record = await self._session.run(self._cloud.login_token, token.token)
        auto_approve = record is not None and record.approved_authorization_id is None and not self._options.manual_login
        if auto_approve and record is not None and not self._expired(record):
            if (self._cloud.now() - record.created_at).total_seconds() >= self._options.auto_approve_seconds:
                await self._session.run(self._cloud.approve_login_token, token.token, PHONE_AUTHORIZATION_ID)
        approved_id = await self._session.run(self._cloud.claim_login_token, token.token)
        if approved_id is not None:
            return await self._finish(approved_id)
        if refresh and (record is None or self._expired(token)):
            await self._issue_qr()
        return self._pending_status(self._pending or pending)

    async def _finish(self, authorization_id: str) -> AccountStatus:
        if self._options.two_factor:
            self._pending = _PendingLogin(step=LoginStep.PASSWORD_REQUIRED, authorization_id=authorization_id)
            return self._pending_status(self._pending)
        await self._session.store(authorization_id)
        self._pending = None
        return AccountStatus(step=LoginStep.AUTHORIZED, account=self._cloud.user)

    async def _issue_qr(self) -> None:
        await self._discard_qr()
        token = await self._session.run(self._cloud.issue_login_token, self._options)
        self._pending = _PendingLogin(step=LoginStep.QR_PENDING, token=token)

    async def _discard_qr(self) -> None:
        if self._pending is not None and self._pending.token is not None:
            await self._session.run(self._cloud.discard_login_token, self._pending.token.token)

    def _pending_status(self, pending: _PendingLogin) -> AccountStatus:
        if pending.step == LoginStep.QR_PENDING and pending.token is not None:
            return AccountStatus(
                step=LoginStep.QR_PENDING,
                qr_url=pending.token.url,
                qr_token=pending.token.token,
                qr_expires_at=pending.token.expires_at,
            )
        if pending.step == LoginStep.PASSWORD_REQUIRED:
            return AccountStatus(step=LoginStep.PASSWORD_REQUIRED, password_hint=FAKE_PASSWORD_HINT)
        return AccountStatus(step=pending.step)

    def _expired(self, token: FakeLoginToken | None) -> bool:
        return token is None or token.expires_at <= self._cloud.now()


def _timestamp(value: datetime | None) -> float:
    return value.timestamp() if value is not None else 0.0
