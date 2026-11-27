from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from bento.application.search.parser import ParsedSearchQuery, QueryIntent, parse_search_query
from bento.application.search.scoring import ScoreParts, fuse_scores, recency_score, weights_for_intent
from bento.domain.assets import Asset, AssetKind, ProcessingState
from bento.domain.indexing import EmbeddingRecord, OCRBlock
from bento.domain.smart_search import (
    EmbeddingSpace,
    InvalidEmbeddingSpaceError,
    legacy_space_id,
    parse_space_id,
    truncate_and_renormalize,
)
from bento.domain.search import (
    MATCH_REASON_ORDER,
    MatchReason,
    SearchFacet,
    SearchHit,
    SearchOrigin,
    SearchQuery,
    SearchResults,
    SearchResultType,
    SearchSnippet,
    build_snippet,
)
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import (
    AlbumAssetModel,
    AlbumModel,
    AssetModel,
    AssetTextModel,
    FolderModel,
    OCRBlockModel,
    ThumbnailModel,
)
from bento.ports.repositories import ClockPort
from bento.ports.search import SearchIndexPort

from .sqlite_fts import DOCUMENT_TEXT_SOURCE, OCR_TEXT_SOURCE, SQLiteFTSSearchIndex, preferred_text_rows
from .sqlite_vec import SQLiteVecSearchIndex, Vector


class QueryEmbeddingProviderPort(Protocol):
    """The query side of `EmbeddingProviderPort`: the query prefix is applied by the provider."""

    async def is_enabled(self) -> bool: ...

    @property
    def space(self) -> EmbeddingSpace: ...

    async def embed_query(self, text: str) -> Vector: ...


class LegacyQueryEmbeddingProviderPort(Protocol):
    """Providers from before embedding spaces (one `embed_text` for queries and documents)."""

    async def is_enabled(self) -> bool: ...

    async def embed_text(self, asset_id: str, text: str) -> tuple[EmbeddingRecord, Vector]: ...


@dataclass(slots=True)
class _Candidate:
    id: str
    type: SearchResultType
    title: str
    updated_at: datetime
    asset_id: str | None = None
    subtitle: str | None = None
    thumbnail_url: str | None = None
    processing_state: ProcessingState | None = None
    text_score: float = 0.0
    vector_score: float = 0.0
    metadata_score: float = 0.0
    recency_score: float = 0.0
    final_score: float = 0.0
    reasons: set[str] = field(default_factory=set)
    folder_id: str | None = None
    mime_type: str | None = None
    origin: str | None = None
    has_taken_at: bool = False
    texts: dict[str, str] = field(default_factory=dict)
    """Matched text per internal reason (`ocr`, `filename`, `folder`, `album`), for the snippet."""


