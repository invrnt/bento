"""Drive: ls, tree, stat, mkdir, mv, rename, rm, open."""

from __future__ import annotations

from typing import Any

from bento.interfaces.cli.catalog import Command, arg
from bento.interfaces.cli.commands.common import (
    date_text,
    drive_item,
    folder_id_of,
    item_id,
    kind_label,
    pages,
    resolve,
    resolve_folder,
    resolved_summary,
    run_batch,
    size_text,
)
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.errors import CliError, usage
from bento.interfaces.cli.output import Output
from bento.interfaces.cli.paths import join_path, parse_ref

FOLDERS_FIRST = {"folder": 0, "asset": 1}


# ls ------------------------------------------------------------------------------------------


def ls(ctx: Context) -> int:
    resolved = resolve(ctx, ctx.args.path or "/")
    parent_path = str(resolved.get("path") or "/")
    if resolved.get("kind") == "asset":
        asset = resolved["asset"]
        entry = {"type": "asset", "id": asset["id"], "name": asset["filename"], "updated_at": asset.get("updated_at"), "asset": asset}
        document: dict[str, Any] = {"path": parent_path, "items": [{**entry, "path": parent_path}], "next_cursor": None}
    else:
        params = {"folder_id": folder_id_of(resolved), "limit": ctx.args.limit, "cursor": ctx.args.cursor}
        items, next_cursor, _ = pages(ctx, "/drive/items", params, follow=ctx.args.all)
        ordered = sorted(items, key=lambda item: (FOLDERS_FIRST.get(str(item.get("type")), 2), str(item.get("name", "")).casefold()))
        document = {
            "path": parent_path,
            "folder": resolved.get("folder"),
            "items": [drive_item(item, parent_path) for item in ordered],
            "next_cursor": next_cursor,
        }
    long = bool(ctx.args.long)
    ctx.out.result(document, lambda out, data: _render_ls(out, data, long=long))
    return 0


def _render_ls(out: Output, data: dict[str, Any], *, long: bool) -> None:
    items = data["items"]
    if not items:
        out.line(out.t("ls.empty", path=data["path"]))
    elif long:
        rows = []
        for item in items:
            asset = item.get("asset") or {}
            is_folder = item.get("type") == "folder"
            rows.append(
                [
                    kind_label(out, "folder" if is_folder else asset.get("kind")),
                    item["name"] + ("/" if is_folder else ""),
                    "" if is_folder else size_text(out, asset.get("size_bytes")),
                    date_text(item.get("updated_at")),
                    "" if is_folder else out.t(f"state.{asset.get('processing_state')}"),
                    f"id:{item['id']}",
                ]
            )
        out.table([out.t(f"col.{name}") for name in ("type", "name", "size", "modified", "state", "id")], rows)
    else:
        for item in items:
            out.line(item["name"] + ("/" if item.get("type") == "folder" else ""))
    if data.get("next_cursor"):
        out.note(out.t("ls.more"))


# tree ----------------------------------------------------------------------------------------


def tree(ctx: Context) -> int:
    params = {
        "path": parse_ref(ctx.args.path or "/").text,
        "depth": ctx.args.depth,
        "include_assets": ctx.args.files,
        "max_nodes": ctx.args.max_nodes,
    }
    data = ctx.api.get("/drive/tree", params)
    ctx.out.result(data, _render_tree)
    return 0


def _render_tree(out: Output, data: dict[str, Any]) -> None:
    root = data.get("root") or {}
    out.line(str(root.get("path") or "/"))
    _render_children(out, root.get("children") or [], "")
    folders, files = _count(root)
    out.line("")
    out.line(out.t("tree.summary", folders=folders, files=files))
    if data.get("truncated"):
        out.note(out.t("tree.truncated"))


def _render_children(out: Output, children: list[dict[str, Any]], prefix: str) -> None:
    for index, node in enumerate(children):
        last = index == len(children) - 1
        branch = "└── " if last else "├── "
        is_folder = node.get("kind") == "folder"
        label = str(node.get("name", "")) + ("/" if is_folder else "")
        if not is_folder and isinstance(node.get("size_bytes"), int):
            label += f"  ({size_text(out, node['size_bytes'])})"
        if node.get("has_more"):
            label += "  …"
        out.line(prefix + branch + label)
        _render_children(out, node.get("children") or [], prefix + ("    " if last else "│   "))


