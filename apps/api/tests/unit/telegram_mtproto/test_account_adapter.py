from __future__ import annotations

import asyncio

import pytest
from telethon import errors, functions

from bento.adapters.telegram_mtproto.account import MtprotoTelegramAccount
from bento.domain.account import LoginStep
from bento.domain.errors import TelegramAccountError
from bento.ports.key_store import TELEGRAM_SESSION
from tests.unit.telegram_mtproto.fake_telethon import NOW, FakeTelethonClient, fail_on, make_session


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


def _account(client: FakeTelethonClient | None = None) -> tuple[MtprotoTelegramAccount, FakeTelethonClient, object]:
    client = client or FakeTelethonClient()
    session, store = make_session(client)
    return MtprotoTelegramAccount(session, now=lambda: NOW), client, store


def test_qr_login_completes_in_the_background_and_stores_the_session() -> None:
    async def scenario() -> None:
        account, client, store = _account()

        pending = await account.start_qr_login()

        assert pending.step == LoginStep.QR_PENDING and pending.qr_url == "tg://login?token=qr-token-1"
        assert pending.qr_token == b"qr-token-1" and pending.qr_expires_at is not None
        assert (await account.poll_login()).step == LoginStep.QR_PENDING
        await client.qr_outcome.put("scanned")
        for _ in range(20):
            await asyncio.sleep(0)
        status = await account.status()

        assert status.step == LoginStep.AUTHORIZED and status.account is not None
        assert status.qr_url is None and status.qr_token is None
        assert await store.get(TELEGRAM_SESSION) == b"1fake-session-after-login"  # type: ignore[attr-defined]

    run(scenario())


def test_qr_tokens_are_recreated_before_they_expire() -> None:
    async def scenario() -> None:
        account, client, _ = _account()
        await account.start_qr_login()
        await client.qr_outcome.put(asyncio.TimeoutError())
        for _ in range(20):
            await asyncio.sleep(0)

        status = await account.poll_login()

        assert status.step == LoginStep.QR_PENDING and status.qr_url == "tg://login?token=qr-token-2"
        await account.log_out()

    run(scenario())


def test_qr_login_with_two_factor_asks_for_the_password() -> None:
    async def scenario() -> None:
        account, client, _ = _account()
        await account.start_qr_login()
        await client.qr_outcome.put(errors.SessionPasswordNeededError(request=None))
        for _ in range(20):
            await asyncio.sleep(0)

        status = await account.status()
        assert status.step == LoginStep.PASSWORD_REQUIRED and status.password_hint == "perro"
        client.sign_in_results = [errors.PasswordHashInvalidError(request=None)]
        wrong = await account.submit_password("nope")
        assert wrong.step == LoginStep.PASSWORD_REQUIRED and wrong.error_code == "telegram_password_invalid"

        assert (await account.submit_password("right")).authorized
        assert client.calls_of("sign_in")[-1]["password"] is True

    run(scenario())


def test_phone_login_maps_code_errors_and_flood_waits() -> None:
    async def scenario() -> None:
        account, client, _ = _account()
        with pytest.raises(TelegramAccountError) as raised:
            await account.submit_code("12345")
        assert raised.value.code == "telegram_login_expired"
        assert (await account.start_phone_login("12")).error_code == "telegram_phone_invalid"
        client.failures = [fail_on("send_code_request", errors.FloodWaitError(request=None, capture=90))]
        flooded = await account.start_phone_login("+57 300 123 4512")
        assert flooded.error_code == "telegram_flood_wait" and flooded.retry_after_seconds == 90
        client.failures = [fail_on("send_code_request", errors.PhoneNumberInvalidError(request=None))]
        assert (await account.start_phone_login("+57 300 123 4512")).error_code == "telegram_phone_invalid"

        assert (await account.start_phone_login("+57 300 123 4512")).step == LoginStep.CODE_REQUIRED
        client.sign_in_results = [errors.PhoneCodeInvalidError(request=None)]
        wrong = await account.submit_code("1 2 3 4 5")
        assert wrong.step == LoginStep.CODE_REQUIRED and wrong.error_code == "telegram_code_invalid"
        assert client.calls_of("sign_in")[-1] == {
            "phone": "+57 300 123 4512", "code": "12345", "phone_code_hash": "code-hash", "password": False
        }
        client.sign_in_results = [errors.SessionPasswordNeededError(request=None)]
        assert (await account.submit_code("12345")).step == LoginStep.PASSWORD_REQUIRED
        assert (await account.submit_password("secret")).authorized

    run(scenario())


