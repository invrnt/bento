"""find: name, metadata, OCR text and semantic search, with Bento paths in the results."""

from __future__ import annotations

from typing import Any

from bento.interfaces.cli.catalog import Command, arg
from bento.interfaces.cli.commands.common import folder_id_of, kind_label, pages, paths_for, resolve_folder
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.output import Output

SEARCH_TYPES = ("asset", "folder", "photo", "video", "document", "pdf_page", "ocr_block", "album")


def find(ctx: Context) -> int:
    args = ctx.args
    folder_id = folder_id_of(resolve_folder(ctx, args.within)) if args.within else None
    params = {
        "q": args.query or "",
        "type": args.type,
        "folder_id": folder_id,
        "date_from": args.date_from,
        "date_to": args.date_to,
        "limit": max(1, min(int(args.limit), 100)),
    }
    items, next_cursor, last = pages(ctx, "/search", params, follow=args.all)
    ids = [str(item.get("asset_id") or item.get("id")) for item in items if item.get("type") != "album"]
    known = paths_for(ctx, ids) if ids else {}
    enriched = []
    for item in items:
        key = str(item.get("asset_id") or item.get("id"))
        enriched.append({**item, "path": known.get(key)})
    document: dict[str, Any] = {"query": params["q"], "items": enriched, "facets": last.get("facets") or [], "next_cursor": next_cursor}
    ctx.out.result(document, _render)
    return 0


def _render(out: Output, data: dict[str, Any]) -> None:
    rows = [
        [kind_label(out, item.get("type")), item.get("title") or "", item.get("path") or "-", item.get("reason") or "", f"id:{item.get('asset_id') or item.get('id')}"]
        for item in data["items"]
    ]
    out.table([out.t(f"col.{name}") for name in ("type", "name", "path", "reason", "id")], rows, empty=out.t("find.empty"))
    if data.get("next_cursor"):
        out.note(out.t("ls.more"))


COMMANDS = (
    Command(
        ("find",),
        "Search by name, metadata, OCR text (and meaning when enabled)",
        "Busca por nombre, metadatos, texto OCR (y significado si está activo)",
        find,
        (
            arg("query", en="Text to search", es="Texto a buscar", nargs="?"),
            arg("--in", en="Only inside this folder", es="Solo dentro de esta carpeta", dest="within", metavar="PATH"),
            arg("--type", en="Result type", es="Tipo de resultado", choices=SEARCH_TYPES),
            arg("--from", en="From date (YYYY-MM-DD)", es="Desde la fecha (AAAA-MM-DD)", dest="date_from", metavar="DATE"),
            arg("--to", en="Until date (YYYY-MM-DD)", es="Hasta la fecha (AAAA-MM-DD)", dest="date_to", metavar="DATE"),
            arg("--limit", en="Results per page (1-100)", es="Resultados por página (1-100)", type=int, default=50),
            arg("--all", en="Follow cursors", es="Sigue los cursores", action="store_true"),
        ),
        output="SearchResults",
    ),
)
