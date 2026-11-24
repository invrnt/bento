"""Helpers shared by command handlers: target resolution of paths, pagination, batches, item rendering."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import Any

from bento.interfaces.cli.context import Context
from bento.interfaces.cli.errors import EXIT_PARTIAL, CliError
from bento.interfaces.cli.output import Output, human_date, human_size
from bento.interfaces.cli.paths import BentoRef, join_path, parse_ref

PATHS_BATCH = 500


# Resolution ----------------------------------------------------------------------------------


def resolve(ctx: Context, text: str | BentoRef) -> dict[str, Any]:
    """`GET /drive/resolve` → `ResolvedItem {kind, path, folder, asset, breadcrumbs}`."""
    ref = parse_ref(text) if isinstance(text, str) else text
    data = ctx.api.get("/drive/resolve", {"path": ref.text})
    if not isinstance(data, dict):
        raise CliError("unexpected_response", "Unexpected response from /drive/resolve", {}, 1)
    return data


def item_id(resolved: dict[str, Any]) -> str | None:
    kind = resolved.get("kind")
    if kind == "folder" and resolved.get("folder"):
        return str(resolved["folder"]["id"])
    if kind == "asset" and resolved.get("asset"):
        return str(resolved["asset"]["id"])
    return None


def resolve_folder(ctx: Context, text: str | BentoRef) -> dict[str, Any]:
    """Like `resolve`, but the item must be the root or a folder (`not_a_folder`, exit 4)."""
    resolved = resolve(ctx, text)
    if resolved.get("kind") not in {"root", "folder"}:
        raise CliError(
            "not_a_folder",
            "The path is a file, not a folder",
            {"path": resolved.get("path")},
        )
    return resolved


def folder_id_of(resolved: dict[str, Any]) -> str | None:
    return str(resolved["folder"]["id"]) if resolved.get("kind") == "folder" and resolved.get("folder") else None


def paths_for(ctx: Context, ids: Sequence[str]) -> dict[str, str]:
    """`POST /drive/paths` in batches; unknown ids are left out."""
    unique = list(dict.fromkeys(item for item in ids if item))
    found: dict[str, str] = {}
    for start in range(0, len(unique), PATHS_BATCH):
        data = ctx.api.post("/drive/paths", {"ids": unique[start : start + PATHS_BATCH]})
        if isinstance(data, dict) and isinstance(data.get("paths"), dict):
            found.update({str(key): str(value) for key, value in data["paths"].items()})
    return found


# Pagination ----------------------------------------------------------------------------------


def pages(
    ctx: Context, path: str, params: dict[str, Any], *, follow: bool, key: str = "items"
) -> tuple[list[Any], str | None, dict[str, Any]]:
    """Fetch one page, or every page when `follow`; returns (items, next_cursor, last page)."""
    items: list[Any] = []
    cursor = params.get("cursor")
    last: dict[str, Any] = {}
    while True:
        page = ctx.api.get(path, {**params, "cursor": cursor})
        last = page if isinstance(page, dict) else {}
        items.extend(last.get(key) or [])
        cursor = last.get("next_cursor")
        if not follow or not cursor:
            return items, cursor, last


def iterate(ctx: Context, path: str, params: dict[str, Any], key: str = "items") -> Iterator[Any]:
    cursor: str | None = None
    while True:
        page = ctx.api.get(path, {**params, "cursor": cursor})
        if not isinstance(page, dict):
            return
        yield from page.get(key) or []
        cursor = page.get("next_cursor")
        if not cursor:
            return


# Batches -------------------------------------------------------------------------------------


def run_batch(
    ctx: Context,
    inputs: Sequence[str],
    action: Callable[[str], dict[str, Any]],
    *,
    human: Callable[[Output, dict[str, Any]], None],
    extra: dict[str, Any] | None = None,
) -> int:
    """One input: errors propagate with their own exit code. Several: per-item results, exit 7 on any failure."""
    if len(inputs) == 1:
        item = action(inputs[0])
        document = {"items": [item], **(extra or {})}
        ctx.out.result(document, lambda out, data: human(out, data["items"][0]))
        return 0
    items: list[dict[str, Any]] = []
    failed = 0
    for value in inputs:
        try:
            items.append(action(value))
        except CliError as error:
            failed += 1
            items.append({"input": value, "status": "failed", "error": error.to_json()["error"]})
    document = {"items": items, "failed": failed, **(extra or {})}

    def render(out: Output, data: dict[str, Any]) -> None:
        for item in data["items"]:
            if item.get("status") == "failed":
                error = item["error"]
                out.line(f"✗ {item['input']}: {out.t.error_message(error['code'], error['message'], error['details'])}")
            else:
                human(out, item)

    ctx.out.result(document, render)
    return EXIT_PARTIAL if failed else 0


# Rendering -----------------------------------------------------------------------------------


def drive_item(entry: dict[str, Any], parent_path: str) -> dict[str, Any]:
    """`DriveItemResponse` plus `path`."""
    return {**entry, "path": join_path(parent_path, str(entry.get("name", "")))}


def kind_label(out: Output, kind: str | None) -> str:
    return out.t(f"kind.{kind}") if kind else "-"


def size_text(out: Output, value: Any) -> str:
    return human_size(value if isinstance(value, int) else None, out.lang)


def date_text(value: Any) -> str:
    return human_date(value if isinstance(value, str) else None)


def resolved_summary(resolved: dict[str, Any]) -> dict[str, Any]:
    """A compact `{id, kind, path}` for results."""
    return {"id": item_id(resolved), "kind": resolved.get("kind"), "path": resolved.get("path")}


def require_value(ctx: Context, value: str | None, *, prompt_key: str, flag: str, secret: bool = False) -> str:
    """A value from a flag, or a TTY prompt; otherwise a usage error (non-interactive by default)."""
    if value:
        return value
    if ctx.out.interactive and not ctx.out.json_mode:
        answer = ctx.out.prompt(ctx.t(prompt_key), secret=secret)
        if answer:
            return answer
    raise CliError("usage_error", f"Missing value: pass {flag}", {"flag": flag}, 2)
