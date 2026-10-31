"""Telegram sharing and import (`/telegram/*`, `/assets/{id}/share/telegram`)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bento.application.sharing import SharingService
from bento.application.telegram_import import TelegramImportService
from bento.domain.errors import DomainError, StorageUnavailableError
from bento.infrastructure.settings import Settings
from bento.interfaces.http.routes_account import domain_error_response
from bento.ports.telegram import TelegramChatsPort

router = APIRouter()


@dataclass(frozen=True, slots=True)
class TelegramRouteDependencies:
    sharing: SharingService
    imports: TelegramImportService


class TelegramChatResponse(BaseModel):
    id: int
    title: str
    kind: str


class TelegramChatsResponse(BaseModel):
    items: list[TelegramChatResponse]


class ShareRequest(BaseModel):
    chat_id: int
    caption: str | None = None


class ShareResponse(BaseModel):
    sent: bool


class TelegramMediaResponse(BaseModel):
    message_id: int
    kind: str
    filename: str
    size_bytes: int | None
    date: str


class TelegramMediaPageResponse(BaseModel):
    items: list[TelegramMediaResponse]
    next_cursor: str | None


class ImportRequest(BaseModel):
    chat_id: int
    message_ids: list[int] | None = Field(default=None, max_length=1000)
    all: bool = False


class ImportResponse(BaseModel):
    job_id: str
    queued: int


@router.get("/telegram/chats", response_model=TelegramChatsResponse)
async def list_chats(request: Request, query: str | None = None, limit: int = 30) -> Any:
    try:
        chats = await _dependencies(request).imports.list_chats(query=query, limit=limit)
    except DomainError as exc:
        return domain_error_response(request, exc)
    return TelegramChatsResponse(
        items=[TelegramChatResponse(id=chat.id, title=chat.title, kind=chat.kind.value) for chat in chats]
    )


@router.post("/assets/{asset_id}/share/telegram", response_model=ShareResponse)
async def share_asset(asset_id: str, request: Request, body: ShareRequest) -> ShareResponse | JSONResponse:
    try:
        await _dependencies(request).sharing.share(asset_id, body.chat_id, caption=body.caption)
    except DomainError as exc:
        return domain_error_response(request, exc)
    return ShareResponse(sent=True)


@router.get("/telegram/import/media", response_model=TelegramMediaPageResponse)
async def list_import_media(request: Request, chat_id: int, cursor: str | None = None, kind: str = "all") -> Any:
    try:
        page = await _dependencies(request).imports.list_media(chat_id, cursor=cursor, kind=kind)
    except DomainError as exc:
        return domain_error_response(request, exc)
    return TelegramMediaPageResponse(
        items=[
            TelegramMediaResponse(
                message_id=item.message_id,
                kind=item.kind.value,
                filename=item.filename,
                size_bytes=item.size_bytes,
                date=item.date.isoformat(),
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.post("/telegram/import", response_model=ImportResponse)
async def import_media(request: Request, body: ImportRequest) -> ImportResponse | JSONResponse:
    try:
        queued = await _dependencies(request).imports.enqueue(
            body.chat_id, message_ids=tuple(body.message_ids or ()), all_items=body.all
        )
    except DomainError as exc:
        return domain_error_response(request, exc)
    return ImportResponse(job_id=queued.job_id, queued=queued.queued)


def _dependencies(request: Request) -> TelegramRouteDependencies:
    cached = getattr(request.app.state, "telegram_route_dependencies", None)
    if cached is not None:
        return cached

    from bento.adapters.jobs import SQLiteJobQueue
    from bento.adapters.repositories import SQLiteAssetRepository
    from bento.infrastructure.db.clock import SystemClock
    from bento.infrastructure.mtproto import wiring
    from bento.infrastructure.services import get_asset_content

    settings: Settings = request.app.state.settings
    sessions = wiring.session_factory(settings)

    def chats() -> TelegramChatsPort | None:
        runtime = wiring.telegram_runtime(settings)
        if runtime is None:
            raise StorageUnavailableError("telegram")
        return runtime.chats

    dependencies = TelegramRouteDependencies(
        sharing=SharingService(
            assets=SQLiteAssetRepository(sessions), content=lambda: get_asset_content(settings), chats=chats
        ),
        imports=TelegramImportService(chats=chats, jobs=SQLiteJobQueue(sessions, SystemClock())),
    )
    request.app.state.telegram_route_dependencies = dependencies
    return dependencies