def _count(node: dict[str, Any]) -> tuple[int, int]:
    folders = files = 0
    for child in node.get("children") or []:
        if child.get("kind") == "folder":
            folders += 1
            sub_folders, sub_files = _count(child)
            folders += sub_folders
            files += sub_files
        else:
            files += 1
    return folders, files


# stat ----------------------------------------------------------------------------------------


def stat(ctx: Context) -> int:
    return run_batch(ctx, ctx.args.paths, lambda value: resolve(ctx, value), human=_render_stat)


def _render_stat(out: Output, item: dict[str, Any]) -> None:
    kind = item.get("kind")
    pairs: list[tuple[str, Any]] = [(out.t("col.path"), item.get("path")), (out.t("col.type"), kind_label(out, kind))]
    if kind == "folder" and item.get("folder"):
        folder = item["folder"]
        pairs += [("id", f"id:{folder['id']}"), (out.t("col.created"), date_text(folder.get("created_at"))), (out.t("col.modified"), date_text(folder.get("updated_at")))]
    elif kind == "asset" and item.get("asset"):
        asset = item["asset"]
        pairs += [
            ("id", f"id:{asset['id']}"),
            (out.t("col.kind"), kind_label(out, asset.get("kind"))),
            ("MIME", asset.get("mime_type")),
            (out.t("col.size"), size_text(out, asset.get("size_bytes"))),
            ("SHA-256", asset.get("sha256")),
            (out.t("col.state"), out.t(f"state.{asset.get('processing_state')}")),
            (out.t("col.favorite"), out.t("yes") if asset.get("favorite") else out.t("no")),
            (out.t("col.taken"), date_text(asset.get("taken_at"))),
            (out.t("col.created"), date_text(asset.get("created_at"))),
            (out.t("col.modified"), date_text(asset.get("updated_at"))),
        ]
    out.fields(pairs)
    out.line("")


# mkdir ---------------------------------------------------------------------------------------


def mkdir(ctx: Context) -> int:
    parents = bool(ctx.args.parents)

    def make(value: str) -> dict[str, Any]:
        ref = parse_ref(value)
        if ref.item_id is not None or ref.is_root:
            raise usage("mkdir needs a folder path", path=value)
        if parents:
            data = ctx.api.post("/drive/folders/ensure", {"path": ref.canonical})
            folder = data.get("folder") or {}
            return {"id": folder.get("id"), "path": data.get("path"), "folder": folder, "created": bool(data.get("created"))}
        try:
            existing = resolve(ctx, ref)
        except CliError as error:
            if error.code != "path_not_found":
                raise
        else:
            raise CliError("path_exists", "The path already exists", {"path": existing.get("path"), "id": item_id(existing)})
        try:
            parent = resolve_folder(ctx, ref.parent)
        except CliError as error:
            if error.code == "path_not_found":
                error.details.setdefault("hint", "bento mkdir -p")
            raise
        folder = ctx.api.post("/drive/folders", {"name": ref.name, "parent_id": folder_id_of(parent)})
        return {"id": folder["id"], "path": join_path(str(parent.get("path") or "/"), ref.name), "folder": folder, "created": True}

    return run_batch(ctx, ctx.args.paths, make, human=_render_mkdir)


def _render_mkdir(out: Output, item: dict[str, Any]) -> None:
    out.line(out.t("mkdir.created" if item.get("created") else "mkdir.exists", path=item.get("path")))


# mv / rename ---------------------------------------------------------------------------------


def _move(ctx: Context, resolved: dict[str, Any], folder_id: str | None, new_name: str | None = None) -> dict[str, Any]:
    kind = resolved.get("kind")
    if kind == "folder":
        body: dict[str, Any] = {"parent_id": folder_id}
        if new_name:
            body["name"] = new_name
        return dict(ctx.api.patch(f"/drive/folders/{resolved['folder']['id']}", body))
    if kind == "asset":
        asset_id = resolved["asset"]["id"]
        moved = ctx.api.post(f"/drive/items/{asset_id}/move", {"folder_id": folder_id})
        if new_name:
            moved = ctx.api.patch(f"/drive/items/{asset_id}", {"name": new_name})
        return dict(moved)
    raise usage("The root folder cannot be moved")


