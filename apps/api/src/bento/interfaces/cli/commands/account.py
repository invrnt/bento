"""Account: status, login (QR or phone), logout, whoami."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from bento.interfaces.cli.catalog import Command, arg
from bento.interfaces.cli.commands.common import require_value
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.errors import EXIT_SETUP_REQUIRED, SETUP_NEXT, CliError, usage
from bento.interfaces.cli.output import Output, is_tty
from bento.interfaces.cli.qr import render_qr

POLL_SECONDS = 2.0
SETUP_STATES = ("signed_out", "no_vault", "locked")


# Rendering -----------------------------------------------------------------------------------


def show_qr(ctx: Context, qr: dict[str, Any] | None, *, title: str, hint: str | None = None) -> None:
    """QR on stdout for humans; on stderr (TTY only) in JSON mode so stdout stays one document."""
    if not qr:
        return
    stream = ctx.out.stderr if ctx.out.json_mode else ctx.out.stdout
    if ctx.out.json_mode and not is_tty(stream):
        return
    ansi = is_tty(stream) and not ctx.environ.get("NO_COLOR")
    stream.write(f"\n{title}\n\n{render_qr(qr, ansi=ansi)}\n\n")
    if hint:
        stream.write(hint + "\n")
    stream.flush()


def account_label(account: dict[str, Any] | None) -> str:
    if not account:
        return "-"
    name = str(account.get("display_name") or "")
    if account.get("username"):
        name += f" (@{account['username']})"
    if account.get("phone_masked"):
        name += f"  {account['phone_masked']}"
    return name.strip() or str(account.get("user_id"))


# Status --------------------------------------------------------------------------------------


def _safe(ctx: Context, path: str) -> Any:
    try:
        return ctx.api.get(path)
    except CliError as error:
        if error.exit_code == 5:
            raise
        return {"error": error.to_json()["error"]}


def setup_state(health: dict[str, Any], account: Any, vault: Any) -> dict[str, Any]:
    """Whether this instance still needs `bento setup`, and why."""
    if health.get("storage_backend") == "local":
        return {"required": False, "reason": None, "next": None}
    account_error = (account or {}).get("error") if isinstance(account, dict) else None
    if isinstance(account_error, dict) and account_error.get("code") == "telegram_not_available":
        return {"required": True, "reason": "telegram_not_available", "next": SETUP_NEXT["telegram_not_available"]}
    state = (vault or {}).get("state") if isinstance(vault, dict) else None
    if state in SETUP_STATES:
        return {"required": True, "reason": state, "next": SETUP_NEXT[str(state)]}
    return {"required": False, "reason": None, "next": None}


def status(ctx: Context) -> int:
    health = ctx.api.get("/health")
    version = _safe(ctx, "/version")
    account = _safe(ctx, "/account") if health.get("storage_backend") != "local" else None
    vault = _safe(ctx, "/vault")
    sync = _safe(ctx, "/sync/status")
    activity = _safe(ctx, "/activity")
    document = {
        "target": ctx.target.public(),
        "version": version,
        "storage_backend": health.get("storage_backend"),
        "account": account,
        "vault": vault,
        "sync": sync,
        "activity": activity,
        "setup": setup_state(health, account, vault),
    }
    ctx.out.result(document, _render_status)
    return EXIT_SETUP_REQUIRED if document["setup"]["required"] else 0


def _render_status(out: Output, data: dict[str, Any]) -> None:
    from bento.interfaces.cli.commands.sync import render_activity

    target = data["target"]
    version = data.get("version") or {}
    vault = data.get("vault") or {}
    account = data.get("account") or {}
    sync = data.get("sync") or {}
    pairs: list[tuple[str, Any]] = [
        (out.t("status.target"), f"{out.t('target.' + target['kind'])} · {target['url']} · v{version.get('version', '?')}"),
        (out.t("status.storage"), out.t(f"storage.{data.get('storage_backend')}")),
    ]
    if data.get("storage_backend") != "local":
        pairs.append((out.t("status.account"), account_label(account.get("account")) if not account.get("error") else out.t.error_message(account["error"]["code"], account["error"]["message"], {})))
    if not vault.get("error"):
        usage_info = vault.get("usage") or {}
        pairs.append((out.t("status.vault"), out.t(f"vault.state.{vault.get('state')}")))
        if vault.get("state") == "ready":
            from bento.interfaces.cli.output import human_size

            pairs.append((out.t("status.files"), f"{usage_info.get('files', 0)} · {human_size(usage_info.get('bytes', 0), out.lang)}"))
            pairs.append((out.t("status.devices"), vault.get("devices_count")))
    if not sync.get("error"):
        pairs.append((out.t("status.sync"), out.t(f"sync.state.{sync.get('state')}")))
    out.fields(pairs)
    activity = data.get("activity") or {}
    if activity and not activity.get("error"):
        render_activity(out, activity)
    setup = data["setup"]
    if setup["required"]:
        out.line("")
        out.line(out.t(f"setup.reason.{setup['reason']}"))
        out.line(out.t("error.next", command=setup["next"]))


# Login ---------------------------------------------------------------------------------------


def _account_error(status: dict[str, Any]) -> CliError:
    error = status.get("error") or {}
    code = str(error.get("code") or "telegram_login_failed")
    return CliError(code, str(error.get("message") or "Telegram sign-in failed"), dict(error.get("details") or {}))


def _expired(status: dict[str, Any]) -> bool:
    expires = status.get("qr_expires_at")
    if not isinstance(expires, str):
        return False
    try:
        return datetime.fromisoformat(expires.replace("Z", "+00:00")) <= datetime.now(UTC)
    except ValueError:
        return False


def _password(ctx: Context, status: dict[str, Any], *, from_stdin: bool) -> dict[str, Any]:
    if from_stdin:
        password = ctx.out.stdin.readline().rstrip("\r\n")
        if not password:
            raise usage("--password-stdin received an empty line")
    else:
        hint = status.get("password_hint")
        if hint:
            ctx.out.note(ctx.t("login.password_hint", hint=hint))
        password = require_value(ctx, None, prompt_key="login.password_prompt", flag="--password-stdin", secret=True)
    return dict(ctx.api.post("/account/login/password", {"password": password}))


def login_flow(
    ctx: Context,
    *,
    phone: str | None = None,
    code: str | None = None,
    password_stdin: bool = False,
    wait: bool = True,
    timeout: float | None = None,
) -> dict[str, Any]:
    status = dict(ctx.api.get("/account"))
    if status.get("step") == "authorized":
        return status
    if code and status.get("step") == "code_required" and not phone:
        status = dict(ctx.api.post("/account/login/code", {"code": code}))
    elif phone:
        status = dict(ctx.api.post("/account/login/phone", {"phone": phone}))
        if status.get("step") == "code_required":
            ctx.out.note(ctx.t("login.code_sent"))
            entered = require_value(ctx, code, prompt_key="login.code_prompt", flag="--code")
            status = dict(ctx.api.post("/account/login/code", {"code": entered.strip()}))
    else:
        # Resume a QR login that is still valid (e.g. after `login --no-wait`) instead of replacing it.
        if not (status.get("step") == "qr_pending" and status.get("qr_url") and not _expired(status)):
            status = dict(ctx.api.post("/account/login/qr"))
        show_qr(ctx, status.get("qr"), title=ctx.t("login.qr_title"), hint=ctx.t("login.qr_hint"))
        if not wait:
            return status
        deadline = time.monotonic() + (timeout if timeout is not None else 300.0)
        shown = status.get("qr_url")
        while status.get("step") == "qr_pending":
            if time.monotonic() >= deadline:
                raise CliError("telegram_login_expired", "The QR login timed out", {"next": "bento login"})
            time.sleep(POLL_SECONDS)
            status = dict(ctx.api.get("/account"))
            if status.get("step") == "qr_pending" and (_expired(status) or not status.get("qr_url")):
                status = dict(ctx.api.post("/account/login/qr"))
            if status.get("step") == "qr_pending" and status.get("qr_url") != shown:
                shown = status.get("qr_url")
                show_qr(ctx, status.get("qr"), title=ctx.t("login.qr_refreshed"))
            if status.get("step") == "signed_out":
                status = dict(ctx.api.post("/account/login/qr"))
    if status.get("step") == "password_required":
        status = _password(ctx, status, from_stdin=password_stdin)
    if status.get("step") == "failed" or (status.get("error") and status.get("step") != "authorized"):
        raise _account_error(status)
    if status.get("step") == "code_required":
        raise CliError("telegram_code_required", "Telegram is waiting for the login code", {"next": "bento login --code CODE"}, EXIT_SETUP_REQUIRED)
    if status.get("step") == "password_required":
        raise CliError("telegram_password_required", "Telegram needs the 2FA password", {"next": "bento login --password-stdin"}, EXIT_SETUP_REQUIRED)
    return status


def login(ctx: Context) -> int:
    args = ctx.args
    if args.password_stdin and is_tty(ctx.out.stdin):
        ctx.out.note(ctx.t("login.password_stdin_tty"))
    status = login_flow(
        ctx,
        phone=args.phone,
        code=args.code,
        password_stdin=bool(args.password_stdin),
        wait=not args.no_wait,
        timeout=ctx.flag("timeout"),
    )
    ctx.out.result(status, _render_login)
    return 0


def _render_login(out: Output, status: dict[str, Any]) -> None:
    if status.get("step") == "authorized":
        out.line(out.t("login.done", account=account_label(status.get("account"))))
    else:
        out.line(out.t("login.pending", step=status.get("step")))


def logout(ctx: Context) -> int:
    ctx.require_confirmation("logout", ctx.t("logout.confirm"))
    status = ctx.api.post("/account/logout")
    ctx.out.result(status, lambda out, _: out.line(out.t("logout.done")))
    return 0


def whoami(ctx: Context) -> int:
    status = ctx.api.get("/account")
    if status.get("step") != "authorized" or not status.get("account"):
        raise CliError("signed_out", "This Bento is not signed in to Telegram", {})
    ctx.out.result(status["account"], lambda out, account: out.line(account_label(account)))
    return 0


COMMANDS = (
    Command(("status",), "One-screen summary (exit 6 when setup is required)", "Resumen en una pantalla (sale con 6 si falta configurar)", status, output="Status"),
    Command(
        ("login",),
        "Sign in to Telegram (QR by default, or --phone)",
        "Inicia sesión en Telegram (QR por defecto, o --phone)",
        login,
        (
            arg("--phone", en="Phone number with country code", es="Teléfono con código de país", metavar="NUMBER"),
            arg("--code", en="Login code Telegram sent you", es="Código que te envió Telegram", metavar="CODE"),
            arg("--password-stdin", en="Read the 2FA password from stdin", es="Lee la contraseña 2FA de stdin", action="store_true"),
            arg("--no-wait", en="Start the QR login and return it", es="Inicia el QR y lo devuelve sin esperar", action="store_true"),
        ),
        output="AccountStatus",
    ),
    Command(("logout",), "Sign out of Telegram (keeps the local library)", "Cierra la sesión de Telegram (conserva la biblioteca local)", logout, output="AccountStatus"),
    Command(("whoami",), "The signed-in Telegram account", "La cuenta de Telegram conectada", whoami, output="TelegramAccount"),
)
