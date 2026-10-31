from __future__ import annotations

import base64
from datetime import timedelta
from pathlib import Path

import pytest

from bento.adapters.fake_telegram import FAKE_PASSWORD, FAKE_USER, FakeTelegramAccount, FakeTelegramCloud
from bento.domain.account import LoginStep
from bento.domain.errors import TelegramAccountError
from bento.ports.key_store import TELEGRAM_SESSION
from tests.integration.fake_telegram.support import ManualClock, make_device, run, sign_in


def test_qr_login_auto_approves_after_two_seconds(tmp_path: Path) -> None:
    async def scenario() -> None:
        clock = ManualClock()
        device = make_device(tmp_path, clock=clock)
        account = device.runtime.account

        pending = await account.start_qr_login()

        assert pending.step == LoginStep.QR_PENDING
        assert pending.qr_url is not None and pending.qr_url.startswith("tg://login?token=")
        token = pending.qr_url.removeprefix("tg://login?token=")
        assert "=" not in token
        assert base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)) == pending.qr_token
        assert pending.qr_expires_at is not None
        assert pending.qr_expires_at - FakeTelegramCloud(tmp_path, clock=clock).now() == timedelta(seconds=30)
        clock.advance(1.5)
        assert (await account.status()).step == LoginStep.QR_PENDING
        assert (await account.start_qr_login()).qr_token == pending.qr_token

        clock.advance(0.5)
        status = await account.poll_login()

        assert status.authorized
        assert status.account == FAKE_USER
        assert device.key_store.values[TELEGRAM_SESSION].startswith(b"bento-fake-session:v1:")
        assert (await account.status()).authorized

    run(scenario())


def test_manual_qr_login_waits_for_explicit_approval_and_refreshes_expired_tokens(tmp_path: Path) -> None:
    async def scenario() -> None:
        clock = ManualClock()
        account = make_device(tmp_path, clock=clock, manual_login=True).runtime.account

        first = await account.start_qr_login()
        clock.advance(31)
        assert (await account.status()).qr_token == first.qr_token
        refreshed = await account.poll_login()
        assert refreshed.step == LoginStep.QR_PENDING
        assert refreshed.qr_token != first.qr_token
        clock.advance(10)
        assert (await account.poll_login()).qr_token == refreshed.qr_token

        assert isinstance(account, FakeTelegramAccount)
        assert (await account.approve_pending_login()).authorized

    run(scenario())


def test_cloud_level_approval_is_claimed_on_next_poll(tmp_path: Path) -> None:
    async def scenario() -> None:
        clock = ManualClock()
        account = make_device(tmp_path, clock=clock, manual_login=True).runtime.account
        await account.start_qr_login()

        assert FakeTelegramCloud(tmp_path, clock=clock).approve_pending_logins() == 1
        assert FakeTelegramCloud(tmp_path, clock=clock).approve_pending_logins() == 0
        assert (await account.status()).authorized

    run(scenario())


def test_phone_login_with_code_and_optional_two_factor_password(tmp_path: Path) -> None:
    async def scenario() -> None:
        plain = make_device(tmp_path / "plain").runtime.account
        with pytest.raises(TelegramAccountError) as no_login:
            await plain.submit_code("12345")
        assert no_login.value.code == "telegram_login_expired"
        assert (await plain.start_phone_login("12")).error_code == "telegram_phone_invalid"
        assert (await plain.start_phone_login("+57 300 000 0001")).step == LoginStep.CODE_REQUIRED
        wrong = await plain.submit_code("00000")
        assert (wrong.step, wrong.error_code) == (LoginStep.CODE_REQUIRED, "telegram_code_invalid")
        assert (await plain.submit_code("123 45")).authorized

        guarded = make_device(tmp_path / "2fa", two_factor=True).runtime.account
        await guarded.start_phone_login("+57 300 000 0001")
        needs_password = await guarded.submit_code("12345")
        assert (needs_password.step, needs_password.password_hint) == (LoginStep.PASSWORD_REQUIRED, "demo")
        assert (await guarded.status()).step == LoginStep.PASSWORD_REQUIRED
        bad = await guarded.submit_password("nope")
        assert (bad.step, bad.error_code) == (LoginStep.PASSWORD_REQUIRED, "telegram_password_invalid")
        assert (await guarded.submit_password(FAKE_PASSWORD)).authorized

    run(scenario())


def test_qr_login_with_two_factor_asks_for_password_after_approval(tmp_path: Path) -> None:
    async def scenario() -> None:
        clock = ManualClock()
        device = make_device(tmp_path, clock=clock, two_factor=True)
        await device.runtime.account.start_qr_login()
        clock.advance(2)

        assert (await device.runtime.account.poll_login()).step == LoginStep.PASSWORD_REQUIRED
        assert TELEGRAM_SESSION not in device.key_store.values
        assert (await device.runtime.account.submit_password(FAKE_PASSWORD)).authorized

    run(scenario())


