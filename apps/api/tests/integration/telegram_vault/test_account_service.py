from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bento.adapters.fake_telegram import FAKE_LOGIN_CODE, FAKE_PASSWORD
from bento.adapters.jobs import SQLiteJobQueue
from bento.application.account import AccountService
from bento.domain.account import LoginStep
from bento.domain.errors import TelegramAccountError, TelegramNotAvailableError
from bento.domain.jobs import JobType
from bento.domain.vault import VaultState
from tests.integration.telegram_vault.support import VaultDevice, make_vault_device


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


def _service(device: VaultDevice) -> tuple[AccountService, SQLiteJobQueue, list[str]]:
    jobs = SQLiteJobQueue(device.sessions, device.clock)
    changes: list[str] = []

    async def changed() -> None:
        changes.append("changed")

    return AccountService(account=lambda: device.runtime.account, jobs=jobs, on_change=changed), jobs, changes


async def _reloads(jobs: SQLiteJobQueue) -> int:
    items, _ = await jobs.list(limit=50)
    return sum(1 for job in items if job.type == JobType.ACCOUNT_RELOAD)


def test_qr_login_signs_in_and_asks_the_worker_to_reload(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_vault_device(tmp_path, tmp_path / "cloud", "desk", manual_login=True)
        service, jobs, changes = _service(device)
        assert (await service.status()).step == LoginStep.SIGNED_OUT

        pending = await service.start_qr_login()
        assert pending.step == LoginStep.QR_PENDING
        assert pending.qr_url and pending.qr_url.startswith("tg://login?token=")
        assert pending.qr_token and pending.qr_expires_at is not None
        assert (await service.start_qr_login()).qr_url == pending.qr_url  # still valid: same token

        device.cloud.approve_pending_logins()
        status = await service.status()

        assert status.step == LoginStep.AUTHORIZED and status.account is not None
        assert status.account.display_name == "Ana Demo" and status.account.phone_masked
        assert await _reloads(jobs) == 1 and changes == ["changed"]
        assert (await service.status()).authorized and await _reloads(jobs) == 1
        assert await service.avatar_jpeg()

    run(scenario())


def test_expired_qr_tokens_are_replaced_while_polling(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_vault_device(tmp_path, tmp_path / "cloud", "desk", manual_login=True, qr_ttl_seconds=0.0)
        service, _, _ = _service(device)
        first = await service.start_qr_login()
        second = await service.status()
        assert second.step == LoginStep.QR_PENDING and second.qr_url != first.qr_url

    run(scenario())


def test_phone_code_and_two_factor_password(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_vault_device(tmp_path, tmp_path / "cloud", "desk", two_factor=True)
        service, jobs, _ = _service(device)
        with pytest.raises(TelegramAccountError) as raised:
            await service.submit_code(FAKE_LOGIN_CODE)
        assert raised.value.code == "telegram_login_expired"
        assert (await service.start_phone_login("12")).error_code == "telegram_phone_invalid"

        assert (await service.start_phone_login("+57 300 000 0001")).step == LoginStep.CODE_REQUIRED
        wrong = await service.submit_code("00000")
        assert wrong.step == LoginStep.CODE_REQUIRED and wrong.error_code == "telegram_code_invalid"
        password = await service.submit_code(FAKE_LOGIN_CODE)
        assert password.step == LoginStep.PASSWORD_REQUIRED and password.password_hint == "demo"
        bad = await service.submit_password("nope")
        assert bad.step == LoginStep.PASSWORD_REQUIRED and bad.error_code == "telegram_password_invalid"
        assert await _reloads(jobs) == 0

        status = await service.submit_password(FAKE_PASSWORD)

        assert status.authorized and await _reloads(jobs) == 1

    run(scenario())


def test_logout_keeps_the_local_vault_for_the_same_account(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_vault_device(tmp_path, tmp_path / "cloud", "desk")
        service, jobs, changes = _service(device)
        await service.start_phone_login("+57 300 000 0001")
        await service.submit_code(FAKE_LOGIN_CODE)
        await device.vault.create()

        status = await service.log_out()

        assert status.step == LoginStep.SIGNED_OUT and await _reloads(jobs) == 2 and len(changes) == 2
        signed_out = await device.vault.status()
        assert signed_out.state == VaultState.SIGNED_OUT
        # A previously attached device offers to reconnect instead of the first-run welcome.
        assert signed_out.reason == "session_closed"
        assert await device.vault.current() is None
        await service.start_phone_login("+57 300 000 0001")
        await service.submit_code(FAKE_LOGIN_CODE)
        assert (await device.vault.status()).state == VaultState.READY

    run(scenario())


def test_builds_without_credentials_report_telegram_not_available() -> None:
    def unavailable() -> None:
        raise TelegramNotAvailableError()

    service = AccountService(account=unavailable)  # type: ignore[arg-type]
    with pytest.raises(TelegramNotAvailableError):
        run(service.status())
    assert run(AccountService(account=lambda: None).avatar_jpeg()) is None
    with pytest.raises(TelegramNotAvailableError):
        run(AccountService(account=lambda: None).start_qr_login())