class CompositeSearchIndex(SearchIndexPort):
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        clock: ClockPort,
        *,
        text_index: SQLiteFTSSearchIndex,
        vector_index: SQLiteVecSearchIndex | None = None,
        query_embedding_provider: QueryEmbeddingProviderPort | LegacyQueryEmbeddingProviderPort | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._text_index = text_index
        self._vector_index = vector_index
        self._query_embedding_provider = query_embedding_provider

    async def index_asset(self, asset: Asset) -> None:
        await self._text_index.index_asset(asset)

    async def index_ocr(self, block: OCRBlock) -> None:
        await self._text_index.index_ocr(block)

    async def index_embedding(self, record: EmbeddingRecord) -> None:
        if self._vector_index is not None:
            await self._vector_index.index_embedding(record)
        else:
            await self._text_index.index_embedding(record)

    async def remove_asset(self, asset_id: str) -> None:
        await self._text_index.remove_asset(asset_id)
        if self._vector_index is not None:
            await self._vector_index.remove_asset(asset_id)

    async def search(self, query: SearchQuery) -> SearchResults:
        parsed = parse_search_query(query.text)
        effective = _effective_query(query, parsed)
        limit = max(min(effective.limit, 100), 1)
        offset = _decode_cursor(effective.cursor)
        candidate_limit = min(max(limit + offset + 25, limit * 3), 200)
        candidates: dict[tuple[SearchResultType, str], _Candidate] = {}

        if effective.result_type != SearchResultType.OCR_BLOCK:
            await self._add_text_hits(candidates, effective, parsed, candidate_limit)
            self._add_metadata_hits(candidates, effective, parsed, candidate_limit)
            self._add_recent_asset_hits(candidates, effective, parsed, candidate_limit)
        self._add_ocr_block_hits(candidates, effective, parsed, candidate_limit)
        if effective.origin is None:  # folders and albums have no origin
            self._add_collection_hits(candidates, effective, parsed, candidate_limit)
        self._add_container_hits(candidates, effective, parsed, candidate_limit)

        vector_available = await self._add_vector_hits(candidates, effective, candidate_limit)
        self._finalize_scores(candidates.values(), parsed, vector_available)

        sorted_candidates = sorted(
            candidates.values(),
            key=lambda candidate: (-candidate.final_score, -candidate.updated_at.timestamp(), candidate.id),
        )
        page = sorted_candidates[offset : offset + limit]
        facets = tuple(
            SearchFacet(type=result_type, count=count)
            for result_type, count in Counter(candidate.type for candidate in sorted_candidates).items()
        )
        next_cursor = str(offset + limit) if len(sorted_candidates) > offset + limit else None
        folder_names = self._folder_names({candidate.folder_id for candidate in page if candidate.folder_id is not None})
        return SearchResults(
            items=tuple(_hit(candidate, parsed.tokens, folder_names) for candidate in page),
            facets=facets,
            next_cursor=next_cursor,
        )

    def _folder_names(self, folder_ids: set[str]) -> dict[str, str]:
        if not folder_ids:
            return {}
        with session_scope(self._session_factory) as session:
            return dict(session.execute(select(FolderModel.id, FolderModel.name).where(FolderModel.id.in_(folder_ids))).all())

    def _add_container_hits(
        self,
        candidates: dict[tuple[SearchResultType, str], _Candidate],
        query: SearchQuery,
        parsed: ParsedSearchQuery,
        limit: int,
    ) -> None:
        """Files inside a folder, or photos in an album, whose name matches: `folder_name` / `album` reasons."""
        if not parsed.tokens or query.result_type in {SearchResultType.FOLDER, SearchResultType.ALBUM, SearchResultType.OCR_BLOCK}:
            return
        with session_scope(self._session_factory) as session:
            folders = [
                (folder.id, folder.name, score)
                for folder in session.scalars(select(FolderModel).where(FolderModel.deleted_at.is_(None)))
                if (score := _name_match_score(folder.name, parsed.tokens)) > 0
            ]
            albums = [
                (album.id, album.title, score)
                for album in session.scalars(select(AlbumModel).where(AlbumModel.deleted_at.is_(None)))
                if (score := _name_match_score(album.title, parsed.tokens)) > 0
            ]
            for folder_id, name, score in folders[:limit]:
                for model in session.scalars(_asset_select(query).where(AssetModel.folder_id == folder_id).limit(limit)):
                    self._add_member(session, candidates, model, query, score, "folder", name)
            for album_id, title, score in albums[:limit]:
                statement = (
                    _asset_select(query)
                    .join(AlbumAssetModel, AlbumAssetModel.asset_id == AssetModel.id)
                    .where(AlbumAssetModel.album_id == album_id)
                    .limit(limit)
                )
                for model in session.scalars(statement):
                    self._add_member(session, candidates, model, query, score, "album", title)

    def _add_member(
        self,
        session: Session,
        candidates: dict[tuple[SearchResultType, str], _Candidate],
        model: AssetModel,
        query: SearchQuery,
        score: float,
        reason: str,
        text: str,
    ) -> None:
        candidate = _asset_candidate(session, model, _asset_result_type(model, query.result_type))
        candidate.metadata_score = max(candidate.metadata_score, score * 0.6)
        candidate.reasons.add(reason)
        candidate.texts[reason] = text
        _merge_candidate(candidates, candidate)

    async def _add_text_hits(
        self,
        candidates: dict[tuple[SearchResultType, str], _Candidate],
        query: SearchQuery,
        parsed: ParsedSearchQuery,
        limit: int,
    ) -> None:
        if not query.text.strip() or query.result_type in {SearchResultType.FOLDER, SearchResultType.ALBUM}:
            return
        results = await self._text_index.search(
            SearchQuery(
                text=query.text,
                result_type=query.result_type,
                folder_id=query.folder_id,
                date_from=query.date_from,
                date_to=query.date_to,
                limit=limit,
                cursor=None,
            )
        )
        with session_scope(self._session_factory) as session:
            for hit in results.items:
                if hit.asset_id is None:
                    continue
                model = session.get(AssetModel, hit.asset_id)
                if model is None or model.deleted_at is not None or not _origin_matches(model.origin, query.origin):
                    continue
                candidate = _asset_candidate(session, model, _asset_result_type(model, query.result_type))
                candidate.text_score = max(candidate.text_score, hit.score)
                candidate.reasons.update(_matched_sources(session, model, parsed.tokens, candidate.texts))
                _merge_candidate(candidates, candidate)

    def _add_metadata_hits(
        self,
        candidates: dict[tuple[SearchResultType, str], _Candidate],
        query: SearchQuery,
        parsed: ParsedSearchQuery,
        limit: int,
    ) -> None:
        if query.result_type in {SearchResultType.FOLDER, SearchResultType.ALBUM, SearchResultType.OCR_BLOCK}:
            return
        if not parsed.tokens:
            return
        with session_scope(self._session_factory) as session:
            statement = _asset_select(query).limit(limit)
            for model in session.scalars(statement):
                score, reasons = _metadata_match(model, parsed)
                if score <= 0:
                    continue
                candidate = _asset_candidate(session, model, _asset_result_type(model, query.result_type))
                candidate.metadata_score = max(candidate.metadata_score, score)
                if "filename" in reasons:
                    candidate.text_score = max(candidate.text_score, score)
                candidate.reasons.update(reasons)
                _merge_candidate(candidates, candidate)

    def _add_recent_asset_hits(
        self,
        candidates: dict[tuple[SearchResultType, str], _Candidate],
        query: SearchQuery,
        parsed: ParsedSearchQuery,
        limit: int,
    ) -> None:
        if query.result_type in {SearchResultType.FOLDER, SearchResultType.ALBUM, SearchResultType.OCR_BLOCK}:
            return
        if parsed.tokens and parsed.intent != QueryIntent.DATE:
            return
        with session_scope(self._session_factory) as session:
            for model in session.scalars(_asset_select(query).limit(limit)):
                candidate = _asset_candidate(session, model, _asset_result_type(model, query.result_type))
                candidate.metadata_score = max(candidate.metadata_score, 0.15 if parsed.tokens else 0.05)
                candidate.reasons.add("date" if parsed.intent == QueryIntent.DATE else "recent")
                _merge_candidate(candidates, candidate)

    def _add_ocr_block_hits(
        self,
        candidates: dict[tuple[SearchResultType, str], _Candidate],
        query: SearchQuery,
        parsed: ParsedSearchQuery,
        limit: int,
    ) -> None:
        if query.result_type not in {None, SearchResultType.OCR_BLOCK} or not parsed.tokens:
            return
        with session_scope(self._session_factory) as session:
            filters = [OCRBlockModel.text.ilike(f"%{token}%") for token in parsed.tokens]
            statement = (
                select(OCRBlockModel, AssetModel)
                .join(AssetModel, AssetModel.id == OCRBlockModel.asset_id)
                .where(or_(*filters), *_asset_conditions(query))
                .order_by(OCRBlockModel.created_at.desc(), OCRBlockModel.id.desc())
                .limit(limit)
            )
            for block, asset in session.execute(statement).all():
                candidate = _Candidate(
                    id=block.id,
                    type=SearchResultType.OCR_BLOCK,
                    asset_id=asset.id,
                    title=asset.filename,
                    subtitle=_page_subtitle(block.page_number),
                    thumbnail_url=_thumbnail_url(session, asset.id),
                    processing_state=ProcessingState(asset.processing_state),
                    updated_at=asset.updated_at,
                    text_score=1.0,
                    metadata_score=0.2,
                    reasons={"ocr"},
                    folder_id=asset.folder_id,
                    mime_type=asset.mime_type,
                    origin=asset.origin,
                    has_taken_at=asset.taken_at is not None,
                    texts={"ocr": block.text},
                )
                _merge_candidate(candidates, candidate)

    def _add_collection_hits(
        self,
        candidates: dict[tuple[SearchResultType, str], _Candidate],
        query: SearchQuery,
        parsed: ParsedSearchQuery,
        limit: int,
    ) -> None:
        if query.result_type not in {None, SearchResultType.FOLDER, SearchResultType.ALBUM}:
            return
        if not parsed.tokens and query.result_type is None:
            return
        with session_scope(self._session_factory) as session:
            if query.result_type in {None, SearchResultType.FOLDER}:
                folder_statement = (
                    select(FolderModel)
                    .where(FolderModel.deleted_at.is_(None))
                    .order_by(FolderModel.updated_at.desc(), FolderModel.id.desc())
                    .limit(limit)
                )
                if query.folder_id is not None:
                    folder_statement = folder_statement.where(FolderModel.parent_id == query.folder_id)
                for folder in session.scalars(folder_statement):
                    score = _name_match_score(folder.name, parsed.tokens)
                    if score <= 0 and parsed.tokens:
                        continue
                    _merge_candidate(
                        candidates,
                        _Candidate(
                            id=folder.id,
                            type=SearchResultType.FOLDER,
                            title=folder.name,
                            subtitle="Carpeta",
                            updated_at=folder.updated_at,
                            text_score=score,
                            metadata_score=max(score, 0.1),
                            reasons={"folder"},
                            folder_id=folder.parent_id,
                            texts={"folder": folder.name},
                        ),
                    )
            if query.result_type in {None, SearchResultType.ALBUM} and query.folder_id is None:
                album_statement = (
                    select(AlbumModel)
                    .where(AlbumModel.deleted_at.is_(None))
                    .order_by(AlbumModel.updated_at.desc(), AlbumModel.id.desc())
                    .limit(limit)
                )
                for album in session.scalars(album_statement):
                    score = _name_match_score(album.title, parsed.tokens)
                    if score <= 0 and parsed.tokens:
                        continue
                    _merge_candidate(
                        candidates,
                        _Candidate(
                            id=album.id,
                            type=SearchResultType.ALBUM,
                            title=album.title,
                            subtitle="Album",
                            updated_at=album.updated_at,
                            text_score=score,
                            metadata_score=max(score, 0.1),
                            reasons={"album"},
                            texts={"album": album.title},
                        ),
                    )

    async def _add_vector_hits(
        self,
        candidates: dict[tuple[SearchResultType, str], _Candidate],
        query: SearchQuery,
        limit: int,
    ) -> bool:
        if (
            self._vector_index is None
            or self._query_embedding_provider is None
            or not query.text.strip()
            or query.result_type in {SearchResultType.FOLDER, SearchResultType.ALBUM, SearchResultType.OCR_BLOCK}
        ):
            return False
        try:
            target = await self._query_vector(query.text)
            if target is None:
                return False
            space_id, vector = target
            vector_hits = await self._vector_index.search_vectors(vector, limit=limit, space_id=space_id)
        except Exception:
            # The embedding runtime is missing, unhealthy or stopped: search keeps working on text alone.
            return False

        by_asset = {hit.asset_id: hit for hit in vector_hits}
        if not by_asset:
            return True
        with session_scope(self._session_factory) as session:
            statement = _asset_select(query).where(AssetModel.id.in_(by_asset.keys()))
            for model in session.scalars(statement):
                vector_hit = by_asset[model.id]
                candidate = _asset_candidate(session, model, _asset_result_type(model, query.result_type))
                candidate.vector_score = max(candidate.vector_score, vector_hit.score)
                candidate.reasons.add("vector")
                _merge_candidate(candidates, candidate)
        return True

    async def _query_vector(self, text: str) -> tuple[str, Vector] | None:
        """The query vector in the space search must use: the active space, else the provider's own space.

        Search keeps the active space while a new one is being built (blue/green). A provider serving a newer
        space of the same model and revision can still answer it by Matryoshka truncation; any other mismatch
        means vector search is unavailable for now.
        """
        provider = self._query_embedding_provider
        if provider is None or self._vector_index is None or not await provider.is_enabled():
            return None
        embed_query = getattr(provider, "embed_query", None)
        if embed_query is not None:
            provider_space = str(getattr(provider, "space").id)
            vector: Vector = tuple(await embed_query(text))
        else:
            record, vector = await getattr(provider, "embed_text")("query", text)
            provider_space = legacy_space_id(record.provider, len(vector))
        active = await self._vector_index.active_space_id()
        target = active or provider_space
        projected = _project_query_vector(vector, provider_space, target)
        if projected is None:
            return None
        return target, projected

    def _finalize_scores(
        self,
        candidates: object,
        parsed: ParsedSearchQuery,
        vector_available: bool,
    ) -> None:
        candidate_list = list(candidates)
        _normalize_text_scores(candidate_list)
        weights = weights_for_intent(parsed.intent, vector_available=vector_available)
        now = self._clock.now()
        for candidate in candidate_list:
            candidate.recency_score = recency_score(now, candidate.updated_at)
            candidate.final_score = fuse_scores(
                ScoreParts(
                    text=candidate.text_score,
                    vector=candidate.vector_score,
                    metadata=candidate.metadata_score,
                    recency=candidate.recency_score,
                ),
                weights,
            )
            if candidate.final_score == 0.0 and candidate.reasons:
                candidate.final_score = 0.01


