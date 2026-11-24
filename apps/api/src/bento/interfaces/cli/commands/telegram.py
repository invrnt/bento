"""Telegram: chats, share (unencrypted copy), import from chats."""

from __future__ import annotations

from typing import Any

from bento.interfaces.cli.catalog import Command, arg
from bento.interfaces.cli.commands.common import date_text, resolve, size_text
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.errors import CliError, confirmation_required, usage
from bento.interfaces.cli.output import Output


def chats(ctx: Context) -> int:
    data = ctx.api.get("/telegram/chats", {"query": ctx.args.query, "limit": ctx.args.limit})
    ctx.out.result(
        data,
        lambda out, doc: out.table(
            [out.t("col.id"), out.t("col.kind"), out.t("col.name")],
            [[chat["id"], chat["kind"], chat["title"]] for chat in doc.get("items") or []],
            empty=out.t("telegram.no_chats"),
        ),
    )
    return 0


def share(ctx: Context) -> int:
    resolved = resolve(ctx, ctx.args.path)
    if resolved.get("kind") != "asset":
        raise usage("share needs a file", path=resolved.get("path"))
    # Sharing sends an unencrypted copy: always explicit.
    if not ctx.yes:
        if not ctx.out.interactive or ctx.out.json_mode:
            raise confirmation_required("share")
        ctx.out.note(ctx.t("share.warning"))
        if not ctx.out.confirm(ctx.t("share.confirm", path=resolved.get("path"), chat=ctx.args.chat)):
            raise CliError("cancelled", "Cancelled", {"command": "share"}, 1)
    body: dict[str, Any] = {"chat_id": ctx.args.chat}
    if ctx.args.caption:
        body["caption"] = ctx.args.caption
    data = ctx.api.post(f"/assets/{resolved['asset']['id']}/share/telegram", body)
    document = {**data, "id": resolved["asset"]["id"], "path": resolved.get("path"), "chat_id": ctx.args.chat, "encrypted": False}
    ctx.out.result(document, lambda out, doc: out.line(out.t("share.sent", path=doc["path"])))
    return 0


def import_list(ctx: Context) -> int:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page = ctx.api.get("/telegram/import/media", {"chat_id": ctx.args.list_chat, "cursor": cursor, "kind": ctx.args.kind})
        items.extend(page.get("items") or [])
        cursor = page.get("next_cursor")
        if not cursor or not ctx.args.all or len(items) >= 5000:
            break
    document = {"chat_id": ctx.args.list_chat, "items": items, "next_cursor": cursor}

    def render(out: Output, doc: dict[str, Any]) -> None:
        out.table(
            [out.t("col.id"), out.t("col.kind"), out.t("col.name"), out.t("col.size"), out.t("col.date")],
            [[item["message_id"], item["kind"], item["filename"], size_text(out, item.get("size_bytes")), date_text(item.get("date"))] for item in doc["items"]],
            empty=out.t("telegram.no_media"),
        )

    ctx.out.result(document, render)
    return 0


def import_media(ctx: Context) -> int:
    if ctx.args.chat is None:
        raise usage("Pass --chat CHAT_ID (see `bento telegram chats`)")
    if bool(ctx.args.all) == bool(ctx.args.message_ids):
        raise usage("Pass --all or --message-ids ID…")
    body: dict[str, Any] = {"chat_id": ctx.args.chat, "all": bool(ctx.args.all)}
    if ctx.args.message_ids:
        body["message_ids"] = ctx.args.message_ids
    data = ctx.api.post("/telegram/import", body)
    ctx.out.result(data, lambda out, doc: out.line(out.t("import.queued", count=doc.get("queued", 0), job=doc.get("job_id"))))
    return 0


COMMANDS = (
    Command(("telegram",), "Your Telegram chats", "Tus chats de Telegram"),
    Command(
        ("telegram", "chats"),
        "List Telegram chats (ids for share/import)",
        "Lista chats de Telegram (ids para compartir/importar)",
        chats,
        (
            arg("--query", en="Filter by name", es="Filtra por nombre", metavar="Q"),
            arg("--limit", en="Maximum chats", es="Máximo de chats", type=int, default=30),
        ),
        output="TelegramChats",
    ),
    Command(
        ("share",),
        "Send an UNENCRYPTED copy of a file to a Telegram chat",
        "Envía una copia SIN CIFRAR de un archivo a un chat de Telegram",
        share,
        (
            arg("path", en="File", es="Archivo"),
            arg("--chat", en="Chat id", es="Id del chat", type=int, required=True, metavar="CHAT_ID"),
            arg("--caption", en="Message text", es="Texto del mensaje", metavar="TEXT"),
        ),
        output="ShareResult",
    ),
    Command(
        ("import",),
        "Import media from a Telegram chat into Bento",
        "Importa archivos de un chat de Telegram a Bento",
        import_media,
        (
            arg("--chat", en="Chat id", es="Id del chat", type=int, metavar="CHAT_ID"),
            arg("--all", en="Import every media message", es="Importa todos los archivos", action="store_true"),
            arg("--message-ids", en="Only these message ids", es="Solo estos mensajes", type=int, nargs="+", metavar="ID"),
        ),
        output="ImportQueued",
    ),
    Command(
        ("import", "list"),
        "List importable media in a chat",
        "Lista los archivos importables de un chat",
        import_list,
        (
            arg("--chat", en="Chat id", es="Id del chat", type=int, required=True, dest="list_chat", metavar="CHAT_ID"),
            arg("--kind", en="Media kind", es="Tipo de archivo", choices=("photo", "video", "document", "all"), default="all"),
            arg("--all", en="Follow cursors", es="Sigue los cursores", action="store_true"),
        ),
        output="TelegramMedia",
    ),
)
