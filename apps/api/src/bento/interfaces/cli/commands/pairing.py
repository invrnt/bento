"""Stremio-like pairing: `bento pair` on a device that has the vault, `bento join CODE` on the new one."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from bento.interfaces.cli.catalog import Command, arg
from bento.interfaces.cli.commands.account import show_qr
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.errors import EXIT_USAGE, CliError
from bento.interfaces.cli.output import Output, human_date

POLL_SECONDS = 1.0
TERMINAL_FAILURES = frozenset({"rejected", "failed", "expired", "cancelled"})
AFTER_APPROVAL_SECONDS = 600.0


def _pid(value: str) -> str:
    return value[3:] if value.startswith("id:") else value


def pairing_error(pairing: dict[str, Any]) -> CliError:
    state = str(pairing.get("state"))
    error = pairing.get("error") or {}
    code = str(error.get("code") or f"pairing_{state}")
    message = str(error.get("message") or f"Pairing {state}")
    return CliError(code, message, {"pairing_id": pairing.get("id"), "state": state}, 4)


def _expires_in(pairing: dict[str, Any]) -> float:
    try:
        expires = datetime.fromisoformat(str(pairing.get("expires_at")).replace("Z", "+00:00"))
    except ValueError:
        return 300.0
    return max(5.0, (expires - datetime.now(UTC)).total_seconds() + 5.0)


def sas_text(pairing: dict[str, Any]) -> str:
    return "   ".join(pairing.get("sas") or [])


# Rendering -----------------------------------------------------------------------------------


def render_pairing(out: Output, pairing: dict[str, Any]) -> None:
    pairs: list[tuple[str, Any]] = [
        ("id", pairing.get("id")),
        (out.t("pair.state"), out.t(f"pair.state.{pairing.get('state')}")),
    ]
    if pairing.get("code"):
        pairs.append((out.t("pair.code"), pairing["code"]))
    if pairing.get("peer"):
        pairs.append((out.t("pair.peer"), pairing["peer"].get("device_name")))
    if pairing.get("sas"):
        pairs.append((out.t("pair.sas"), sas_text(pairing)))
    if pairing.get("error"):
        pairs.append((out.t("sync.error"), out.t.error_message(pairing["error"].get("code", ""), pairing["error"].get("message", ""), {})))
    pairs.append((out.t("pair.expires"), human_date(pairing.get("expires_at"))))
    out.fields(pairs)


def _announce_code(ctx: Context, pairing: dict[str, Any]) -> None:
    if ctx.out.json_mode:
        ctx.out.event("pairing_code", {key: pairing.get(key) for key in ("id", "code", "link", "web_link", "expires_at")})
        show_qr(ctx, pairing.get("qr"), title=ctx.t("pair.qr_title"))
        return
    ctx.out.line(ctx.t("pair.code_title"))
    ctx.out.line("")
    ctx.out.line(f"    {pairing.get('code')}")
    ctx.out.line("")
    ctx.out.line(ctx.t("pair.code_how", code=pairing.get("code")))
    if pairing.get("web_link"):
        ctx.out.line(ctx.t("pair.web_link", link=pairing["web_link"]))
    if pairing.get("link"):
        ctx.out.line(ctx.t("pair.link", link=pairing["link"]))
    show_qr(ctx, pairing.get("qr"), title=ctx.t("pair.qr_title"))
    ctx.out.line(ctx.t("pair.expires_at", time=human_date(pairing.get("expires_at"))))


# Host ----------------------------------------------------------------------------------------


def follow_host(ctx: Context, pairing: dict[str, Any], *, approve: bool) -> dict[str, Any]:
    pairing_id = str(pairing["id"])
    deadline = time.monotonic() + _expires_in(pairing)
    announced_sas = False
    waiting_note = False
    while True:
        state = pairing.get("state")
        if state == "completed":
            return pairing
        if state in TERMINAL_FAILURES:
            raise pairing_error(pairing)
        if state == "awaiting_approval" and pairing.get("sas"):
            if not announced_sas:
                peer = (pairing.get("peer") or {}).get("device_name", "?")
                ctx.out.note(ctx.t("pair.peer_connected", peer=peer))
                ctx.out.note(ctx.t("pair.sas_host", sas=sas_text(pairing)))
                ctx.out.event("pairing_sas", {"id": pairing_id, "sas": pairing.get("sas"), "peer": pairing.get("peer")})
                announced_sas = True
            if approve:
                pairing = dict(ctx.api.post(f"/pairing/{pairing_id}/approve"))
                deadline = time.monotonic() + AFTER_APPROVAL_SECONDS
                continue
            if ctx.out.interactive and not ctx.out.json_mode:
                if ctx.out.confirm(ctx.t("pair.sas_question")):
                    pairing = dict(ctx.api.post(f"/pairing/{pairing_id}/approve"))
                    deadline = time.monotonic() + AFTER_APPROVAL_SECONDS
                else:
                    pairing = dict(ctx.api.post(f"/pairing/{pairing_id}/reject"))
                continue
            raise CliError(
                "confirmation_required",
                "The other device is waiting: compare the emojis and approve",
                {"pairing_id": pairing_id, "sas": pairing.get("sas"), "peer": pairing.get("peer"), "next": f"bento pair approve {pairing_id}"},
                EXIT_USAGE,
            )
        elif not waiting_note and state == "waiting":
            ctx.out.note(ctx.t("pair.waiting_guest"))
            waiting_note = True
        if time.monotonic() >= deadline:
            raise CliError("pairing_expired", "The pairing code expired", {"pairing_id": pairing_id, "next": "bento pair --wait"}, 4)
        time.sleep(POLL_SECONDS)
        pairing = dict(ctx.api.get(f"/pairing/{pairing_id}"))


def pair_host(ctx: Context) -> int:
    pairing = dict(ctx.api.post("/pairing/host"))
    _announce_code(ctx, pairing)
    if ctx.args.wait or ctx.args.approve:
        pairing = follow_host(ctx, pairing, approve=bool(ctx.args.approve))
        ctx.out.result(pairing, lambda out, data: out.line(out.t("pair.host_done", peer=(data.get("peer") or {}).get("device_name", "?"))))
        return 0
    ctx.out.result(pairing, lambda out, data: out.note(out.t("pair.follow_hint", id=data["id"])))
    return 0


# Guest ---------------------------------------------------------------------------------------


def follow_guest(ctx: Context, pairing: dict[str, Any], *, fallback: bool = False) -> dict[str, Any]:
    pairing_id = str(pairing["id"])
    deadline = time.monotonic() + _expires_in(pairing)
    shown_sas = False
    shown_qr: Any = None
    last_progress: Any = None
    while True:
        state = pairing.get("state")
        if state == "completed":
            return pairing
        if state in TERMINAL_FAILURES:
            raise pairing_error(pairing)
        if state == "awaiting_approval" and pairing.get("sas") and not shown_sas:
            shown_sas = True
            ctx.out.event("pairing_sas", {"id": pairing_id, "sas": pairing.get("sas"), "peer": pairing.get("peer")})
            if fallback:
                ctx.out.note(ctx.t("pair.sas_fallback", sas=sas_text(pairing)))
                if ctx.out.interactive and not ctx.out.json_mode:
                    if ctx.out.confirm(ctx.t("pair.sas_question")):
                        pairing = dict(ctx.api.post(f"/pairing/{pairing_id}/confirm"))
                    else:
                        pairing = dict(ctx.api.delete(f"/pairing/{pairing_id}"))
                    continue
                raise CliError(
                    "confirmation_required",
                    "Compare the emojis with the other device, then confirm",
                    {"pairing_id": pairing_id, "sas": pairing.get("sas"), "next": f"bento pair confirm {pairing_id}"},
                    EXIT_USAGE,
                )
            ctx.out.note(ctx.t("pair.sas_guest", sas=sas_text(pairing)))
        if state == "needs_telegram_login" and pairing.get("telegram_qr") and pairing.get("telegram_qr") != shown_qr:
            shown_qr = pairing.get("telegram_qr")
            ctx.out.event("login_qr", {"pairing_id": pairing_id, "qr": shown_qr})
            show_qr(ctx, shown_qr, title=ctx.t("pair.telegram_login_title"), hint=ctx.t("login.qr_hint"))
            deadline = time.monotonic() + AFTER_APPROVAL_SECONDS
        if state in {"approving", "bootstrapping"}:
            deadline = max(deadline, time.monotonic() + 60.0)
            if state == "bootstrapping":
                progress = _bootstrap_progress(ctx)
                if progress and progress != last_progress:
                    ctx.out.note(ctx.t("pair.bootstrapping", done=progress[0], total=progress[1]))
                    last_progress = progress
        if time.monotonic() >= deadline:
            raise CliError("pairing_expired", "The pairing timed out", {"pairing_id": pairing_id}, 4)
        time.sleep(POLL_SECONDS)
        pairing = dict(ctx.api.get(f"/pairing/{pairing_id}"))


def _bootstrap_progress(ctx: Context) -> tuple[int, int] | None:
    try:
        sync = ctx.api.get("/sync/status")
    except CliError:
        return None
    bootstrap = sync.get("bootstrap") if isinstance(sync, dict) else None
    if not bootstrap:
        return None
    return int(bootstrap.get("done", 0)), int(bootstrap.get("total", 0))


def join_flow(ctx: Context, code: str, *, wait: bool = True) -> dict[str, Any]:
    pairing = dict(ctx.api.post("/pairing/join", {"code": code.strip()}))
    if not wait:
        return pairing
    ctx.out.note(ctx.t("pair.joining"))
    return follow_guest(ctx, pairing)


def join(ctx: Context) -> int:
    pairing = join_flow(ctx, ctx.args.code, wait=not ctx.args.no_wait)
    if pairing.get("state") == "completed":
        ctx.out.result(pairing, lambda out, _: out.line(out.t("pair.join_done")))
    else:
        ctx.out.result(pairing, render_pairing)
    return 0


# Explicit control ----------------------------------------------------------------------------


def _show(ctx: Context, pairing: Any) -> int:
    ctx.out.result(pairing, render_pairing)
    return 0


def pair_status(ctx: Context) -> int:
    return _show(ctx, ctx.api.get(f"/pairing/{_pid(ctx.args.id)}"))


def pair_approve(ctx: Context) -> int:
    return _show(ctx, ctx.api.post(f"/pairing/{_pid(ctx.args.id)}/approve"))


def pair_reject(ctx: Context) -> int:
    return _show(ctx, ctx.api.post(f"/pairing/{_pid(ctx.args.id)}/reject"))


def pair_cancel(ctx: Context) -> int:
    return _show(ctx, ctx.api.delete(f"/pairing/{_pid(ctx.args.id)}"))


def pair_confirm(ctx: Context) -> int:
    pairing = dict(ctx.api.post(f"/pairing/{_pid(ctx.args.id)}/confirm"))
    if ctx.args.wait:
        pairing = follow_guest(ctx, pairing, fallback=True)
    return _show(ctx, pairing)


def pair_request(ctx: Context) -> int:
    pairing = dict(ctx.api.post("/pairing/request"))
    ctx.out.note(ctx.t("pair.request_sent"))
    if not ctx.args.no_wait:
        pairing = follow_guest(ctx, pairing, fallback=True)
    return _show(ctx, pairing)


def pair_requests(ctx: Context) -> int:
    data = ctx.api.get("/pairing/requests")
    ctx.out.result(
        data,
        lambda out, doc: out.table(
            [out.t("col.id"), out.t("col.name"), out.t("col.platform"), out.t("col.created")],
            [[item["id"], item["device_name"], item["platform"], human_date(item.get("created_at"))] for item in doc.get("items") or []],
            empty=out.t("pair.no_requests"),
        ),
    )
    return 0


def pair_review(ctx: Context) -> int:
    request_id = _pid(ctx.args.request)
    pairing = dict(ctx.api.post(f"/pairing/requests/{request_id}/review"))
    if pairing.get("sas"):
        ctx.out.note(ctx.t("pair.sas_host", sas=sas_text(pairing)))
        if ctx.out.interactive and not ctx.out.json_mode:
            path = "approve" if ctx.out.confirm(ctx.t("pair.sas_question")) else "reject"
            pairing = dict(ctx.api.post(f"/pairing/requests/{request_id}/{path}"))
    return _show(ctx, pairing)


def pair_accept(ctx: Context) -> int:
    return _show(ctx, ctx.api.post(f"/pairing/requests/{_pid(ctx.args.request)}/approve"))


def pair_deny(ctx: Context) -> int:
    return _show(ctx, ctx.api.post(f"/pairing/requests/{_pid(ctx.args.request)}/reject"))


ID = arg("id", en="Pairing id (pair_…)", es="Id de la vinculación (pair_…)", metavar="ID")
REQ = arg("request", en="Request id", es="Id de la solicitud", metavar="REQ")

COMMANDS = (
    Command(
        ("pair",),
        "Show a code to add another device (run `bento join CODE` there)",
        "Muestra un código para añadir otro dispositivo (allí: `bento join CÓDIGO`)",
        pair_host,
        (
            arg("--wait", en="Wait for the other device and ask to approve", es="Espera al otro dispositivo y pide aprobar", action="store_true"),
            arg("--approve", en="Approve automatically once it connects (on explicit user instruction)", es="Aprueba automáticamente al conectar (solo si la persona lo pidió)", action="store_true"),
        ),
        output="Pairing",
    ),
    Command(("pair", "status"), "Pairing session state", "Estado de una vinculación", pair_status, (ID,), output="Pairing"),
    Command(("pair", "approve"), "Approve the waiting device", "Aprueba el dispositivo en espera", pair_approve, (ID,), output="Pairing"),
    Command(("pair", "reject"), "Reject the waiting device", "Rechaza el dispositivo en espera", pair_reject, (ID,), output="Pairing"),
    Command(("pair", "cancel"), "Cancel a pairing session", "Cancela una vinculación", pair_cancel, (ID,), output="Pairing"),
    Command(
        ("pair", "confirm"),
        "New device (fallback): the emojis match",
        "Dispositivo nuevo (alternativa): los emojis coinciden",
        pair_confirm,
        (ID, arg("--wait", en="Wait until the keys arrive", es="Espera a recibir las llaves", action="store_true")),
        output="Pairing",
    ),
    Command(
        ("pair", "request"),
        "New device: ask your other devices through Telegram (no code)",
        "Dispositivo nuevo: pide acceso a tus otros dispositivos por Telegram (sin código)",
        pair_request,
        (arg("--no-wait", en="Return immediately", es="Vuelve enseguida", action="store_true"),),
        output="Pairing",
    ),
    Command(("pair", "requests"), "Access requests from new devices", "Solicitudes de acceso de dispositivos nuevos", pair_requests, output="PairingRequests"),
    Command(("pair", "review"), "Review a request (shows the emojis)", "Revisa una solicitud (muestra los emojis)", pair_review, (REQ,), output="Pairing"),
    Command(("pair", "accept"), "Accept a reviewed request", "Acepta una solicitud revisada", pair_accept, (REQ,), output="Pairing"),
    Command(("pair", "deny"), "Deny a request", "Rechaza una solicitud", pair_deny, (REQ,), output="Pairing"),
    Command(
        ("join",),
        "Join your Bento with the code shown on another device",
        "Únete a tu Bento con el código que muestra otro dispositivo",
        join,
        (
            arg("code", en="Code (K7Q2-MXR9-T4WA) or bento:// / https link", es="Código (K7Q2-MXR9-T4WA) o enlace bento:// / https", metavar="CODE_OR_LINK"),
            arg("--no-wait", en="Return after joining the session", es="Vuelve tras unirte a la sesión", action="store_true"),
        ),
        output="Pairing",
    ),
)
