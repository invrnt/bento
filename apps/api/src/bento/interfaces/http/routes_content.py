"""`GET /assets/{id}/content`: decrypted, range-capable streaming of an asset's original."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from bento.application.content import AssetContentService, ContentSource
from bento.domain.errors import DomainError
from bento.infrastructure.storage_pipeline import StoragePipelineComponents, get_storage_pipeline

router = APIRouter()

STREAM_CHUNK_BYTES = 1024 * 1024
CONTENT_SECURITY_POLICY = "default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'; sandbox"


class RangeNotSatisfiableError(ValueError):
    pass


def parse_byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Inclusive `(start, end)` of a single `bytes=` range, or None to serve the whole file.

    Other units and multi-range requests are ignored (full response). Malformed or unsatisfiable byte ranges
    raise `RangeNotSatisfiableError` (416).
    """
    if header is None:
        return None
    unit, _, spec = header.strip().partition("=")
    if unit.strip().lower() != "bytes":
        return None
    spec = spec.strip()
    if "," in spec:
        return None
    first, separator, last = (part.strip() for part in spec.partition("-"))
    if not separator or (first and not first.isdigit()) or (last and not last.isdigit()) or not (first or last):
        raise RangeNotSatisfiableError(spec)
    if not first:
        suffix = int(last)
        if suffix == 0 or size == 0:
            raise RangeNotSatisfiableError(spec)
        return max(0, size - suffix), size - 1
    start = int(first)
    end = int(last) if last else size - 1
    if end < start or start >= size:
        raise RangeNotSatisfiableError(spec)
    return start, min(end, size - 1)


def inline_disposition(filename: str) -> str:
    fallback = "".join(ch if 32 <= ord(ch) < 127 and ch not in '"\\;' else "_" for ch in filename) or "file"
    return f"inline; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def pipeline(request: Request) -> StoragePipelineComponents:
    override = getattr(request.app.state, "storage_pipeline", None)
    if override is not None:
        return override
    return get_storage_pipeline(request.app.state.settings)


def error_response(request: Request, error: DomainError) -> JSONResponse:
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    return JSONResponse(
        status_code=_status_code(error),
        content={
            "error": {"code": error.code, "message": error.message, "details": error.details, "request_id": request_id}
        },
    )


def _status_code(error: DomainError) -> int:
    if error.code.endswith("_not_found") and error.code != "vault_not_found":
        return 404
    if error.code in {"settings_source_locked", "settings_revision_conflict", "duplicate_asset"}:
        return 409
    if error.code == "unsupported_media_type":
        return 415
    if error.code in {"storage_unavailable", "vault_locked", "vault_not_found", "telegram_not_authorized", "telegram_flood_wait"}:
        return 503
    if error.code == "integrity_failed":
        return 502
    return 400


@router.head("/assets/{asset_id}/content", response_model=None, include_in_schema=False)
@router.get("/assets/{asset_id}/content", response_model=None)
async def asset_content(asset_id: str, request: Request) -> Response:
    try:
        content = pipeline(request).content
        source = await content.open_original(asset_id)
    except DomainError as exc:
        return error_response(request, exc)
    size = source.size_bytes
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Content-Disposition": inline_disposition(source.asset.filename),
        "Content-Security-Policy": CONTENT_SECURITY_POLICY,
        "X-Content-Type-Options": "nosniff",
    }
    try:
        byte_range = parse_byte_range(request.headers.get("range"), size)
    except RangeNotSatisfiableError:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})
    status = 200
    start, end = 0, size - 1
    if byte_range is not None:
        start, end = byte_range
        status = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    length = max(0, end - start + 1)
    headers["Content-Length"] = str(length)
    media_type = source.asset.metadata.mime_type
    if request.method == "HEAD" or length == 0:
        return Response(status_code=status, headers=headers, media_type=media_type)
    try:
        first = await content.read_source_range(source, start, min(STREAM_CHUNK_BYTES, length))
    except DomainError as exc:
        return error_response(request, exc)
    return StreamingResponse(
        _stream(content, source, first, start, length),
        status_code=status,
        headers=headers,
        media_type=media_type,
    )


async def _stream(
    content: AssetContentService, source: ContentSource, first: bytes, start: int, length: int
) -> AsyncIterator[bytes]:
    yield first
    position = start + len(first)
    remaining = length - len(first)
    while remaining > 0 and first:
        chunk = await content.read_source_range(source, position, min(STREAM_CHUNK_BYTES, remaining))
        if not chunk:
            break
        yield chunk
        position += len(chunk)
        remaining -= len(chunk)
