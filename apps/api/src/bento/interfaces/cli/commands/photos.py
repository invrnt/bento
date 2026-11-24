"""Photos: timeline, albums, favorites."""

from __future__ import annotations

from typing import Any

from bento.interfaces.cli.catalog import Command, arg
from bento.interfaces.cli.commands.common import date_text, iterate, pages, paths_for, resolve, run_batch
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.errors import CliError, usage
from bento.interfaces.cli.output import Output


def _asset(ctx: Context, value: str) -> dict[str, Any]:
    resolved = resolve(ctx, value)
    if resolved.get("kind") != "asset":
        raise usage("This command needs a file, not a folder", path=resolved.get("path"))
    return {"asset": resolved["asset"], "path": resolved.get("path")}


def timeline(ctx: Context) -> int:
    groups, next_cursor, _ = pages(ctx, "/photos/timeline", {"limit": ctx.args.limit}, follow=False, key="groups")
    ids = [asset["id"] for group in groups for asset in group.get("assets") or []]
    known = paths_for(ctx, ids) if ids else {}
    for group in groups:
        group["assets"] = [{**asset, "path": known.get(asset["id"])} for asset in group.get("assets") or []]
    ctx.out.result({"groups": groups, "next_cursor": next_cursor}, _render_timeline)
    return 0


def _render_timeline(out: Output, data: dict[str, Any]) -> None:
    if not data["groups"]:
        out.line(out.t("photos.empty"))
    for group in data["groups"]:
        out.line(f"{group['date']}  ({len(group['assets'])})")
        for asset in group["assets"]:
            star = "★ " if asset.get("favorite") else "  "
            out.line(f"  {star}{asset.get('path') or asset['filename']}")


# Albums --------------------------------------------------------------------------------------


def find_album(ctx: Context, value: str) -> dict[str, Any]:
    if value.startswith("id:"):
        return dict(ctx.api.get(f"/photos/albums/{value[3:]}"))
    matches = [album for album in iterate(ctx, "/photos/albums", {"limit": 200}) if album.get("title") == value]
    if not matches:
        raise CliError("album_not_found", "Album not found", {"album": value})
    if len(matches) > 1:
        raise CliError(
            "album_ambiguous",
            "Several albums have this name; use id:",
            {"album": value, "candidates": [{"id": album["id"], "kind": "album", "path": album["title"], "created_at": album["created_at"]} for album in matches]},
        )
    return matches[0]


def albums_ls(ctx: Context) -> int:
    items = list(iterate(ctx, "/photos/albums", {"limit": 200}))
    ctx.out.result(
        {"items": items},
        lambda out, data: out.table(
            [out.t("col.name"), out.t("col.items"), out.t("col.modified"), out.t("col.id")],
            [[album["title"], len(album.get("asset_ids") or []), date_text(album.get("updated_at")), f"id:{album['id']}"] for album in data["items"]],
            empty=out.t("albums.empty"),
        ),
    )
    return 0


def albums_create(ctx: Context) -> int:
    title = ctx.args.name.strip()
    if not title:
        raise usage("Album name is required")
    album = ctx.api.post("/photos/albums", {"title": title})
    ctx.out.result(album, lambda out, data: out.line(out.t("albums.created", name=data["title"], id=data["id"])))
    return 0


def albums_show(ctx: Context) -> int:
    album = find_album(ctx, ctx.args.album)
    ids = list(album.get("asset_ids") or [])
    known = paths_for(ctx, ids) if ids else {}
    document = {**album, "items": [{"id": asset_id, "path": known.get(asset_id)} for asset_id in ids]}

    def render(out: Output, data: dict[str, Any]) -> None:
        out.line(f"{data['title']}  (id:{data['id']}, {len(data['items'])})")
        for item in data["items"]:
            out.line(f"  {item['path'] or 'id:' + item['id']}")

    ctx.out.result(document, render)
    return 0


def _album_membership(ctx: Context, *, add: bool) -> int:
    album = find_album(ctx, ctx.args.album)

    def change(value: str) -> dict[str, Any]:
        target = _asset(ctx, value)
        asset_id = target["asset"]["id"]
        if add:
            ctx.api.post(f"/photos/albums/{album['id']}/items", {"asset_id": asset_id})
        else:
            ctx.api.delete(f"/photos/albums/{album['id']}/items/{asset_id}")
        return {"id": asset_id, "path": target["path"], "album_id": album["id"], "status": "added" if add else "removed"}

    key = "albums.added" if add else "albums.removed"
    return run_batch(ctx, ctx.args.paths, change, human=lambda out, item: out.line(out.t(key, path=item["path"], album=album["title"])))


def albums_add(ctx: Context) -> int:
    return _album_membership(ctx, add=True)


def albums_remove(ctx: Context) -> int:
    return _album_membership(ctx, add=False)


def favorite(ctx: Context) -> int:
    value = not ctx.args.off

    def change(text: str) -> dict[str, Any]:
        target = _asset(ctx, text)
        asset = ctx.api.post(f"/photos/{target['asset']['id']}/favorite", {"favorite": value})
        return {"id": asset["id"], "path": target["path"], "favorite": asset.get("favorite"), "asset": asset}

    key = "favorite.on" if value else "favorite.off"
    return run_batch(ctx, ctx.args.paths, change, human=lambda out, item: out.line(out.t(key, path=item["path"])))


ALBUM_HELP = ("Album name or id:<album_id>", "Nombre del álbum o id:<id>")

COMMANDS = (
    Command(("photos",), "Photo and video timeline", "Línea de tiempo de fotos y videos", default_child="timeline"),
    Command(
        ("photos", "timeline"),
        "Photo and video timeline grouped by date",
        "Fotos y videos agrupados por fecha",
        timeline,
        (arg("--limit", en="Photos per page", es="Fotos por página", type=int, default=50),),
        output="PhotoTimeline",
    ),
    Command(("albums",), "Photo albums", "Álbumes de fotos", default_child="ls"),
    Command(("albums", "ls"), "List albums", "Lista los álbumes", albums_ls, output="AlbumList"),
    Command(("albums", "create"), "Create an album", "Crea un álbum", albums_create, (arg("name", en="Album name", es="Nombre del álbum", metavar="NAME"),), output="Album"),
    Command(("albums", "show"), "Show an album and its files", "Muestra un álbum y sus archivos", albums_show, (arg("album", en=ALBUM_HELP[0], es=ALBUM_HELP[1], metavar="ALBUM"),), output="AlbumDetail"),
    Command(
        ("albums", "add"),
        "Add files to an album",
        "Añade archivos a un álbum",
        albums_add,
        (arg("album", en=ALBUM_HELP[0], es=ALBUM_HELP[1], metavar="ALBUM"), arg("paths", en="Files", es="Archivos", nargs="+", metavar="PATH")),
        output="AlbumChange",
    ),
    Command(
        ("albums", "remove"),
        "Remove files from an album (the files stay)",
        "Quita archivos de un álbum (los archivos se conservan)",
        albums_remove,
        (arg("album", en=ALBUM_HELP[0], es=ALBUM_HELP[1], metavar="ALBUM"), arg("paths", en="Files", es="Archivos", nargs="+", metavar="PATH")),
        output="AlbumChange",
    ),
    Command(
        ("favorite",),
        "Mark files as favorites (--off to unmark)",
        "Marca archivos como favoritos (--off para quitar)",
        favorite,
        (arg("paths", en="Files", es="Archivos", nargs="+", metavar="PATH"), arg("--off", en="Remove the favorite mark", es="Quita la marca de favorito", action="store_true")),
        output="FavoriteChange",
    ),
)
