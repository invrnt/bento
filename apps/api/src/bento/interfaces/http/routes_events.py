"""`GET /events`: Server-Sent Events announcing which parts of the library changed (`application/events.py`).

Guarded like every other route (loopback host check and, when configured, the bearer token).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from bento.application.events import MAX_STREAM_SECONDS, ChangeEvent, ChangeTopic, LibraryEventsService
from bento.domain.errors import DomainError, ValidationFailedError
from bento.interfaces.http.routes_content import error_response, pipeline

router = APIRouter()

RETRY_MILLISECONDS = 3000


@router.get(
    "/events",
    response_model=None,
    responses={200: {"content": {"text/event-stream": {}}, "description": "Server-Sent Events"}},
)
async def library_events(
    request: Request,
    topics: Annotated[str | None, Query(max_length=200)] = None,
    max_seconds: Annotated[int, Query(ge=1, le=MAX_STREAM_SECONDS)] = MAX_STREAM_SECONDS,
) -> StreamingResponse | JSONResponse:
    """`topics`: comma-separated subset of `library,jobs,imports,sync` (default: all). Events:
    `ready` (`data: {"topics": [...]}`) once, then `change` (`data: {"topics": ["library", ...]}`) whenever a
    watched topic changed; `: ping` comments while idle. The server ends the stream after `max_seconds`;
    reconnect (the `retry` hint is 3 s) and refetch what you show, since changes are not replayed."""
    try:
        watched = _topics(topics)
        service = _service(request)
    except DomainError as exc:
        return error_response(request, exc)
    return StreamingResponse(
        _encode(service.stream(watched, max_seconds=max_seconds, disconnected=request.is_disconnected)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def _encode(events: AsyncIterator[ChangeEvent]) -> AsyncIterator[bytes]:
    yield f"retry: {RETRY_MILLISECONDS}\n\n".encode()
    async for event in events:
        if event.kind == "heartbeat":
            yield b": ping\n\n"
            continue
        data = json.dumps({"topics": [topic.value for topic in event.topics]})
        yield f"event: {event.kind}\ndata: {data}\n\n".encode()


def _topics(raw: str | None) -> frozenset[ChangeTopic] | None:
    if raw is None or not raw.strip():
        return None
    try:
        return frozenset(ChangeTopic(item.strip()) for item in raw.split(",") if item.strip())
    except ValueError:
        raise ValidationFailedError(
            "Unknown event topic", {"allowed": [topic.value for topic in ChangeTopic]}
        ) from None


def _service(request: Request) -> LibraryEventsService:
    cached = getattr(request.app.state, "library_events", None)
    if cached is not None:
        return cached
    from bento.adapters.repositories.change_signatures import SQLiteChangeSignatures

    service = LibraryEventsService(signatures=SQLiteChangeSignatures(pipeline(request).session_factory))
    request.app.state.library_events = service
    return service
