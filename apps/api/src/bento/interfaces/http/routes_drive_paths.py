"""Path-addressed Drive routes for the CLI (`api/cli-endpoints.md`). Rules live in `application/drive_paths.py`."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import ModuleType
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bento.application.drive_paths import (
    DEFAULT_TREE_DEPTH,
    DEFAULT_TREE_NODES,
    DrivePathUseCases,
    DriveTreeNode,
    ResolvedDriveItem,
)
from bento.domain.drive_paths import ROOT_PATH, DriveNodeKind, parse_drive_ref
from bento.domain.errors import DomainError

router = APIRouter()


class EnsureFolderRequest(BaseModel):
    path: str


class DrivePathsRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class AssetLookupRequest(BaseModel):
    sha256: list[str] = Field(default_factory=list)


@router.get("/drive/resolve", response_model=None)
async def resolve_drive_path(request: Request, path: str = ROOT_PATH) -> dict[str, Any] | JSONResponse:
    async def run(use_cases: DrivePathUseCases) -> dict[str, Any]:
        return _resolved(await use_cases.resolve(parse_drive_ref(path)))

    return await _handle(request, run)


@router.post("/drive/folders/ensure", response_model=None)
async def ensure_drive_folder(request: Request, body: EnsureFolderRequest) -> dict[str, Any] | JSONResponse:
    async def run(use_cases: DrivePathUseCases) -> dict[str, Any]:
        result = await use_cases.ensure_folder(parse_drive_ref(body.path))
        return {
            "folder": _http()._folder_response(result.folder).model_dump() if result.folder is not None else None,
            "path": result.path,
            "created": list(result.created),
        }

    return await _handle(request, run)


@router.get("/drive/tree", response_model=None)
async def drive_tree(
    request: Request,
    path: str = ROOT_PATH,
    depth: int = DEFAULT_TREE_DEPTH,
    include_assets: bool = True,
    max_nodes: int = DEFAULT_TREE_NODES,
) -> dict[str, Any] | JSONResponse:
    async def run(use_cases: DrivePathUseCases) -> dict[str, Any]:
        result = await use_cases.tree(
            parse_drive_ref(path), depth=depth, include_assets=include_assets, max_nodes=max_nodes
        )
        return {"root": _tree_node(result.root), "truncated": result.truncated, "nodes": result.nodes}

    return await _handle(request, run)


@router.post("/drive/paths", response_model=None)
async def drive_paths(request: Request, body: DrivePathsRequest) -> dict[str, Any] | JSONResponse:
    async def run(use_cases: DrivePathUseCases) -> dict[str, Any]:
        result = await use_cases.paths_for_ids(body.ids)
        return {"paths": result.paths, "missing": list(result.missing)}

    return await _handle(request, run)


@router.post("/assets/lookup", response_model=None)
async def lookup_assets(request: Request, body: AssetLookupRequest) -> dict[str, Any] | JSONResponse:
    async def run(use_cases: DrivePathUseCases) -> dict[str, Any]:
        matches = await use_cases.lookup_sha256(body.sha256)
        http = _http()
        return {
            "items": {
                sha256: {"asset": http._asset_response(match.asset).model_dump(), "path": match.path}
                for sha256, match in matches.items()
            }
        }

    return await _handle(request, run)


def drive_path_use_cases(request: Request) -> DrivePathUseCases:
    cached = getattr(request.app.state, "drive_path_use_cases", None)
    if cached is not None:
        return cached
    product = _http()._product_dependencies(request)
    use_cases = DrivePathUseCases(folders=product.folders, assets=product.assets, drive=product.drive)
    request.app.state.drive_path_use_cases = use_cases
    return use_cases


async def _handle(
    request: Request, run: Callable[[DrivePathUseCases], Awaitable[dict[str, Any]]]
) -> dict[str, Any] | JSONResponse:
    try:
        return await run(drive_path_use_cases(request))
    except DomainError as exc:
        return _http()._domain_error_response(request, exc)


def _resolved(item: ResolvedDriveItem) -> dict[str, Any]:
    http = _http()
    return {
        "kind": item.kind.value,
        "path": item.path,
        "folder": http._folder_response(item.folder).model_dump() if item.folder is not None else None,
        "asset": http._asset_response(item.asset).model_dump() if item.asset is not None else None,
        "breadcrumbs": [{"id": folder.id, "name": folder.name} for folder in item.breadcrumbs],
    }


def _tree_node(node: DriveTreeNode) -> dict[str, Any]:
    body: dict[str, Any] = {"kind": node.kind.value, "id": node.id, "name": node.name, "path": node.path}
    if node.asset is not None:
        body["size_bytes"] = node.asset.metadata.size_bytes
        body["mime_type"] = node.asset.metadata.mime_type
        body["created_at"] = node.asset.created_at.isoformat()
    elif node.folder is not None:
        body["created_at"] = node.folder.created_at.isoformat()
    if node.kind != DriveNodeKind.ASSET and node.children is not None:
        body["children"] = [_tree_node(child) for child in node.children]
    if node.has_more:
        body["has_more"] = True
    return body


def _http() -> ModuleType:
    """`routes.py` (shared Drive response builders and dependencies), imported lazily because it includes
    this router at import time."""
    from bento.interfaces.http import routes

    return routes