def _project_query_vector(vector: Vector, provider_space: str, target_space: str) -> Vector | None:
    if provider_space == target_space:
        return vector
    try:
        model_id, revision, dims = parse_space_id(provider_space)
        target_model, target_revision, target_dims = parse_space_id(target_space)
    except InvalidEmbeddingSpaceError:
        return None
    if not revision or (model_id, revision) != (target_model, target_revision) or target_dims > dims:
        return None
    return truncate_and_renormalize(vector, target_dims)


def _effective_query(query: SearchQuery, parsed: ParsedSearchQuery) -> SearchQuery:
    return SearchQuery(
        text=query.text,
        result_type=query.result_type,
        folder_id=query.folder_id,
        date_from=query.date_from or parsed.date_from,
        date_to=query.date_to or parsed.date_to,
        limit=query.limit,
        cursor=query.cursor,
        origin=query.origin,
    )


def _asset_select(query: SearchQuery) -> Select[tuple[AssetModel]]:
    return (
        select(AssetModel)
        .where(*_asset_conditions(query))
        .order_by(
            func.coalesce(AssetModel.taken_at, AssetModel.updated_at, AssetModel.created_at).desc(),
            AssetModel.id.desc(),
        )
    )


def _asset_conditions(query: SearchQuery) -> list[object]:
    conditions: list[object] = [AssetModel.deleted_at.is_(None)]
    kinds = _kind_filter(query.result_type)
    if kinds:
        conditions.append(AssetModel.kind.in_([kind.value for kind in kinds]))
    if query.folder_id is not None:
        conditions.append(AssetModel.folder_id == query.folder_id)
    asset_date = func.coalesce(AssetModel.taken_at, AssetModel.created_at)
    if query.date_from is not None:
        conditions.append(asset_date >= query.date_from)
    if query.date_to is not None:
        conditions.append(asset_date <= query.date_to)
    if query.origin is not None:
        conditions.append(_origin_condition(query.origin))
    return conditions


