"""Devices: list, rename, remove (prints the new recovery code), acknowledge."""

from __future__ import annotations

from typing import Any

from bento.interfaces.cli.catalog import Command, arg
from bento.interfaces.cli.commands.common import date_text
from bento.interfaces.cli.commands.vault import show_recovery_code
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.output import Output


def _did(value: str) -> str:
    return value[3:] if value.startswith("id:") else value


def _device_rows(out: Output, devices: list[dict[str, Any]]) -> list[list[Any]]:
    rows = []
    for device in devices:
        marks = []
        if device.get("current"):
            marks.append(out.t("devices.this"))
        if device.get("needs_review"):
            marks.append(out.t("devices.review"))
        if device.get("removed_at"):
            marks.append(out.t("devices.removed"))
        rows.append([device["name"], device.get("platform"), date_text(device.get("last_seen_at")), " ".join(marks), device["id"]])
    return rows


def ls(ctx: Context) -> int:
    data = ctx.api.get("/devices", {"include_removed": True if ctx.args.include_removed else None})
    ctx.out.result(
        data,
        lambda out, doc: out.table(
            [out.t(f"col.{name}") for name in ("name", "platform", "seen", "notes", "id")],
            _device_rows(out, doc.get("items") or []),
            empty=out.t("devices.empty"),
        ),
    )
    return 0


def rename(ctx: Context) -> int:
    device = ctx.api.patch(f"/devices/{_did(ctx.args.id)}", {"name": ctx.args.name})
    ctx.out.result(device, lambda out, doc: out.line(out.t("devices.renamed", name=doc["name"])))
    return 0


def remove(ctx: Context) -> int:
    device_id = _did(ctx.args.id)
    excluded = [_did(value) for value in ctx.args.exclude or []]
    preview = ctx.api.get(f"/devices/{device_id}/removal-preview")
    if not ctx.out.json_mode:
        recipients = preview.get("recipients") or []
        ctx.out.note(ctx.t("devices.remove_recipients"))
        for device in recipients:
            flag = " ✗" if device["id"] in excluded else ""
            review = f" ({ctx.t('devices.review')})" if device.get("needs_review") else ""
            ctx.out.note(f"  - {device['name']}{review}  {device['id']}{flag}")
    ctx.require_confirmation("devices remove", ctx.t("devices.remove_confirm", id=device_id))
    body = {"exclude_device_ids": excluded} if excluded else None
    data = dict(ctx.api.delete(f"/devices/{device_id}", body))
    show_recovery_code(ctx, str(data.get("recovery_code")), data.get("recovery_qr"))
    ctx.out.result(data, lambda out, doc: out.line(out.t("devices.removed_done", count=len(doc.get("removed_device_ids") or []))))
    return 0


def ack(ctx: Context) -> int:
    device = ctx.api.post(f"/devices/{_did(ctx.args.id)}/acknowledge")
    ctx.out.result(device, lambda out, doc: out.line(out.t("devices.acknowledged", name=doc["name"])))
    return 0


ID = arg("id", en="Device id", es="Id del dispositivo", metavar="ID")

COMMANDS = (
    Command(("devices",), "Devices connected to your Bento", "Dispositivos conectados a tu Bento", default_child="ls"),
    Command(
        ("devices", "ls"),
        "List devices",
        "Lista los dispositivos",
        ls,
        (arg("--include-removed", en="Include removed devices", es="Incluye los eliminados", action="store_true"),),
        output="DeviceList",
    ),
    Command(("devices", "rename"), "Rename a device", "Renombra un dispositivo", rename, (ID, arg("name", en="New name", es="Nombre nuevo", metavar="NAME")), output="Device"),
    Command(
        ("devices", "remove"),
        "Remove a device (rotates keys, prints a new recovery code)",
        "Elimina un dispositivo (rota las llaves y muestra un código nuevo)",
        remove,
        (ID, arg("--exclude", en="Also remove these unknown devices", es="Elimina también estos dispositivos desconocidos", nargs="+", metavar="ID")),
        output="DeviceRemoval",
    ),
    Command(("devices", "ack"), "Mark a new device as reviewed", "Marca un dispositivo nuevo como revisado", ack, (ID,), output="Device"),
)
