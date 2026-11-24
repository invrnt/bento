from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bento.domain.search import SearchOrigin, SearchQuery, SearchResults, SearchResultType
from bento.ports.search import SearchIndexPort

from .parser import ParsedSearchQuery, QueryIntent, parse_search_query
from .scoring import ScoreParts, ScoreWeights, fuse_scores, recency_score, weights_for_intent


@dataclass(frozen=True, slots=True)
class SearchAssetsQuery:
    text: str
    result_type: SearchResultType | None = None
    folder_id: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    limit: int = 50
    cursor: str | None = None
    origin: SearchOrigin | None = None


class SearchUseCase:
    def __init__(self, *, index: SearchIndexPort) -> None:
        self._index = index

    async def execute(self, query: SearchAssetsQuery) -> SearchResults:
        return await self._index.search(
            SearchQuery(
                text=query.text,
                result_type=query.result_type,
                folder_id=query.folder_id,
                date_from=query.date_from,
                date_to=query.date_to,
                limit=max(min(query.limit, 100), 1),
                cursor=query.cursor,
                origin=query.origin,
            )
        )


__all__ = [
    "ParsedSearchQuery",
    "QueryIntent",
    "ScoreParts",
    "ScoreWeights",
    "SearchAssetsQuery",
    "SearchUseCase",
    "fuse_scores",
    "parse_search_query",
    "recency_score",
    "weights_for_intent",
]