_TELEGRAM_ORIGINS = ("telegram_inbox", "telegram_import")


def _origin_condition(origin: SearchOrigin) -> object:
    if origin == SearchOrigin.PEER:
        return AssetModel.origin.is_(None)
    if origin == SearchOrigin.TELEGRAM:
        return AssetModel.origin.in_(_TELEGRAM_ORIGINS)
    return AssetModel.origin == origin.value


def _origin_matches(value: str | None, origin: SearchOrigin | None) -> bool:
    if origin is None:
        return True
    if origin == SearchOrigin.PEER:
        return value is None
    if origin == SearchOrigin.TELEGRAM:
        return value in _TELEGRAM_ORIGINS
    return value == origin.value


def _kind_filter(result_type: SearchResultType | None) -> tuple[AssetKind, ...]:
    if result_type == SearchResultType.PHOTO:
        return (AssetKind.IMAGE,)
    if result_type == SearchResultType.VIDEO:
        return (AssetKind.VIDEO,)
    if result_type == SearchResultType.DOCUMENT:
        return (AssetKind.DOCUMENT, AssetKind.PDF)
    if result_type == SearchResultType.PDF_PAGE:
        return (AssetKind.PDF,)
    return ()


def _asset_candidate(session: Session, model: AssetModel, result_type: SearchResultType) -> _Candidate:
    return _Candidate(
        id=model.id,
        type=result_type,
        asset_id=model.id,
        title=model.filename,
        subtitle=_asset_subtitle(model),
        thumbnail_url=_thumbnail_url(session, model.id),
        processing_state=ProcessingState(model.processing_state),
        updated_at=model.updated_at,
        folder_id=model.folder_id,
        mime_type=model.mime_type,
        origin=model.origin,
        has_taken_at=model.taken_at is not None,
        texts={"filename": model.filename},
    )


