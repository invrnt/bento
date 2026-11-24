"""`bento setup`: the one command a person runs. Resumable from any step.

start/locate Bento → Telegram sign-in → create the vault (first device) or join it (pairing code, Sync
fallback, or recovery code) → backup suggestions. Off a TTY (or with --json) it never prompts: it performs
only the steps whose inputs were given and returns the current `step` with the `next` commands.
"""

from __future__ import annotations

from typing import Any

from bento.interfaces.cli.catalog import Command, arg
from bento.interfaces.cli.commands.account import login_flow
from bento.interfaces.cli.commands.pairing import follow_guest, join_flow
from bento.interfaces.cli.commands.vault import create_vault, unlock_vault
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.errors import CliError
from bento.interfaces.cli.output import Output

MAX_STEPS = 8
NEXT = {
    "telegram_login": ["bento login", "bento join CODE"],
    "create_vault": ["bento vault create"],
    "join_vault": ["bento join CODE", "bento pair request", "bento vault unlock --recovery-code CODE"],
}


def _interactive(ctx: Context) -> bool:
    return ctx.out.interactive and not ctx.out.json_mode


def _choose_unlock(ctx: Context) -> str:
    ctx.out.line(ctx.t("setup.locked_intro"))
    ctx.out.line(ctx.t("setup.locked_option_code"))
    ctx.out.line(ctx.t("setup.locked_option_request"))
    ctx.out.line(ctx.t("setup.locked_option_recovery"))
    while True:
        answer = ctx.out.prompt(ctx.t("setup.locked_choice")).strip()
        if answer in {"1", "2", "3"}:
            return answer


def _offer_backups(ctx: Context) -> list[dict[str, Any]]:
    added: list[dict[str, Any]] = []
    try:
        existing = {source.get("path") for source in ctx.api.get("/backup/sources").get("items") or []}
        suggestions = [item for item in ctx.api.get("/backup/suggestions").get("items") or [] if item.get("path") not in existing]
    except CliError:
        return added
    if not suggestions:
        return added
    ctx.out.line("")
    ctx.out.line(ctx.t("setup.backup_intro"))
    for item in suggestions:
        if ctx.out.confirm(ctx.t("setup.backup_question", label=item.get("label"), path=item.get("path"))):
            try:
                added.append(ctx.api.post("/backup/sources", {"path": item["path"], "label": item.get("label")}))
            except CliError as error:
                ctx.out.note(ctx.t.error_message(error.code, error.message, error.details))
    return added


def setup(ctx: Context) -> int:
    args = ctx.args
    target = ctx.target
    health = ctx.api.get("/health")
    done: list[str] = []
    document: dict[str, Any] = {"target": target.public(), "storage_backend": health.get("storage_backend"), "done": done}
    if _interactive(ctx):
        ctx.out.line(ctx.t("setup.welcome"))
        ctx.out.line(ctx.t("setup.target", kind=ctx.t("target." + target.kind), url=target.url))
    if health.get("storage_backend") == "local":
        document.update({"step": "local_only", "complete": True, "next": [], "vault": ctx.api.get("/vault")})
        ctx.out.result(document, lambda out, _: out.line(out.t("setup.local_only")))
        return 0

    join_code: str | None = args.join
    recovery_code: str | None = args.recovery_code
    step = "ready"
    vault: dict[str, Any] = {}
    for _ in range(MAX_STEPS):
        vault = dict(ctx.api.get("/vault"))
        state = vault.get("state")
        if state in {"ready", "bootstrapping", "local_only"}:
            step = "ready"
            break
        if state == "signed_out":
            if join_code:
                join_flow(ctx, join_code)
                done.append("joined")
                join_code = None
                continue
            if not _interactive(ctx) and not args.phone:
                step = "telegram_login"
                break
            if _interactive(ctx):
                ctx.out.line(ctx.t("setup.login_intro"))
            login_flow(ctx, phone=args.phone, code=args.code, wait=True, timeout=ctx.flag("timeout"))
            done.append("signed_in")
            continue
        if state == "no_vault":
            if not _interactive(ctx):
                step = "create_vault"
                break
            ctx.out.line(ctx.t("setup.no_vault_intro"))
            if not ctx.out.confirm(ctx.t("setup.create_question"), default=True):
                step = "create_vault"
                break
            create_vault(ctx)
            done.append("vault_created")
            continue
        if state == "locked":
            if join_code:
                join_flow(ctx, join_code)
                done.append("joined")
                join_code = None
                continue
            if recovery_code:
                unlock_vault(ctx, recovery_code)
                done.append("unlocked")
                recovery_code = None
                continue
            if not _interactive(ctx):
                step = "join_vault"
                break
            choice = _choose_unlock(ctx)
            if choice == "1":
                join_code = ctx.out.prompt(ctx.t("setup.code_prompt")).strip()
            elif choice == "2":
                pairing = dict(ctx.api.post("/pairing/request"))
                ctx.out.note(ctx.t("pair.request_sent"))
                follow_guest(ctx, pairing, fallback=True)
                done.append("joined")
            else:
                unlock_vault(ctx, None)
                done.append("unlocked")
            continue
        step = str(state)
        break

    complete = step == "ready"
    document.update({"step": step, "complete": complete, "next": NEXT.get(step, []), "vault": vault})
    if complete and _interactive(ctx) and not args.no_backup:
        document["backup_added"] = _offer_backups(ctx)
    ctx.out.result(document, _render)
    return 0


def _render(out: Output, data: dict[str, Any]) -> None:
    if data["complete"]:
        out.line(out.t("setup.ready"))
        out.line(out.t("setup.ready_hint"))
        return
    out.line(out.t(f"setup.step.{data['step']}"))
    for command in data["next"]:
        out.line(f"  {command}")


COMMANDS = (
    Command(
        ("setup",),
        "Guided setup: sign in, create or join your vault, backups",
        "Configuración guiada: inicia sesión, crea o únete a tu bóveda, respaldos",
        setup,
        (
            arg("--phone", en="Sign in with this phone number instead of QR", es="Inicia sesión con este teléfono en vez del QR", metavar="NUMBER"),
            arg("--code", en="Telegram login code (with --phone)", es="Código de Telegram (con --phone)", metavar="CODE"),
            arg("--join", en="Pairing code from another device", es="Código de vinculación de otro dispositivo", metavar="CODE"),
            arg("--recovery-code", en="Unlock with the recovery code", es="Desbloquea con el código de recuperación", metavar="CODE"),
            arg("--no-backup", en="Do not offer backup folders", es="No ofrece carpetas para respaldar", action="store_true"),
        ),
        output="SetupState",
    ),
)
