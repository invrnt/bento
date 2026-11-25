"""Trash: list, restore, purge, empty."""

from __future__ import annotations

from typing import Any

from bento.interfaces.cli.catalog import Command, arg
from bento.interfaces.cli.commands.common import date_text, iterate, kind_label, pages, size_text
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.errors import CliError
from bento.interfaces.cli.output import Output


def ls(ctx: Context) -> int:
    items, next_cursor, _ = pages(ctx, "/trash", {"limit": 200 if ctx.args.all else 50}, follow=ctx.args.all)
    ctx.out.result({"items": items, "next_cursor": next_cursor}, _render_ls)
    return 0


def _render_ls(out: Output, data: dict[str, Any]) -> None:
    rows = [
        [kind_label(out, item.get("type")), item["name"], size_text(out, item.get("size_bytes")), date_text(item.get("deleted_at")), date_text(item.get("purge_at")), f"id:{item['id']}"]
        for item in data["items"]
    ]
    out.table([out.t(f"col.{name}") for name in ("type", "name", "size", "deleted", "purge", "id")], rows, empty=out.t("trash.empty"))
    if data.get("next_cursor"):
        out.note(out.t("ls.more"))


def _trash_ids(ctx: Context, values: list[str]) -> list[str]:
    """`id:X`, a bare id, or the name of a trashed item (trashed items have no path)."""
    entries: list[dict[str, Any]] | None = None
    ids: list[str] = []
    for value in values:
        if value.startswith("id:"):
            ids.append(value[3:])
            continue
        if entries is None:
            entries = list(iterate(ctx, "/trash", {"limit": 200}))
        if any(entry["id"] == value for entry in entries):
            ids.append(value)
            continue
        name = value.rstrip("/").rsplit("/", 1)[-1]
        matches = [entry for entry in entries if entry["name"] == name]
        if not matches:
            raise CliError("trash_item_not_found", "Not in the trash", {"input": value})
        if len(matches) > 1:
            raise CliError(
                "trash_item_ambiguous",
                "Several trashed items have this name; use id:",
                {"input": value, "candidates": [{"id": entry["id"], "kind": entry["type"], "path": entry["name"], "created_at": entry["deleted_at"]} for entry in matches]},
            )
        ids.append(matches[0]["id"])
    return ids


def restore(ctx: Context) -> int:
    ids = _trash_ids(ctx, ctx.args.items)
    data = ctx.api.post("/trash/restore", {"ids": ids})
    document = {"restored": data.get("restored", 0), "ids": ids}
    ctx.out.result(document, lambda out, doc: out.line(out.t("trash.restored", count=doc["restored"])))
    return 0


def purge(ctx: Context) -> int:
    ids = _trash_ids(ctx, ctx.args.items)
    ctx.require_confirmation("trash purge", ctx.t("trash.confirm_purge", count=len(ids)))
    data = ctx.api.post("/trash/purge", {"ids": ids})
    ctx.out.result(data, lambda out, doc: out.line(out.t("trash.purged", count=doc.get("purged", 0))))
    return 0


def empty(ctx: Context) -> int:
    ctx.require_confirmation("trash empty", ctx.t("trash.confirm_empty"))
    data = ctx.api.post("/trash/empty")
    ctx.out.result(data, lambda out, doc: out.line(out.t("trash.purged", count=doc.get("purged", 0))))
    return 0


COMMANDS = (
    Command(("trash",), "Trash (undo removals)", "Papelera (deshacer borrados)", default_child="ls"),
    Command(
        ("trash", "ls"),
        "List trashed items",
        "Lista lo que hay en la papelera",
        ls,
        (arg("--all", en="Follow cursors", es="Sigue los cursores", action="store_true"),),
        output="TrashList",
    ),
    Command(
        ("trash", "restore"),
        "Restore items (id:, id, or trashed name)",
        "Restaura elementos (id:, id o nombre)",
        restore,
        (arg("items", en="id:<id> or name", es="id:<id> o nombre", nargs="+", metavar="ID_OR_PATH"),),
        output="TrashRestore",
    ),
    Command(
        ("trash", "purge"),
        "Delete items forever (needs --yes off a TTY)",
        "Borra para siempre (requiere --yes fuera de una terminal)",
        purge,
        (arg("items", en="id:<id> or name", es="id:<id> o nombre", nargs="+", metavar="ID"),),
        output="TrashPurge",
    ),
    Command(("trash", "empty"), "Empty the trash forever (needs --yes off a TTY)", "Vacía la papelera para siempre (requiere --yes)", empty, output="TrashPurge"),
)