def _asset_result_type(model: AssetModel, requested_type: SearchResultType | None) -> SearchResultType:
    if requested_type in {SearchResultType.PHOTO, SearchResultType.VIDEO, SearchResultType.PDF_PAGE, SearchResultType.ASSET}:
        return requested_type
    if requested_type == SearchResultType.DOCUMENT and model.kind != AssetKind.PDF.value:
        return SearchResultType.DOCUMENT
    if model.kind == AssetKind.IMAGE.value:
        return SearchResultType.PHOTO
    if model.kind == AssetKind.VIDEO.value:
        return SearchResultType.VIDEO
    if model.kind == AssetKind.PDF.value:
        return SearchResultType.PDF_PAGE
    if model.kind == AssetKind.DOCUMENT.value:
        return SearchResultType.DOCUMENT
    return SearchResultType.ASSET


def _metadata_match(model: AssetModel, parsed: ParsedSearchQuery) -> tuple[float, set[str]]:
    if not parsed.tokens:
        return 0.0, set()
    filename = model.filename.lower()
    metadata = _metadata_text(model).lower()
    filename_hits = sum(1 for token in parsed.tokens if token in filename)
    metadata_hits = sum(1 for token in parsed.tokens if token in metadata)
    score = max(filename_hits, metadata_hits) / len(parsed.tokens)
    reasons: set[str] = set()
    if filename_hits:
        reasons.add("filename")
    if metadata_hits:
        reasons.add("metadata")
    if parsed.intent == QueryIntent.DOCUMENT and model.kind in {AssetKind.DOCUMENT.value, AssetKind.PDF.value} and score > 0:
        score = min(score + 0.25, 1.0)
        reasons.add("document")
    return score, reasons


