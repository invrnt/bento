from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class LoginStep(StrEnum):
    SIGNED_OUT = "signed_out"
    QR_PENDING = "qr_pending"
    CODE_REQUIRED = "code_required"
    PASSWORD_REQUIRED = "password_required"
    AUTHORIZED = "authorized"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TelegramAccount:
    user_id: int
    display_name: str
    username: str | None = None
    phone_masked: str | None = None
    premium: bool = False


@dataclass(frozen=True, slots=True)
class AccountStatus:
    """Login state of this device's Telegram session.

    `qr_token` is the raw login token behind `qr_url`; it is only used by the pairing
    flow and must never be serialized to HTTP clients.
    """

    step: LoginStep
    account: TelegramAccount | None = None
    qr_url: str | None = None
    qr_token: bytes | None = None
    qr_expires_at: datetime | None = None
    password_hint: str | None = None
    error_code: str | None = None
    retry_after_seconds: int | None = None

    @property
    def authorized(self) -> bool:
        return self.step == LoginStep.AUTHORIZED and self.account is not None


@dataclass(frozen=True, slots=True)
class TelegramAuthorization:
    hash: int
    device_model: str
    platform: str
    app_name: str
    created_at: datetime | None
    last_active_at: datetime | None
    current: bool = False


@dataclass(frozen=True, slots=True)
class AcceptedLogin:
    authorization_hash: int | None
    device_model: str | None = None
