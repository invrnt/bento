"""Agent helpers: command catalog, the packaged agent guide, and a raw authenticated API call."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

from bento.interfaces.cli import cli_version
from bento.interfaces.cli.catalog import Command, arg, catalog_document
from bento.interfaces.cli.client import decode_json
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.errors import usage
from bento.interfaces.cli.output import Output

METHODS = ("GET", "POST", "PATCH", "PUT", "DELETE")


def commands(ctx: Context) -> int:
    document = catalog_document(cli_version())

    def render(out: Output, doc: dict[str, Any]) -> None:
        width = max(len(command["name"]) for command in doc["commands"])
        for command in doc["commands"]:
            out.line(f"{command['name'].ljust(width)}  {command['description']}")

    ctx.out.result(document, render)
    return 0


def guide_text() -> str:
    return resources.files("bento.interfaces.cli").joinpath("guide.md").read_text(encoding="utf-8")


def guide(ctx: Context) -> int:
    text = guide_text()
    if ctx.out.json_mode:
        ctx.out.result({"format": "markdown", "guide": text})
    else:
        ctx.out.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def _body(value: str | None) -> Any:
    if value is None:
        return None
    raw = Path(value[1:]).expanduser().read_text(encoding="utf-8") if value.startswith("@") else value
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise usage("--data must be JSON (or @file with JSON)") from exc


def _query(values: list[str] | None) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in values or []:
        key, separator, value = item.partition("=")
        if not separator or not key:
            raise usage("Use --query KEY=VALUE", value=item)
        params[key] = value
    return params


def api(ctx: Context) -> int:
    method = ctx.args.method.upper()
    if method not in METHODS:
        raise usage("Unsupported method", method=method, allowed=list(METHODS))
    path = ctx.args.path if ctx.args.path.startswith("/") else "/" + ctx.args.path
    body = _body(ctx.args.data)
    if ctx.args.verbose:
        # The bearer token is never shown.
        ctx.out.stderr.write(f"> {method} {ctx.api.base_url}{path if path.startswith('/api') else '/api' + path}\n")
        ctx.out.stderr.write("> Authorization: Bearer [redacted]\n" if ctx.target.token else "")
        ctx.out.stderr.write("> X-Bento-Client: web\n")
    response = ctx.api.send(method, path, params=_query(ctx.args.query) or None, json=body)
    if ctx.args.verbose:
        ctx.out.stderr.write(f"< {response.status_code} {response.headers.get('content-type', '')}\n")
    content_type = response.headers.get("content-type", "")
    if "json" in content_type or not response.content:
        ctx.out.json(decode_json(response))
    else:
        stream = getattr(ctx.out.stdout, "buffer", None)
        if stream is not None:
            stream.write(response.content)
            stream.flush()
        else:
            ctx.out.stdout.write(response.text)
    return 0


COMMANDS = (
    Command(("commands",), "Command catalog (use --json)", "Catálogo de comandos (usa --json)", commands, output="CommandCatalog"),
    Command(("guide",), "Guide for AI agents organizing files with Bento", "Guía para agentes de IA que organizan archivos con Bento", guide, output="markdown"),
    Command(
        ("api",),
        "Authenticated raw call to the local API (escape hatch)",
        "Llamada directa y autenticada a la API local",
        api,
        (
            arg("method", en="HTTP method", es="Método HTTP", metavar="METHOD"),
            arg("path", en="Path under /api (e.g. /drive/items)", es="Ruta bajo /api (p. ej. /drive/items)", metavar="PATH"),
            arg("--data", en="JSON body or @file", es="Cuerpo JSON o @archivo", metavar="JSON"),
            arg("--query", en="Query parameter (repeatable)", es="Parámetro de consulta (repetible)", action="append", metavar="K=V"),
            arg("--verbose", en="Show the request on stderr (token redacted)", es="Muestra la petición en stderr (sin el token)", action="store_true"),
        ),
        output="ApiResponse",
    ),
)
