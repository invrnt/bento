from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from bento.application.search import SearchAssetsQuery, SearchUseCase
from bento.domain.search import SearchFacet, SearchHit, SearchOrigin, SearchResultType
from bento.infrastructure.settings import Settings
from bento.interfaces.http.routes_smart_search import live_embedding_key

router = APIRouter()


class SearchSnippetResponse(BaseModel):
    text: str
    highlights: list[tuple[int, int]]
    """`[start, end)` offsets into `text`, in UTF-16 code units."""
    source: str
    """The match reason the excerpt comes from (`ocr_text`, `filename`, `folder_name`, `album`)."""


class SearchItemResponse(BaseModel):
    id: str
    type: str
    asset_id: str | None
    title: str
    subtitle: str | None
    thumbnail_url: str | None
    score: float
    reason: str
    """Spanish sentence for the web UI; clients that localize use `match_reasons`."""
    processing_state: str | None
    match_reasons: list[str] = []
    """Codes, strongest first: `ocr_text`, `filename`, `folder_name`, `album`, `semantic`, `metadata`,
    `document_type`, `exif_date`, `date`, `indexed_text`, `recent`."""
    snippet: SearchSnippetResponse | None = None
    folder_id: str | None = None
    """The containing folder (for folder hits, the parent)."""
    folder_name: str | None = None
    mime_type: str | None = None
    origin: str | None = None
    """Assets only: `device`, `peer` (synced from another device), `telegram_inbox`, `telegram_import`."""


class SearchFacetResponse(BaseModel):
    type: str
    count: int


class SearchResponse(BaseModel):
    items: list[SearchItemResponse]
    facets: list[SearchFacetResponse]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class SearchRouteDependencies:
    search: SearchUseCase


@router.get("/search", response_model=SearchResponse)
async def search(
    request: Request,
    q: Annotated[str, Query()] = "",
    type_: Annotated[SearchResultType | None, Query(alias="type")] = None,
    folder_id: Annotated[str | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    origin: Annotated[SearchOrigin | None, Query()] = None,
) -> SearchResponse:
    """`origin` keeps assets this device got a given way (`device`, `peer`, `telegram`, `telegram_inbox`,
    `telegram_import`); folders and albums are left out while it is set."""
    dependencies = await _search_dependencies(request)
    results = await dependencies.search.execute(
        SearchAssetsQuery(
            origin=origin,
            text=q,
            result_type=type_,
            folder_id=folder_id,
            date_from=_start_of_day(date_from),
            date_to=_end_of_day(date_to),
            limit=limit,
            cursor=cursor,
        )
    )
    return SearchResponse(
        items=[_item_response(item) for item in results.items],
        facets=[_facet_response(facet) for facet in results.facets],
        next_cursor=results.next_cursor,
    )


async def _search_dependencies(request: Request) -> SearchRouteDependencies:
    """Built once per embedding configuration. Smart search activation and removal change it while the API runs,
    so every search compares the live `(embeddings_provider, space_id)` (two small reads) and rebuilds on change."""
    state = request.app.state
    cached = getattr(state, "search_route_dependencies", None)
    if cached is not None and not hasattr(state, "search_route_key"):
        return cached  # injected by a test or an embedding host
    key = await live_embedding_key(request)
    if cached is not None and state.search_route_key == key:
        return cached
    dependencies = _build_search_dependencies(request, provider=key[0])
    state.search_route_dependencies = dependencies
    state.search_route_key = key
    return dependencies


def _build_search_dependencies(request: Request, *, provider: str) -> SearchRouteDependencies:
    from bento.adapters.runtime.embedding_setup import build_query_provider, default_model_ports
    from bento.adapters.search.composite import CompositeSearchIndex
    from bento.adapters.search.sqlite_fts import SQLiteFTSSearchIndex
    from bento.adapters.search.sqlite_vec import SQLiteVecSearchIndex
    from bento.infrastructure.db.clock import SystemClock
    from bento.infrastructure.db.engine import create_session_factory, sqlite_url

    settings = _settings(request)
    data_dir = Path(settings.data_dir)
    clock = SystemClock()
    session_factory = create_session_factory(sqlite_url(data_dir / "db" / "bento.sqlite3"))
    # Queries go through the worker's embedding server (`<data_dir>/run/embedder.json`); the API never spawns one.
    query_provider = build_query_provider(settings, catalog=default_model_ports(settings)[0], provider=provider)
    vector_index = SQLiteVecSearchIndex(
        session_factory,
        clock,
        dimensions=settings.embedding_dimensions,
    )
    dependencies = SearchRouteDependencies(
        search=SearchUseCase(
            index=CompositeSearchIndex(
                session_factory,
                clock,
                text_index=SQLiteFTSSearchIndex(session_factory, clock),
                vector_index=vector_index,
                query_embedding_provider=query_provider,
            )
        )
    )
    return dependencies


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _start_of_day(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=UTC)


def _end_of_day(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.max, tzinfo=UTC)


def _item_response(item: SearchHit) -> SearchItemResponse:
    return SearchItemResponse(
        id=item.id,
        type=item.type.value,
        asset_id=item.asset_id,
        title=item.title,
        subtitle=item.subtitle,
        thumbnail_url=item.thumbnail_url,
        score=item.score,
        reason=item.reason,
        processing_state=item.processing_state.value if item.processing_state is not None else None,
        match_reasons=[reason.value for reason in item.match_reasons],
        snippet=(
            SearchSnippetResponse(
                text=item.snippet.text, highlights=list(item.snippet.highlights), source=item.snippet.source.value
            )
            if item.snippet is not None
            else None
        ),
        folder_id=item.folder_id,
        folder_name=item.folder_name,
        mime_type=item.mime_type,
        origin=item.origin.value if item.origin is not None else None,
    )


def _facet_response(facet: SearchFacet) -> SearchFacetResponse:
    return SearchFacetResponse(type=facet.type.value, count=facet.count)
