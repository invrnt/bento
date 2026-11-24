"""Backup: watched folders and the backup policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bento.interfaces.cli.catalog import Command, arg
from bento.interfaces.cli.commands.common import date_text, size_text
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.errors import usage
from bento.interfaces.cli.output import Output


def _render_sources(out: Output, data: dict[str, Any]) -> None:
    rows = [
        [
            source.get("label") or Path(source["path"]).name,
            source["path"],
            out.t(f"backup.state.{source.get('state')}") if source.get("enabled") else out.t("backup.disabled"),
            f"{source.get('files_done', 0)}/{source.get('files_total', 0)}",
            size_text(out, source.get("bytes_pending")),
            date_text(source.get("last_scan_at")),
            source["id"],
        ]
        for source in data["items"]
    ]
    out.table([out.t(f"col.{name}") for name in ("name", "folder", "state", "files", "pending", "scanned", "id")], rows, empty=out.t("backup.empty"))


def ls(ctx: Context) -> int:
    ctx.out.result(ctx.api.get("/backup/sources"), _render_sources)
    return 0


def _render_source(out: Output, source: dict[str, Any]) -> None:
    _render_sources(out, {"items": [source]})


def add(ctx: Context) -> int:
    directory = Path(ctx.args.directory).expanduser()
    if not directory.is_dir():
        raise usage("Not a local directory", directory=str(directory))
    absolute = str(directory.resolve())
    existing = next(
        (source for source in (ctx.api.get("/backup/sources").get("items") or []) if _same(source.get("path"), absolute)),
        None,
    )
    if existing is not None:
        if ctx.args.label and existing.get("label") != ctx.args.label:
            existing = ctx.api.patch(f"/backup/sources/{existing['id']}", {"label": ctx.args.label})
        ctx.out.result({**existing, "existing": True}, _render_source)
        return 0
    body: dict[str, Any] = {"path": absolute}
    if ctx.args.label:
        body["label"] = ctx.args.label
    source = ctx.api.post("/backup/sources", body)
    ctx.out.result({**source, "existing": False}, _render_source)
    ctx.out.note(ctx.t("backup.added_hint"))
    return 0


def _same(left: Any, right: str) -> bool:
    if not isinstance(left, str):
        return False
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return left == right


def remove(ctx: Context) -> int:
    data = ctx.api.delete(f"/backup/sources/{ctx.args.id}")
    ctx.out.result({**(data or {}), "id": ctx.args.id}, lambda out, _: out.line(out.t("backup.removed")))
    return 0


def _set_enabled(ctx: Context, enabled: bool) -> int:
    source = ctx.api.patch(f"/backup/sources/{ctx.args.id}", {"enabled": enabled})
    ctx.out.result(source, _render_source)
    return 0


def enable(ctx: Context) -> int:
    return _set_enabled(ctx, True)


def disable(ctx: Context) -> int:
    return _set_enabled(ctx, False)


def scan(ctx: Context) -> int:
    ctx.out.result(ctx.api.post(f"/backup/sources/{ctx.args.id}/scan"), _render_source)
    return 0


def suggestions(ctx: Context) -> int:
    data = ctx.api.get("/backup/suggestions")
    ctx.out.result(
        data,
        lambda out, doc: out.table(
            [out.t("col.name"), out.t("col.folder"), out.t("col.kind")],
            [[item["label"], item["path"], item["kind"]] for item in doc.get("items") or []],
            empty=out.t("backup.no_suggestions"),
        ),
    )
    return 0


def policy(ctx: Context) -> int:
    args = ctx.args
    patch: dict[str, Any] = {}
    if args.pause and args.resume:
        raise usage("Use --pause or --resume, not both")
    if args.pause:
        patch["paused"] = True
    if args.resume:
        patch["paused"] = False
    if args.pause_on_battery is not None:
        patch["pause_on_battery"] = args.pause_on_battery == "on"
    if args.bandwidth_kbps is not None:
        if args.bandwidth_kbps < 0:
            raise usage("--bandwidth-kbps must be 0 (unlimited) or more")
        patch["bandwidth_limit_kbps"] = args.bandwidth_kbps
    data = ctx.api.patch("/backup/policy", patch) if patch else ctx.api.get("/backup/policy")

    def render(out: Output, doc: dict[str, Any]) -> None:
        limit = doc.get("bandwidth_limit_kbps") or 0
        out.fields(
            [
                (out.t("backup.policy.paused"), out.t("yes") if doc.get("paused") else out.t("no")),
                (out.t("backup.policy.pause_on_battery"), out.t("yes") if doc.get("pause_on_battery") else out.t("no")),
                (out.t("backup.policy.bandwidth"), out.t("backup.policy.unlimited") if not limit else f"{limit} kbps"),
                (out.t("backup.policy.on_battery"), out.t("yes") if doc.get("on_battery") else out.t("no")),
                (out.t("backup.policy.effective"), out.t("backup.policy.paused_now") if doc.get("effective_paused") else out.t("backup.policy.active")),
            ]
        )

    ctx.out.result(data, render)
    return 0


ID_ARG = arg("id", en="Backup source id", es="Id de la carpeta respaldada", metavar="ID")

COMMANDS = (
    Command(("backup",), "Automatic backup of local folders", "Respaldo automático de carpetas locales", default_child="ls"),
    Command(("backup", "ls"), "List backed-up folders", "Lista las carpetas respaldadas", ls, output="BackupSources"),
    Command(
        ("backup", "add"),
        "Back up a local folder (idempotent)",
        "Respalda una carpeta local (idempotente)",
        add,
        (arg("directory", en="Local directory", es="Carpeta local", metavar="DIR"), arg("--label", en="Display name", es="Nombre visible", metavar="L")),
        output="BackupSource",
    ),
    Command(("backup", "remove"), "Stop backing up a folder (uploaded files stay)", "Deja de respaldar una carpeta (lo subido se conserva)", remove, (ID_ARG,), output="BackupRemoved"),
    Command(("backup", "enable"), "Resume a backed-up folder", "Reactiva una carpeta respaldada", enable, (ID_ARG,), output="BackupSource"),
    Command(("backup", "disable"), "Pause a backed-up folder", "Pausa una carpeta respaldada", disable, (ID_ARG,), output="BackupSource"),
    Command(("backup", "scan"), "Rescan a backed-up folder now", "Vuelve a revisar una carpeta ahora", scan, (ID_ARG,), output="BackupSource"),
    Command(("backup", "suggestions"), "Suggested folders (Pictures, Documents…)", "Carpetas sugeridas (Imágenes, Documentos…)", suggestions, output="BackupSuggestions"),
    Command(
        ("backup", "policy"),
        "Show or change the backup policy",
        "Muestra o cambia la política de respaldo",
        policy,
        (
            arg("--pause", en="Pause all backups", es="Pausa todos los respaldos", action="store_true"),
            arg("--resume", en="Resume backups", es="Reanuda los respaldos", action="store_true"),
            arg("--pause-on-battery", en="Pause on battery", es="Pausar con batería", choices=("on", "off")),
            arg("--bandwidth-kbps", en="Upload limit in kbps (0 = unlimited)", es="Límite de subida en kbps (0 = sin límite)", type=int, metavar="N"),
        ),
        output="BackupPolicy",
    ),
)
