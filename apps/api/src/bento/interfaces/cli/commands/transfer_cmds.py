"""upload, download, cat."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from bento.interfaces.cli.catalog import Command, arg
from bento.interfaces.cli.commands.common import resolve
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.errors import EXIT_PARTIAL, CliError, usage
from bento.interfaces.cli.local_files import WalkOptions, safe_local_name
from bento.interfaces.cli.output import Output, human_size
from bento.interfaces.cli.transfer import Downloader, Uploader, UploadOptions, planned_bytes, summarize

WAIT_POLL_SECONDS = 2.0


def upload(ctx: Context) -> int:
    args = ctx.args
    if args.jobs < 1 or args.jobs > 16:
        raise usage("--jobs must be between 1 and 16")
    options = UploadOptions(
        to=args.to or "/",
        walk=WalkOptions(
            include=tuple(args.include or ()),
            exclude=tuple(args.exclude or ()),
            hidden=bool(args.hidden),
            follow_symlinks=bool(args.follow_symlinks),
            flatten=bool(args.flatten),
        ),
        jobs=args.jobs,
        dry_run=bool(args.dry_run),
        dedupe=not args.no_dedupe,
    )
    progress = None
    uploader = Uploader(ctx.api, options, on_bytes=lambda amount: progress.advance(amount) if progress else None)
    ctx.out.note(ctx.t("upload.scanning"))
    entries = uploader.plan(args.local)
    uploader.hash_all(entries)
    uploader.lookup(entries)
    if not options.dry_run:
        uploader.ensure_folders(entries)
        progress = ctx.out.progress(planned_bytes(entries), ctx.t("upload.progress"))
        uploader.upload_all(entries)
        progress.close()
    document = summarize(entries, to=options.to, dry_run=options.dry_run)
    if args.wait and not options.dry_run and document["uploaded"]:
        document["remote"] = _wait_remote(ctx)
    ctx.out.result(document, _render_upload)
    return EXIT_PARTIAL if document["failed"] else 0


def _wait_remote(ctx: Context) -> dict[str, Any]:
    """`--wait`: until `activity.uploads` is idle (the worker encrypts and sends to Telegram)."""
    limit = ctx.flag("timeout")
    deadline = time.monotonic() + (float(limit) if limit else 3600.0)
    ctx.out.note(ctx.t("upload.waiting_remote"))
    while True:
        activity = ctx.api.get("/activity")
        uploads = activity.get("uploads") or {}
        if not uploads.get("active") and not uploads.get("queued"):
            return {"idle": True, "summary": activity.get("summary")}
        if time.monotonic() >= deadline:
            return {"idle": False, "summary": activity.get("summary"), "uploads": uploads}
        time.sleep(WAIT_POLL_SECONDS)


def _render_upload(out: Output, data: dict[str, Any]) -> None:
    for item in data["items"]:
        status = item["status"]
        if status == "failed":
            error = item.get("error") or {}
            out.line(f"✗ {item['local_path']}: {out.t.error_message(error.get('code', ''), error.get('message', ''), error.get('details') or {})}")
        elif status == "duplicate" and not out.quiet:
            out.line(out.t("upload.duplicate", local=item["local_path"], path=item.get("path") or "?"))
        elif status == "uploaded" and not out.quiet:
            out.line(f"✓ {item['local_path']} → {item.get('path')}")
        elif status == "planned":
            out.line(out.t("upload.planned", local=item["local_path"]))
    if data["dry_run"]:
        out.line(out.t("upload.dry_run_summary", planned=data.get("planned", 0), duplicates=data["duplicates"], skipped=data["skipped"], size=human_size(data.get("planned_bytes", 0), out.lang)))
    else:
        out.line(
            out.t(
                "upload.summary",
                uploaded=data["uploaded"],
                duplicates=data["duplicates"],
                skipped=data["skipped"],
                failed=data["failed"],
                size=human_size(data["bytes"], out.lang),
            )
        )
        if data["uploaded"]:
            out.note(out.t("upload.remote_hint"))


def download(ctx: Context) -> int:
    args = ctx.args
    directory = Path(args.to or ".").expanduser()
    if directory.exists() and not directory.is_dir():
        raise usage("--to must be a directory", to=str(directory))
    resolved_items = [resolve(ctx, value) for value in args.paths]
    for resolved in resolved_items:
        if resolved.get("kind") in {"folder", "root"} and not args.recursive:
            raise usage("This is a folder: use download -r", path=resolved.get("path"))
    total = sum(int((item.get("asset") or {}).get("size_bytes") or 0) for item in resolved_items)
    progress = ctx.out.progress(total, ctx.t("download.progress"))
    downloader = Downloader(ctx.api, overwrite=bool(args.overwrite), on_bytes=progress.advance)
    for resolved in resolved_items:
        kind = resolved.get("kind")
        path = str(resolved.get("path") or "/")
        if kind == "asset":
            downloader.file(resolved["asset"], path, directory)
        elif kind == "folder":
            folder = resolved["folder"]
            downloader.folder(str(folder["id"]), path, directory / safe_local_name(str(folder.get("name") or folder["id"])))
        else:
            downloader.folder(None, "/", directory)
    progress.close()
    document = downloader.summary()
    document["to"] = str(directory.resolve())
    ctx.out.result(document, _render_download)
    return EXIT_PARTIAL if document["failed"] else 0


def _render_download(out: Output, data: dict[str, Any]) -> None:
    for item in data["items"]:
        if item["status"] == "failed":
            error = item.get("error") or {}
            out.line(f"✗ {item['path']}: {error.get('message', '')}")
        elif item["status"] == "skipped":
            out.line(out.t("download.exists", local=item["local_path"]))
        elif not out.quiet:
            out.line(f"✓ {item['path']} → {item['local_path']}")
    out.line(out.t("download.summary", downloaded=data["downloaded"], skipped=data["skipped"], failed=data["failed"], size=human_size(data["bytes"], out.lang)))
    if data["skipped"]:
        out.note(out.t("download.overwrite_hint"))


def cat(ctx: Context) -> int:
    resolved = resolve(ctx, ctx.args.path)
    if resolved.get("kind") != "asset":
        raise CliError("not_a_file", "cat needs a file", {"path": resolved.get("path")}, 2)
    stream = getattr(ctx.out.stdout, "buffer", None)
    with ctx.api.stream("GET", f"/assets/{resolved['asset']['id']}/content") as response:
        for chunk in response.iter_bytes(1024 * 1024):
            if stream is not None:
                stream.write(chunk)
            else:
                ctx.out.stdout.write(chunk.decode("utf-8", "replace"))
    (stream or ctx.out.stdout).flush()
    return 0


COMMANDS = (
    Command(
        ("upload",),
        "Upload files and directory trees (dedupe by content; resumable)",
        "Sube archivos y carpetas completas (sin duplicados; reanudable)",
        upload,
        (
            arg("local", en="Local files or directories (DIR/ uploads only its contents)", es="Archivos o carpetas locales (DIR/ sube solo su contenido)", nargs="+", metavar="LOCAL"),
            arg("--to", en="Destination Bento folder (created like mkdir -p; default /)", es="Carpeta de destino en Bento (se crea como mkdir -p; por defecto /)", metavar="PATH"),
            arg("--exclude", en="Skip names/relative paths matching GLOB (repeatable)", es="Omite nombres/rutas que coincidan con GLOB (repetible)", action="append", metavar="GLOB"),
            arg("--include", en="Only upload files matching GLOB (repeatable)", es="Solo sube archivos que coincidan con GLOB (repetible)", action="append", metavar="GLOB"),
            arg("--hidden", en="Include hidden files and OS junk", es="Incluye archivos ocultos y basura del sistema", action="store_true"),
            arg("--follow-symlinks", en="Follow symbolic links while walking", es="Sigue enlaces simbólicos", action="store_true"),
            arg("--flatten", en="Put every file directly in --to", es="Pone todos los archivos directamente en --to", action="store_true"),
            arg("--jobs", en="Concurrent uploads (default 2)", es="Subidas simultáneas (por defecto 2)", type=int, default=2),
            arg("--dry-run", en="Plan only: hash and check duplicates, change nothing", es="Solo planifica: calcula hashes y duplicados, sin cambios", action="store_true"),
            arg("--no-dedupe", en="Skip the duplicate pre-check (the API still deduplicates)", es="Omite la comprobación previa de duplicados", action="store_true"),
            arg("--wait", en="Wait until the encrypted copies reach Telegram", es="Espera a que las copias cifradas lleguen a Telegram", action="store_true"),
        ),
        output="UploadSummary",
    ),
    Command(
        ("download",),
        "Download files (or folders with -r); never overwrites without --overwrite",
        "Descarga archivos (o carpetas con -r); nunca sobrescribe sin --overwrite",
        download,
        (
            arg("paths", en="Bento paths or id:", es="Rutas de Bento o id:", nargs="+", metavar="PATH"),
            arg("--to", en="Local directory (default: current)", es="Carpeta local (por defecto: la actual)", metavar="DIR"),
            arg("-r", "--recursive", en="Download folders recreating the tree", es="Descarga carpetas recreando el árbol", action="store_true"),
            arg("--overwrite", en="Replace existing local files", es="Reemplaza archivos locales existentes", action="store_true"),
        ),
        output="DownloadSummary",
    ),
    Command(
        ("cat",),
        "Write one file's content to stdout",
        "Escribe el contenido de un archivo en stdout",
        cat,
        (arg("path", en="Bento path or id:", es="Ruta de Bento o id:"),),
        output="bytes",
    ),
)

