from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.ids import new_id
from bento.domain.assets import Asset, AssetKind, ProcessingState
from bento.domain.indexing import EmbeddingRecord, ExtractedPage, OCRBlock
from bento.domain.search import SearchFacet, SearchHit, SearchQuery, SearchResultType, SearchResults
from bento.domain.search_terms import lexical_query
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AssetEmbeddingModel, AssetModel, AssetTextModel, OCRBlockModel
from bento.ports.repositories import ClockPort


DOCUMENT_TEXT_SOURCE = "document"
"""`asset_text.source` of text read from the file itself (`text_extract`); preferred over `ocr` when both exist."""
OCR_TEXT_SOURCE = "ocr"


class SQLiteFTSSearchIndex:
    def __init__(self, session_factory: sessionmaker[Session], clock: ClockPort) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def index_asset(self, asset: Asset) -> None:
        now = self._clock.now()
        with session_scope(self._session_factory) as session:
            session.execute(
                delete(AssetTextModel).where(
                    AssetTextModel.asset_id == asset.id,
                    AssetTextModel.source == "metadata",
                )
            )
            metadata_text = _asset_metadata_text(asset)
            if metadata_text:
                session.add(
                    AssetTextModel(
                        id=new_id("text"),
                        asset_id=asset.id,
                        source="metadata",
                        text=metadata_text,
                        language=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
            session.flush()
            _rebuild_asset_fts(session, asset.id)

    async def index_ocr(self, block: OCRBlock) -> None:
        now = self._clock.now()
        with session_scope(self._session_factory) as session:
            session.merge(
                OCRBlockModel(
                    id=block.id,
                    asset_id=block.asset_id,
                    page_number=block.page_number,
                    text=block.text,
                    confidence=block.confidence,
                    created_at=now,
                )
            )
            session.execute(
                delete(AssetTextModel).where(
                    AssetTextModel.id == f"text_{block.id}",
                    AssetTextModel.source == "ocr",
                )
            )
            session.add(
                AssetTextModel(
                    id=f"text_{block.id}",
                    asset_id=block.asset_id,
                    source="ocr",
                    text=block.text,
                    language=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            _rebuild_asset_fts(session, block.asset_id)

    async def replace_document_text(self, asset_id: str, pages: Sequence[ExtractedPage]) -> None:
        now = self._clock.now()
        with session_scope(self._session_factory) as session:
            session.execute(
                delete(AssetTextModel).where(
                    AssetTextModel.asset_id == asset_id,
                    AssetTextModel.source == DOCUMENT_TEXT_SOURCE,
                )
            )
            for position, page in enumerate(pages):
                if not page.text.strip():
                    continue
                session.add(
                    AssetTextModel(
                        id=document_text_id(asset_id, page.page_number or position),
                        asset_id=asset_id,
                        source=DOCUMENT_TEXT_SOURCE,
                        text=page.text,
                        language=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
            session.flush()
            _rebuild_asset_fts(session, asset_id)

    async def has_document_text(self, asset_id: str) -> bool:
        with session_scope(self._session_factory) as session:
            found = session.scalar(
                select(AssetTextModel.id)
                .where(AssetTextModel.asset_id == asset_id, AssetTextModel.source == DOCUMENT_TEXT_SOURCE)
                .limit(1)
            )
        return found is not None

    async def index_embedding(self, record: EmbeddingRecord) -> None:
        with session_scope(self._session_factory) as session:
            session.merge(
                AssetEmbeddingModel(
                    id=record.id,
                    asset_id=record.asset_id,
                    provider=record.provider,
                    vector_ref=record.vector_ref,
                    dimensions=record.dimensions,
                    created_at=self._clock.now(),
                )
            )

    async def remove_asset(self, asset_id: str) -> None:
        with session_scope(self._session_factory) as session:
            session.execute(text("DELETE FROM asset_fts WHERE asset_id = :asset_id"), {"asset_id": asset_id})
            session.execute(delete(AssetTextModel).where(AssetTextModel.asset_id == asset_id))
            session.execute(delete(OCRBlockModel).where(OCRBlockModel.asset_id == asset_id))
            session.execute(delete(AssetEmbeddingModel).where(AssetEmbeddingModel.asset_id == asset_id))

    async def search(self, query: SearchQuery) -> SearchResults:
        fts_query = _fts_query(query.text)
        if fts_query is None or query.result_type in {SearchResultType.FOLDER, SearchResultType.ALBUM}:
            return SearchResults(items=(), facets=(), next_cursor=None)

        offset = _decode_cursor(query.cursor)
        limit = max(min(query.limit, 100), 1)
        params: dict[str, object] = {
            "query": fts_query,
            "limit": limit + 1,
            "offset": offset,
        }
        filters = ["asset_fts MATCH :query", "a.deleted_at IS NULL"]
        kind_filter = _kind_filter(query.result_type)
        if kind_filter is not None:
            filters.append("a.kind = :kind")
            params["kind"] = kind_filter.value
        if query.folder_id is not None:
            filters.append("a.folder_id = :folder_id")
            params["folder_id"] = query.folder_id
        if query.date_from is not None:
            filters.append("COALESCE(a.taken_at, a.created_at) >= :date_from")
            params["date_from"] = query.date_from
        if query.date_to is not None:
            filters.append("COALESCE(a.taken_at, a.created_at) <= :date_to")
            params["date_to"] = query.date_to

        statement = text(
            f"""
            SELECT
                a.id AS asset_id,
                a.kind AS kind,
                a.filename AS filename,
                a.mime_type AS mime_type,
                a.processing_state AS processing_state,
                bm25(asset_fts) AS rank,
                snippet(asset_fts, 2, '', '', '...', 16) AS snippet_text
            FROM asset_fts
            JOIN assets AS a ON a.id = asset_fts.asset_id
            WHERE {" AND ".join(filters)}
            ORDER BY rank ASC, a.updated_at DESC, a.id ASC
            LIMIT :limit OFFSET :offset
            """
        )

        with session_scope(self._session_factory) as session:
            rows = list(session.execute(statement, params).mappings())

        visible = rows[:limit]
        hits = tuple(_hit_from_row(row, query.result_type) for row in visible)
        facets = tuple(
            SearchFacet(type=result_type, count=count)
            for result_type, count in Counter(hit.type for hit in hits).items()
        )
        next_cursor = str(offset + limit) if len(rows) > limit else None
        return SearchResults(items=hits, facets=facets, next_cursor=next_cursor)


def _rebuild_asset_fts(session: Session, asset_id: str) -> None:
    session.execute(text("DELETE FROM asset_fts WHERE asset_id = :asset_id"), {"asset_id": asset_id})
    asset = session.get(AssetModel, asset_id)
    if asset is None or asset.deleted_at is not None:
        return
    rows = session.execute(
        select(AssetTextModel.source, AssetTextModel.text)
        .where(AssetTextModel.asset_id == asset_id)
        .order_by(AssetTextModel.source.asc(), AssetTextModel.id.asc())
    ).all()
    texts = [text for source, text in preferred_text_rows(rows)]
    metadata = _model_metadata_text(asset)
    session.execute(
        text(
            """
            INSERT INTO asset_fts(asset_id, title, text, metadata)
            VALUES (:asset_id, :title, :text, :metadata)
            """
        ),
        {
            "asset_id": asset.id,
            "title": asset.filename,
            "text": "\n".join(texts),
            "metadata": metadata,
        },
    )


def document_text_id(asset_id: str, page: int) -> str:
    """Stable, page-ordered ids, so reading rows by id keeps the document's page order."""
    digest = hashlib.sha1(asset_id.encode("utf-8")).hexdigest()[:24]
    return f"doc_{digest}_{max(page, 0):05d}"


def preferred_text_rows(rows: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    """An asset's `(source, text)` rows without its OCR text when it has document text (the text layer wins)."""
    if any(source == DOCUMENT_TEXT_SOURCE for source, _ in rows):
        return [(source, text) for source, text in rows if source != OCR_TEXT_SOURCE]
    return list(rows)


def _asset_metadata_text(asset: Asset) -> str:
    parts = [asset.metadata.original_filename, asset.metadata.mime_type]
    if asset.metadata.exif:
        parts.append(json.dumps(dict(asset.metadata.exif), ensure_ascii=False, sort_keys=True))
    return " ".join(part for part in parts if part)


def _model_metadata_text(asset: AssetModel) -> str:
    parts = [asset.original_filename, asset.mime_type]
    if asset.exif_json:
        parts.append(json.dumps(asset.exif_json, ensure_ascii=False, sort_keys=True))
    return " ".join(part for part in parts if part)


def _fts_query(raw: str) -> str | None:
    """FTS5 query: every content word (stop words dropped, `domain/search_terms.py`) and every quoted phrase,
    ANDed. Words are letters and digits only, so they need no escaping inside the double quotes."""
    phrases = lexical_query(raw).fts_words
    if not phrases:
        return None
    return " ".join(f'"{" ".join(words)}"' for words in phrases[:16])


def _kind_filter(result_type: SearchResultType | None) -> AssetKind | None:
    if result_type == SearchResultType.PHOTO:
        return AssetKind.IMAGE
    if result_type == SearchResultType.VIDEO:
        return AssetKind.VIDEO
    if result_type == SearchResultType.DOCUMENT:
        return AssetKind.DOCUMENT
    if result_type == SearchResultType.PDF_PAGE:
        return AssetKind.PDF
    return None


def _hit_from_row(row: object, requested_type: SearchResultType | None) -> SearchHit:
    mapping = dict(row)
    result_type = requested_type or _result_type_for_kind(str(mapping["kind"]))
    snippet = str(mapping.get("snippet_text") or "").strip()
    return SearchHit(
        id=str(mapping["asset_id"]),
        type=result_type,
        title=str(mapping["filename"]),
        score=float(mapping["rank"] or 0.0) * -1,
        reason=snippet or "filename or indexed text match",
        asset_id=str(mapping["asset_id"]),
        subtitle=str(mapping["mime_type"]),
        processing_state=ProcessingState(str(mapping["processing_state"])),
    )


def _result_type_for_kind(kind: str) -> SearchResultType:
    if kind == AssetKind.IMAGE.value:
        return SearchResultType.PHOTO
    if kind == AssetKind.VIDEO.value:
        return SearchResultType.VIDEO
    if kind == AssetKind.DOCUMENT.value:
        return SearchResultType.DOCUMENT
    if kind == AssetKind.PDF.value:
        return SearchResultType.PDF_PAGE
    return SearchResultType.ASSET


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(cursor)
    except ValueError:
        return 0
    return max(value, 0)