def _matched_sources(
    session: Session, model: AssetModel, tokens: tuple[str, ...], texts: dict[str, str] | None = None
) -> set[str]:
    reasons: set[str] = set()
    if not tokens:
        return reasons
    if any(token in model.filename.lower() for token in tokens):
        reasons.add("filename")
    rows = session.execute(
        select(AssetTextModel.source, AssetTextModel.text)
        .where(AssetTextModel.asset_id == model.id)
        .order_by(AssetTextModel.source.asc(), AssetTextModel.id.asc())
    ).all()
    for source, text in preferred_text_rows([(source, text) for source, text in rows]):
        lowered = text.lower()
        if any(token in lowered for token in tokens):
            reason = _TEXT_SOURCE_REASONS.get(source, "metadata")
            reasons.add(reason)
            if reason in {"ocr", "text"} and texts is not None:
                texts.setdefault(reason, text)
    if not reasons:
        reasons.add("text")
    return reasons


def _metadata_text(model: AssetModel) -> str:
    parts = [model.filename, model.original_filename, model.mime_type]
    if model.exif_json:
        parts.append(json.dumps(model.exif_json, ensure_ascii=False, sort_keys=True))
    return " ".join(part for part in parts if part)


def _name_match_score(name: str, tokens: tuple[str, ...]) -> float:
    if not tokens:
        return 0.1
    lowered = name.lower()
    hits = sum(1 for token in tokens if token in lowered)
    return hits / len(tokens)


def _asset_subtitle(model: AssetModel) -> str:
    item_date = model.taken_at or model.created_at
    return item_date.strftime("%b %Y")


def _page_subtitle(page_number: int | None) -> str:
    if page_number is None:
        return "OCR"
    return f"Pagina {page_number}"


def _thumbnail_url(session: Session, asset_id: str) -> str | None:
    exists = session.scalar(select(ThumbnailModel.id).where(ThumbnailModel.asset_id == asset_id).limit(1))
    if exists is None:
        return None
    return f"/api/assets/{asset_id}/thumbnail"