def test_accept_login_token_authorizes_another_instance(tmp_path: Path) -> None:
    async def scenario() -> None:
        clock = ManualClock()
        host = make_device(tmp_path, clock=clock, name="host")
        guest = make_device(tmp_path, clock=clock, name="guest", manual_login=True)
        await sign_in(host)
        pending = await guest.runtime.account.start_qr_login()
        assert pending.qr_token is not None

        accepted = await host.runtime.account.accept_login_token(pending.qr_token)

        assert accepted.authorization_hash and accepted.device_model == "guest"
        assert (await guest.runtime.account.status()).authorized
        host_view = {item.device_model: item for item in await host.runtime.account.list_authorizations()}
        assert host_view["host"].current and host_view["host"].hash == 0
        assert host_view["guest"].hash == accepted.authorization_hash and not host_view["guest"].current
        assert {"host", "guest", "Pixel 8"} == set(host_view)
        guest_view = {item.device_model: item for item in await guest.runtime.account.list_authorizations()}
        assert guest_view["guest"].hash == 0 and guest_view["host"].hash != 0
        assert (await guest.runtime.account.list_authorizations())[0].current

        for token in (pending.qr_token, b"unknown-token"):
            with pytest.raises(TelegramAccountError) as reused:
                await host.runtime.account.accept_login_token(token)
            assert reused.value.code == "telegram_login_expired"

    run(scenario())


def test_accept_login_token_rejects_expired_tokens_and_unauthorized_hosts(tmp_path: Path) -> None:
    async def scenario() -> None:
        clock = ManualClock()
        host = make_device(tmp_path, clock=clock, name="host")
        guest = make_device(tmp_path, clock=clock, name="guest", manual_login=True)
        token = (await guest.runtime.account.start_qr_login()).qr_token
        assert token is not None

        with pytest.raises(TelegramAccountError) as unauthorized:
            await host.runtime.account.accept_login_token(token)
        assert unauthorized.value.code == "telegram_not_authorized"

        await sign_in(host)
        clock.advance(30)
        with pytest.raises(TelegramAccountError) as expired:
            await host.runtime.account.accept_login_token(token)
        assert (expired.value.code, expired.value.details) == ("telegram_login_expired", {"reason": "expired"})

    run(scenario())


def test_terminate_authorization_signs_the_other_instance_out(tmp_path: Path) -> None:
    async def scenario() -> None:
        host = make_device(tmp_path, name="host")
        guest = make_device(tmp_path, name="guest")
        await sign_in(host)
        await sign_in(guest)
        guest_hash = next(
            item.hash for item in await host.runtime.account.list_authorizations() if item.device_model == "guest"
        )

        await host.runtime.account.terminate_authorization(guest_hash)

        assert (await guest.runtime.account.status()).step == LoginStep.SIGNED_OUT
        with pytest.raises(TelegramAccountError) as signed_out:
            await guest.runtime.transport.find_vaults()
        assert signed_out.value.code == "telegram_not_authorized"
        for unknown in (guest_hash, 0):
            with pytest.raises(TelegramAccountError) as missing:
                await host.runtime.account.terminate_authorization(unknown)
            assert missing.value.code == "telegram_authorization_not_found"
        assert [item.device_model for item in await host.runtime.account.list_authorizations()] == ["host", "Pixel 8"]

    run(scenario())


def test_fresh_sessions_can_be_configured_to_refuse_terminating_others(tmp_path: Path) -> None:
    async def scenario() -> None:
        host = make_device(tmp_path, name="host", session_too_new=True)
        await sign_in(host)
        phone = next(item for item in await host.runtime.account.list_authorizations() if not item.current)

        with pytest.raises(TelegramAccountError) as refused:
            await host.runtime.account.terminate_authorization(phone.hash)

        assert refused.value.code == "telegram_session_too_new"


    run(scenario())


def test_the_simulated_phone_still_approves_qr_logins_after_its_session_is_terminated(tmp_path: Path) -> None:
    async def scenario() -> None:
        clock = ManualClock()
        host = make_device(tmp_path, clock=clock, name="host")
        await sign_in(host)
        phone = next(item for item in await host.runtime.account.list_authorizations() if not item.current)
        await host.runtime.account.terminate_authorization(phone.hash)
        guest = make_device(tmp_path, clock=clock, name="guest")

        await guest.runtime.account.start_qr_login()
        clock.advance(2)

        assert (await guest.runtime.account.poll_login()).authorized

    run(scenario())


def test_log_out_removes_the_authorization_and_the_stored_session(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_device(tmp_path)
        assert await device.runtime.account.avatar_jpeg() is None
        await sign_in(device)
        avatar = await device.runtime.account.avatar_jpeg()
        assert avatar is not None and avatar.startswith(b"\xff\xd8") and avatar.endswith(b"\xff\xd9")

        await device.runtime.account.log_out()

        assert (await device.runtime.account.status()).step == LoginStep.SIGNED_OUT
        assert TELEGRAM_SESSION not in device.key_store.values
        assert [item.device_model for item in FakeTelegramCloud(tmp_path).authorizations()] == ["Pixel 8"]
        await device.runtime.account.log_out()

    run(scenario())


def test_sessions_from_other_backends_are_ignored(tmp_path: Path) -> None:
    async def scenario() -> None:
        device = make_device(tmp_path)
        await device.key_store.put(TELEGRAM_SESSION, b"1BVtsOK8Bu5...telethon-string-session")

        assert (await device.runtime.account.status()).step == LoginStep.SIGNED_OUT

    run(scenario())
