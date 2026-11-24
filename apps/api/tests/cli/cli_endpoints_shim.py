"""Test-only stand-in for the CLI-support endpoints of `api/cli-endpoints.md`.

Agent 31 builds the real `/drive/resolve`, `/drive/folders/ensure`, `/drive/tree`, `/drive/paths` and
`/assets/lookup` in parallel. Until they are merged, integration tests mount this shim, which implements
the same contract on top of the existing Drive endpoints (through the app's own ASGI interface), so the
CLI journeys run end to end. When the app already serves `/api/drive/resolve`, the shim is not mounted
and the tests exercise the real endpoints.
"""

from __future__ import annotations

import unicodedata
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

HEADERS = {"X-Bento-Client": "web"}


def has_real_endpoints(app: FastAPI) -> bool:
    return any(getattr(route, "path", "") == "/api/drive/resolve" for route in app.routes)


def install(app: FastAPI) -> bool:
    if has_real_endpoints(app):
        return False
    router = APIRouter()

    def client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers=HEADERS)

    def error(status: int, code: str, details: dict[str, Any]) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": code, "details": details, "request_id": "shim"}})

    async def children(http: httpx.AsyncClient, folder_id: str | None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor = None
        while True:
            params: dict[str, Any] = {"limit": 200}
            if folder_id:
                params["folder_id"] = folder_id
            if cursor:
                params["cursor"] = cursor
            page = (await http.get("/api/drive/items", params=params)).json()
            items.extend(page["items"])
            cursor = page.get("next_cursor")
            if not cursor:
                return items

    def fmt(names: list[str]) -> str:
        return "/" + "/".join(name.replace("/", "\\/") for name in names) if names else "/"

    async def folder_chain(http: httpx.AsyncClient, folder_id: str | None) -> list[dict[str, Any]]:
        if folder_id is None:
            return []
        page = (await http.get("/api/drive/items", params={"folder_id": folder_id, "limit": 1})).json()
        return [{"id": crumb["folder_id"], "name": crumb["name"]} for crumb in page.get("breadcrumbs") or []]

    def parse(text: str) -> tuple[list[str], bool] | JSONResponse:
        raw = text.strip()
        must = raw.endswith("/") and raw not in {"", "/"}
        body = raw[1:] if raw.startswith("/") else raw
        body = body[:-1] if body.endswith("/") else body
        if not body:
            return [], False
        segments = [unicodedata.normalize("NFC", part) for part in body.split("/")]
        for segment in segments:
            if segment == "":
                return error(400, "validation_failed", {"reason": "empty_segment"})
            if segment in {".", ".."}:
                return error(400, "validation_failed", {"reason": "dot_segment"})
        return segments, must

    async def resolve_text(http: httpx.AsyncClient, text: str) -> dict[str, Any] | JSONResponse:
        if text.startswith("id:"):
            item_id = text[3:]
            if item_id.startswith("folder_"):
                page = await http.get("/api/drive/items", params={"folder_id": item_id, "limit": 1})
                chain = [{"id": c["folder_id"], "name": c["name"]} for c in page.json().get("breadcrumbs") or []]
                if page.status_code != 200 or not chain:
                    return error(404, "path_not_found", {"path": text, "missing_from": 0})
                parent_id = chain[-2]["id"] if len(chain) > 1 else None
                folder = next(item["folder"] for item in await children(http, parent_id) if item["id"] == item_id)
                return {"kind": "folder", "path": fmt([c["name"] for c in chain]), "folder": folder, "asset": None, "breadcrumbs": chain}
            response = await http.get(f"/api/assets/{item_id}")
            if response.status_code != 200:
                return error(404, "path_not_found", {"path": text, "missing_from": 0})
            asset = response.json()
            chain = await folder_chain(http, asset["folder_id"])
            return {"kind": "asset", "path": fmt([c["name"] for c in chain] + [asset["filename"]]), "folder": None, "asset": asset, "breadcrumbs": chain}
        parsed = parse(text)
        if isinstance(parsed, JSONResponse):
            return parsed
        segments, must = parsed
        if not segments:
            return {"kind": "root", "path": "/", "folder": None, "asset": None, "breadcrumbs": []}
        parent: str | None = None
        chain: list[dict[str, Any]] = []
        for index, segment in enumerate(segments):
            last = index == len(segments) - 1
            items = await children(http, parent)
            matches = [item for item in items if unicodedata.normalize("NFC", item["name"]) == segment]
            if not last or must:
                folders = [item for item in matches if item["type"] == "folder"]
                matches = folders if (not last or must) else matches
            if not matches:
                return error(404, "path_not_found", {"path": fmt(segments), "missing_from": index})
            if len(matches) > 1:
                candidates = [
                    {"id": item["id"], "kind": "folder" if item["type"] == "folder" else "asset", "path": fmt(segments[: index + 1]), "created_at": (item.get("folder") or item.get("asset") or {}).get("created_at")}
                    for item in matches
                ]
                return error(409, "path_ambiguous", {"path": fmt(segments[: index + 1]), "candidates": candidates})
            match = matches[0]
            if last:
                if match["type"] == "folder":
                    chain.append({"id": match["id"], "name": match["name"]})
                    return {"kind": "folder", "path": fmt(segments), "folder": match["folder"], "asset": None, "breadcrumbs": chain}
                return {"kind": "asset", "path": fmt(segments), "folder": None, "asset": match["asset"], "breadcrumbs": chain}
            if match["type"] != "folder":
                return error(404, "path_not_found", {"path": fmt(segments), "missing_from": index})
            chain.append({"id": match["id"], "name": match["name"]})
            parent = match["id"]
        raise AssertionError

    @router.get("/drive/resolve")
    async def resolve(path: str = "/") -> Any:
        async with client() as http:
            return await resolve_text(http, path)

    @router.post("/drive/folders/ensure")
    async def ensure(request: Request) -> Any:
        body = await request.json()
        parsed = parse(str(body.get("path", "")))
        if isinstance(parsed, JSONResponse):
            return parsed
        segments, _ = parsed
        created: list[str] = []
        folder: dict[str, Any] | None = None
        async with client() as http:
            parent: str | None = None
            for segment in segments:
                existing = sorted(
                    (item["folder"] for item in await children(http, parent) if item["type"] == "folder" and item["name"] == segment),
                    key=lambda value: (value["created_at"], value["id"]),
                )
                if existing:
                    folder = existing[0]
                else:
                    folder = (await http.post("/api/drive/folders", json={"name": segment, "parent_id": parent})).json()
                    created.append(folder["id"])
                parent = folder["id"]
        return {"folder": folder, "path": fmt(segments), "created": created}

    async def node(http: httpx.AsyncClient, item: dict[str, Any] | None, path: str, depth: int, include_assets: bool, counter: list[int]) -> dict[str, Any]:
        if item is None:
            data: dict[str, Any] = {"kind": "root", "id": None, "name": "", "path": "/"}
            folder_id = None
        else:
            data = {"kind": "folder", "id": item["id"], "name": item["name"], "path": path, "created_at": item["folder"]["created_at"]}
            folder_id = item["id"]
        entries = await children(http, folder_id)
        if depth <= 0:
            if entries:
                data["has_more"] = True
            return data
        kids = []
        for entry in sorted(entries, key=lambda e: (0 if e["type"] == "folder" else 1, e["name"].casefold(), e["id"])):
            child_path = (path.rstrip("/") if path != "/" else "") + "/" + entry["name"]
            counter[0] += 1
            if entry["type"] == "folder":
                kids.append(await node(http, entry, child_path, depth - 1, include_assets, counter))
            elif include_assets:
                asset = entry["asset"]
                kids.append({"kind": "asset", "id": entry["id"], "name": entry["name"], "path": child_path, "size_bytes": asset["size_bytes"], "mime_type": asset["mime_type"], "created_at": asset["created_at"]})
        data["children"] = kids
        return data

    @router.get("/drive/tree")
    async def tree(path: str = "/", depth: int = 3, include_assets: bool = True, max_nodes: int = 2000) -> Any:
        async with client() as http:
            resolved = await resolve_text(http, path)
            if isinstance(resolved, JSONResponse):
                return resolved
            if resolved["kind"] == "asset":
                return error(400, "validation_failed", {"reason": "not_a_folder"})
            item = None if resolved["kind"] == "root" else {"id": resolved["folder"]["id"], "name": resolved["folder"]["name"], "folder": resolved["folder"]}
            counter = [0]
            root = await node(http, item, resolved["path"], depth, include_assets, counter)
            return {"root": root, "truncated": False, "nodes": counter[0]}

    @router.post("/drive/paths")
    async def paths(request: Request) -> Any:
        ids = (await request.json()).get("ids") or []
        found: dict[str, str] = {}
        missing: list[str] = []
        async with client() as http:
            for item_id in ids:
                resolved = await resolve_text(http, f"id:{item_id}")
                if isinstance(resolved, JSONResponse):
                    missing.append(item_id)
                else:
                    found[item_id] = resolved["path"]
        return {"paths": found, "missing": missing}

    @router.post("/assets/lookup")
    async def lookup(request: Request) -> Any:
        wanted = set((await request.json()).get("sha256") or [])
        items: dict[str, Any] = {}
        async with client() as http:
            stack: list[tuple[str | None, list[str]]] = [(None, [])]
            while stack:
                folder_id, names = stack.pop()
                for entry in await children(http, folder_id):
                    if entry["type"] == "folder":
                        stack.append((entry["id"], [*names, entry["name"]]))
                    elif entry["asset"]["sha256"] in wanted:
                        items[entry["asset"]["sha256"]] = {"asset": entry["asset"], "path": fmt([*names, entry["name"]])}
        return {"items": items}

    app.include_router(router, prefix="/api")
    # Registered after the existing `/drive/folders/{folder_id}` routes: move ours first so that
    # `POST /drive/folders/ensure` is not captured as a folder id.
    ours = [route for route in app.router.routes if getattr(route, "endpoint", None) in {resolve, ensure, tree, paths, lookup}]
    others = [route for route in app.router.routes if route not in ours]
    app.router.routes[:] = ours + others
    return True