def _merge_candidate(candidates: dict[tuple[SearchResultType, str], _Candidate], incoming: _Candidate) -> None:
    key = (incoming.type, incoming.id)
    existing = candidates.get(key)
    if existing is None:
        candidates[key] = incoming
        return
    existing.text_score = max(existing.text_score, incoming.text_score)
    existing.vector_score = max(existing.vector_score, incoming.vector_score)
    existing.metadata_score = max(existing.metadata_score, incoming.metadata_score)
    existing.reasons.update(incoming.reasons)
    for reason, text in incoming.texts.items():
        existing.texts.setdefault(reason, text)


def _normalize_text_scores(candidates: list[_Candidate]) -> None:
    highest = max((candidate.text_score for candidate in candidates), default=0.0)
    if highest <= 0:
        return
    for candidate in candidates:
        candidate.text_score = min(candidate.text_score / highest, 1.0)


_REASON_CODES: dict[str, MatchReason] = {
    "ocr": MatchReason.OCR_TEXT,
    "vector": MatchReason.SEMANTIC,
    "filename": MatchReason.FILENAME,
    "metadata": MatchReason.METADATA,
    "document": MatchReason.DOCUMENT_TYPE,
    "folder": MatchReason.FOLDER_NAME,
    "album": MatchReason.ALBUM,
    "recent": MatchReason.RECENT,
    "text": MatchReason.INDEXED_TEXT,
}
_SNIPPET_SOURCES = ("ocr", "text", "filename", "folder", "album")
# `asset_text.source` -> candidate reason: text read from the file itself is "indexed text", not OCR.
_TEXT_SOURCE_REASONS = {OCR_TEXT_SOURCE: "ocr", DOCUMENT_TEXT_SOURCE: "text"}


def _match_reasons(candidate: _Candidate) -> tuple[MatchReason, ...]:
    codes = {_REASON_CODES[reason] for reason in candidate.reasons if reason in _REASON_CODES}
    if "date" in candidate.reasons:
        codes.add(MatchReason.EXIF_DATE if candidate.has_taken_at else MatchReason.DATE)
    return tuple(code for code in MATCH_REASON_ORDER if code in codes)


def _snippet(candidate: _Candidate, tokens: tuple[str, ...]) -> SearchSnippet | None:
    for reason in _SNIPPET_SOURCES:
        text = candidate.texts.get(reason)
        if reason in candidate.reasons and text:
            snippet = build_snippet(text, tokens, _REASON_CODES[reason])
            if snippet is not None:
                return snippet
    return None


def _origin(value: str | None, candidate: _Candidate) -> SearchOrigin | None:
    if candidate.asset_id is None:
        return None
    if value is None:
        return SearchOrigin.PEER
    try:
        return SearchOrigin(value)
    except ValueError:
        return None


def _hit(candidate: _Candidate, tokens: tuple[str, ...] = (), folder_names: dict[str, str] | None = None) -> SearchHit:
    return SearchHit(
        id=candidate.id,
        type=candidate.type,
        asset_id=candidate.asset_id,
        title=candidate.title,
        subtitle=candidate.subtitle,
        thumbnail_url=candidate.thumbnail_url,
        score=round(candidate.final_score, 6),
        reason=_reason(candidate.reasons),
        processing_state=candidate.processing_state,
        match_reasons=_match_reasons(candidate),
        snippet=_snippet(candidate, tokens),
        folder_id=candidate.folder_id,
        folder_name=(folder_names or {}).get(candidate.folder_id) if candidate.folder_id is not None else None,
        mime_type=candidate.mime_type,
        origin=_origin(candidate.origin, candidate),
    )


def _reason(reasons: set[str]) -> str:
    labels = [
        ("ocr", "OCR"),
        ("vector", "busqueda semantica"),
        ("filename", "nombre de archivo"),
        ("metadata", "metadata"),
        ("document", "tipo de documento"),
        ("date", "fecha"),
        ("folder", "nombre de carpeta"),
        ("album", "album"),
        ("recent", "actividad reciente"),
        ("text", "texto indexado"),
    ]
    selected = [label for key, label in labels if key in reasons]
    if not selected:
        return "Coincidio con la busqueda"
    return f"Coincidio por {' y '.join(selected[:3])}"


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(cursor)
    except ValueError:
        return 0
    return max(value, 0)