def _rename(ctx: Context, resolved: dict[str, Any], new_name: str) -> dict[str, Any]:
    kind = resolved.get("kind")
    if kind == "folder":
        return dict(ctx.api.patch(f"/drive/folders/{resolved['folder']['id']}", {"name": new_name}))
    if kind == "asset":
        return dict(ctx.api.patch(f"/drive/items/{resolved['asset']['id']}", {"name": new_name}))
    raise usage("The root folder cannot be renamed")


def _check_name(name: str) -> str:
    clean = name.strip()
    if not clean or "/" in clean or clean in {".", ".."}:
        raise usage("Invalid name", name=name)
    return clean


def mv(ctx: Context) -> int:
    sources: list[str] = list(ctx.args.sources)
    destination_text: str = ctx.args.destination
    destination_ref = parse_ref(destination_text)
    new_name: str | None = None
    try:
        destination = resolve_folder(ctx, destination_ref)
    except CliError as error:
        if error.code != "path_not_found" or len(sources) != 1 or destination_ref.item_id is not None or destination_ref.must_be_folder:
            raise
        new_name = _check_name(destination_ref.name)
        destination = resolve_folder(ctx, destination_ref.parent)
    target_folder = folder_id_of(destination)
    target_path = str(destination.get("path") or "/")

    def move_one(value: str) -> dict[str, Any]:
        source = resolve(ctx, value)
        before = source.get("path")
        _move(ctx, source, target_folder, new_name)
        name = new_name or (source["folder"]["name"] if source.get("kind") == "folder" else source["asset"]["filename"])
        return {"id": item_id(source), "kind": source.get("kind"), "from": before, "path": join_path(target_path, name), "status": "moved"}

    return run_batch(ctx, sources, move_one, human=_render_moved)


def _render_moved(out: Output, item: dict[str, Any]) -> None:
    out.line(out.t("mv.done", source=item.get("from"), target=item.get("path")))


def rename(ctx: Context) -> int:
    new_name = _check_name(ctx.args.new_name)
    source = resolve(ctx, ctx.args.path)
    before = str(source.get("path") or "/")
    _rename(ctx, source, new_name)
    parent = before.rsplit("/", 1)[0] or "/"
    item = {"id": item_id(source), "kind": source.get("kind"), "from": before, "path": join_path(parent, new_name), "status": "renamed"}
    ctx.out.result(item, _render_moved)
    return 0


# rm ------------------------------------------------------------------------------------------


def rm(ctx: Context) -> int:
    recursive = bool(ctx.args.recursive)

    def remove(value: str) -> dict[str, Any]:
        resolved = resolve(ctx, value)
        kind = resolved.get("kind")
        if kind == "root":
            raise usage("The root folder cannot be removed")
        if kind == "folder":
            if not recursive:
                raise usage("This is a folder: use rm -r", path=resolved.get("path"))
            ctx.api.delete(f"/drive/folders/{resolved['folder']['id']}")
        else:
            ctx.api.delete(f"/assets/{resolved['asset']['id']}")
        return {**resolved_summary(resolved), "status": "trashed"}

    code = run_batch(
        ctx,
        ctx.args.paths,
        remove,
        human=lambda out, item: out.line(out.t("rm.done", path=item.get("path"))),
        extra={"undo": "bento trash restore ID"},
    )
    ctx.out.note(ctx.t("rm.undo"))
    return code


# open ----------------------------------------------------------------------------------------


def open_item(ctx: Context) -> int:
    resolved = resolve(ctx, ctx.args.path)
    base = ctx.api.base_url
    document: dict[str, Any] = resolved_summary(resolved)
    if resolved.get("kind") == "asset":
        asset_id = resolved["asset"]["id"]
        document["content_url"] = f"{base}/api/assets/{asset_id}/content"
        document["download_url"] = f"{base}/api/assets/{asset_id}/download"
    document["auth"] = "bearer" if ctx.target.token else "none"
    ctx.out.result(document, lambda out, data: out.line(str(data.get("content_url") or data.get("path"))))
    return 0