def test_expired_phone_codes_restart_the_login() -> None:
    async def scenario() -> None:
        account, client, _ = _account()
        await account.start_phone_login("+57 300 123 4512")
        client.sign_in_results = [errors.PhoneCodeExpiredError(request=None)]
        with pytest.raises(TelegramAccountError) as raised:
            await account.submit_code("12345")
        assert raised.value.code == "telegram_login_expired" and raised.value.details == {"reason": "expired"}
        assert (await account.status()).step == LoginStep.SIGNED_OUT

    run(scenario())


def test_accepting_another_devices_login_token() -> None:
    async def scenario() -> None:
        client = FakeTelethonClient("1signed-in")
        account, _, _ = _account(client)

        accepted = await account.accept_login_token(b"guest-token")

        [request] = client.requests_of(functions.auth.AcceptLoginTokenRequest)
        assert request.token == b"guest-token"
        assert accepted.authorization_hash == 99 and accepted.device_model == "Bento (abc123)"
        client.accept_result = errors.AuthTokenExpiredError(request=None)
        with pytest.raises(TelegramAccountError) as raised:
            await account.accept_login_token(b"old")
        assert raised.value.code == "telegram_login_expired" and raised.value.details == {"reason": "expired"}
        client.accept_result = errors.AuthTokenAlreadyAcceptedError(request=None)
        with pytest.raises(TelegramAccountError) as raised:
            await account.accept_login_token(b"old")
        assert raised.value.details == {"reason": "already_accepted"}

    run(scenario())


def test_authorizations_list_and_termination() -> None:
    async def scenario() -> None:
        client = FakeTelethonClient("1signed-in")
        account, _, _ = _account(client)

        listed = await account.list_authorizations()

        assert [(item.hash, item.current, item.device_model) for item in listed] == [
            (0, True, "Bento (def456)"),
            (99, False, "Bento (abc123)"),
        ]
        await account.terminate_authorization(99)
        [reset] = client.requests_of(functions.account.ResetAuthorizationRequest)
        assert reset.hash == 99
        with pytest.raises(TelegramAccountError) as raised:
            await account.terminate_authorization(0)
        assert raised.value.code == "telegram_authorization_not_found"
        client.failures = [fail_on("ResetAuthorizationRequest", errors.FreshResetAuthorisationForbiddenError(request=None))]
        with pytest.raises(TelegramAccountError) as raised:
            await account.terminate_authorization(99)
        assert raised.value.code == "telegram_session_too_new"
        client.failures = [fail_on("ResetAuthorizationRequest", errors.HashInvalidError(request=None))]
        with pytest.raises(TelegramAccountError) as raised:
            await account.terminate_authorization(5)
        assert raised.value.code == "telegram_authorization_not_found"

    run(scenario())


def test_avatar_and_logout() -> None:
    async def scenario() -> None:
        client = FakeTelethonClient("1signed-in")
        account, _, store = _account(client)
        await store.put(TELEGRAM_SESSION, b"1signed-in")  # type: ignore[attr-defined]

        assert await account.avatar_jpeg() == b"\xff\xd8avatar"
        await account.log_out()

        assert client.calls_of("log_out") == [{}]
        assert await store.get(TELEGRAM_SESSION) is None  # type: ignore[attr-defined]
        assert (await account.status()).step == LoginStep.SIGNED_OUT
        assert await account.avatar_jpeg() is None

    run(scenario())
