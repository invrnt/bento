"""Vault lifecycle and the recovery kit. A recovery code is printed only by the command that created it."""

from __future__ import annotations

from typing import Any

from bento.interfaces.cli.catalog import Command, arg
from bento.interfaces.cli.commands.common import date_text, require_value
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.output import Output, human_size


def render_vault(out: Output, vault: dict[str, Any]) -> None:
    usage = vault.get("usage") or {}
    pairs: list[tuple[str, Any]] = [(out.t("vault.state"), out.t(f"vault.state.{vault.get('state')}"))]
    if vault.get("vault_id"):
        pairs += [
            (out.t("col.created"), date_text(vault.get("created_at"))),
            (out.t("status.devices"), vault.get("devices_count")),
            (out.t("status.files"), f"{usage.get('files', 0)} · {human_size(usage.get('bytes', 0), out.lang)}"),
            (out.t("vault.kit"), out.t("vault.kit_saved") if vault.get("recovery_kit_saved") else out.t("vault.kit_missing")),
        ]
    out.fields(pairs)
    if vault.get("recovery_kit_stale"):
        out.line(out.t("vault.kit_stale"))
    if vault.get("reason"):
        out.line(out.t(f"vault.reason.{vault['reason']}"))


def show_recovery_code(ctx: Context, code: str, qr: dict[str, Any] | None) -> None:
    from bento.interfaces.cli.commands.account import show_qr

    if ctx.out.json_mode:
        return
    ctx.out.line("")
    ctx.out.line(ctx.t("recovery.title"))
    ctx.out.line("")
    ctx.out.line(f"    {code}")
    ctx.out.line("")
    ctx.out.line(ctx.t("recovery.explain"))
    if ctx.out.interactive:
        show_qr(ctx, qr, title=ctx.t("recovery.qr_title"))


def confirm_kit(ctx: Context, code: str) -> dict[str, Any] | None:
    """On a TTY, ask for the last group to prove the code was written down."""
    if not ctx.out.interactive or ctx.out.json_mode:
        return None
    expected = code.rsplit("-", 1)[-1]
    for _ in range(3):
        answer = ctx.out.prompt(ctx.t("recovery.confirm_prompt")).strip().upper()
        if not answer:
            ctx.out.note(ctx.t("recovery.confirm_later"))
            return None
        if answer == expected.upper():
            return dict(ctx.api.post("/vault/recovery-code/confirm", {"last_group": answer}))
        ctx.out.note(ctx.t("recovery.confirm_mismatch"))
    ctx.out.note(ctx.t("recovery.confirm_later"))
    return None


def create_vault(ctx: Context) -> dict[str, Any]:
    created = dict(ctx.api.post("/vault"))
    show_recovery_code(ctx, str(created["recovery_code"]), created.get("recovery_qr"))
    confirmed = confirm_kit(ctx, str(created["recovery_code"]))
    if confirmed is not None:
        created["vault"] = confirmed
    return created


def status(ctx: Context) -> int:
    ctx.out.result(ctx.api.get("/vault"), render_vault)
    return 0


def create(ctx: Context) -> int:
    created = create_vault(ctx)
    ctx.out.result(created, lambda out, data: out.line(out.t("vault.created")))
    return 0


def unlock_vault(ctx: Context, code: str | None) -> dict[str, Any]:
    value = require_value(ctx, code, prompt_key="vault.recovery_prompt", flag="--recovery-code", secret=True)
    return dict(ctx.api.post("/vault/unlock", {"recovery_code": value.strip()}))


def unlock(ctx: Context) -> int:
    vault = unlock_vault(ctx, ctx.args.recovery_code)
    ctx.out.result(vault, render_vault)
    return 0


def rotate(ctx: Context) -> int:
    ctx.require_confirmation("vault recovery rotate", ctx.t("recovery.confirm_rotate"))
    data = dict(ctx.api.post("/vault/recovery-code"))
    show_recovery_code(ctx, str(data["recovery_code"]), data.get("recovery_qr"))
    confirm_kit(ctx, str(data["recovery_code"]))
    ctx.out.result(data, lambda out, _: out.line(out.t("recovery.rotated")))
    return 0


def verify(ctx: Context) -> int:
    data = ctx.api.post("/vault/recovery-code/verify", {"recovery_code": ctx.args.code.strip()})
    ctx.out.result(data, lambda out, doc: out.line(out.t("recovery.valid" if doc.get("valid") else "recovery.invalid")))
    return 0 if data.get("valid") else 1


def confirm(ctx: Context) -> int:
    vault = ctx.api.post("/vault/recovery-code/confirm", {"last_group": ctx.args.last_group.strip()})
    ctx.out.result(vault, lambda out, _: out.line(out.t("recovery.confirmed")))
    return 0


COMMANDS = (
    Command(("vault",), "Your encrypted cloud (vault)", "Tu nube cifrada (bóveda)", default_child="status"),
    Command(("vault", "status"), "Vault state", "Estado de la bóveda", status, output="VaultStatus"),
    Command(("vault", "create"), "Create the vault (prints the recovery code once)", "Crea la bóveda (muestra el código de recuperación una vez)", create, output="CreatedVault"),
    Command(
        ("vault", "unlock"),
        "Unlock this device with the recovery code",
        "Desbloquea este dispositivo con el código de recuperación",
        unlock,
        (arg("--recovery-code", en="Recovery code (prompted on a TTY)", es="Código de recuperación (se pide en la terminal)", metavar="CODE"),),
        output="VaultStatus",
    ),
    Command(("vault", "recovery"), "Recovery kit", "Kit de recuperación"),
    Command(("vault", "recovery", "rotate"), "Generate a new recovery code (old one stops working)", "Genera un código nuevo (el anterior deja de servir)", rotate, output="RecoveryCode"),
    Command(
        ("vault", "recovery", "verify"),
        "Check a recovery code (exit 1 when invalid)",
        "Comprueba un código de recuperación (sale con 1 si no vale)",
        verify,
        (arg("code", en="Recovery code", es="Código de recuperación", metavar="CODE"),),
        output="RecoveryVerify",
    ),
    Command(
        ("vault", "recovery", "confirm"),
        "Mark the kit as saved (last group of the code)",
        "Marca el kit como guardado (último grupo del código)",
        confirm,
        (arg("last_group", en="Last group of the code", es="Último grupo del código", metavar="LAST_GROUP"),),
        output="VaultStatus",
    ),
)