PATH_HELP = ("Bento path (/A/B) or id:<id>", "Ruta de Bento (/A/B) o id:<id>")

COMMANDS = (
    Command(
        ("ls",),
        "List a folder (folders first)",
        "Lista una carpeta (carpetas primero)",
        ls,
        (
            arg("path", en=PATH_HELP[0], es=PATH_HELP[1], nargs="?"),
            arg("-l", "--long", en="Show size, type, dates and indexing state", es="Muestra tamaño, tipo, fechas y estado", action="store_true"),
            arg("--limit", en="Page size (1-200)", es="Tamaño de página (1-200)", type=int, default=100),
            arg("--cursor", en="Continue from a next_cursor", es="Continúa desde un next_cursor"),
            arg("--all", en="Follow cursors and list everything", es="Sigue los cursores y lista todo", action="store_true"),
        ),
        output="DriveListing",
    ),
    Command(
        ("tree",),
        "Nested view of a folder (server-side, bounded)",
        "Vista en árbol de una carpeta (limitada)",
        tree,
        (
            arg("path", en=PATH_HELP[0], es=PATH_HELP[1], nargs="?"),
            arg("--depth", en="Levels (1-20, default 3)", es="Niveles (1-20, por defecto 3)", type=int, default=3),
            arg("--files", en="Include files (default)", es="Incluye archivos (por defecto)", action="store_true", default=True),
            arg("--no-files", en="Only folders", es="Solo carpetas", action="store_false", dest="files"),
            arg("--max-nodes", en="Maximum nodes (default 2000)", es="Máximo de nodos (por defecto 2000)", type=int, default=2000),
        ),
        output="DriveTree",
    ),
    Command(
        ("stat",),
        "Full metadata of folders/files",
        "Metadatos completos de carpetas/archivos",
        stat,
        (arg("paths", en=PATH_HELP[0], es=PATH_HELP[1], nargs="+", metavar="PATH"),),
        output="ResolvedItems",
    ),
    Command(
        ("mkdir",),
        "Create folders (-p: parents too, reuse existing)",
        "Crea carpetas (-p: también las intermedias, reutiliza existentes)",
        mkdir,
        (
            arg("-p", "--parents", en="Create missing parents; succeed if it exists", es="Crea las intermedias; no falla si existe", action="store_true"),
            arg("paths", en="Folder path", es="Ruta de la carpeta", nargs="+", metavar="PATH"),
        ),
        output="MkdirResult",
    ),
    Command(
        ("mv",),
        "Move files/folders into DEST (or move+rename one item)",
        "Mueve archivos/carpetas a DEST (o mueve y renombra uno)",
        mv,
        (
            arg("sources", en="Items to move", es="Elementos a mover", nargs="+", metavar="SRC"),
            arg("destination", en="Destination folder", es="Carpeta de destino", metavar="DEST"),
        ),
        output="MoveResult",
    ),
    Command(
        ("rename",),
        "Rename a file or folder",
        "Renombra un archivo o carpeta",
        rename,
        (
            arg("path", en=PATH_HELP[0], es=PATH_HELP[1]),
            arg("new_name", en="New name (no '/')", es="Nombre nuevo (sin '/')", metavar="NEW_NAME"),
        ),
        output="MoveItem",
    ),
    Command(
        ("rm",),
        "Move to trash (undo with `bento trash restore`)",
        "Mueve a la papelera (deshacer con `bento trash restore`)",
        rm,
        (
            arg("-r", "--recursive", en="Allow folders", es="Permite carpetas", action="store_true"),
            arg("paths", en=PATH_HELP[0], es=PATH_HELP[1], nargs="+", metavar="PATH"),
        ),
        output="RemoveResult",
    ),
    Command(
        ("open",),
        "Print the local content URL of an item",
        "Muestra la URL local del contenido de un elemento",
        open_item,
        (arg("path", en=PATH_HELP[0], es=PATH_HELP[1]),),
        output="OpenTarget",
    ),
)
