"""`asset_index` entity data: read back from the local search tables, written through the search adapters."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.ocr.sqlite_pages import SQLitePDFPageTextCatalog
from bento.adapters.search.sqlite_fts import SQLiteFTSSearchIndex
from bento.adapters.search.sqlite_vec import SQLiteVecSearchIndex, _load_sqlite_vec
from bento.application.sync.asset_index import ocr_fields
from bento.application.sync.codec import b64url_encode, decode_vector
from bento.domain.errors import ValidationFailedError
from bento.domain.indexing import EmbeddingRecord, OCRBlock
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AssetEmbeddingModel, AssetTextModel, OCRBlockModel, PDFPageModel
from bento.ports.repositories import ClockPort

LOGGER = logging.getLogger("bento.sync.index")
_CHUNK = 500


class AssetIndexData:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        clock: ClockPort,
        *,
        vector_dimensions: int | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._fts = SQLiteFTSSearchIndex(session_factory, clock)
        self._pages = SQLitePDFPageTextCatalog(session_factory, clock)
        self._vectors = (
            SQLiteVecSearchIndex(session_factory, clock, dimensions=vector_dimensions) if vector_dimensions else None
        )

    # Read-back (initial publish, snapshots)

    def indexed_asset_ids(self, session: Session) -> list[str]:
        ids: set[str] = set(session.scalars(select(OCRBlockModel.asset_id).distinct()))
        ids.update(session.scalars(select(PDFPageModel.asset_id).distinct()))
        ids.update(session.scalars(select(AssetEmbeddingModel.asset_id).distinct()))
        return sorted(ids)

    def read(self, session: Session, asset_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        wanted = sorted(set(asset_ids))
        data: dict[str, dict[str, Any]] = {}
        for start in range(0, len(wanted), _CHUNK):
            chunk = wanted[start : start + _CHUNK]
            data.update(self._read_text(session, chunk))
            for asset_id, embedding in self._read_embeddings(session, chunk).items():
                data.setdefault(asset_id, {}).update(embedding)
        return data

    def _read_text(self, session: Session, asset_ids: list[str]) -> dict[str, dict[str, Any]]:
        blocks: dict[str, list[str]] = {}
        for asset_id, block_text in session.execute(
            select(OCRBlockModel.asset_id, OCRBlockModel.text)
            .where(OCRBlockModel.asset_id.in_(asset_ids))
            .order_by(OCRBlockModel.asset_id, OCRBlockModel.page_number.nulls_first(), OCRBlockModel.id)
        ):
            if block_text.strip():
                blocks.setdefault(asset_id, []).append(block_text)
        pages: dict[str, list[tuple[int, str]]] = {}
        for asset_id, page_number, page_text in session.execute(
            select(PDFPageModel.asset_id, PDFPageModel.page_number, PDFPageModel.text)
            .where(PDFPageModel.asset_id.in_(asset_ids))
            .order_by(PDFPageModel.asset_id, PDFPageModel.page_number)
        ):
            pages.setdefault(asset_id, []).append((page_number, page_text or ""))
        return {
            asset_id: ocr_fields(
                ocr_text="\n".join(blocks.get(asset_id, ())), pdf_pages=pages.get(asset_id, ()), language=None
            )
            for asset_id in sorted(set(blocks) | set(pages))
        }

    def _read_embeddings(self, session: Session, asset_ids: list[str]) -> dict[str, dict[str, Any]]:
        latest: dict[str, AssetEmbeddingModel] = {}
        for row in session.scalars(
            select(AssetEmbeddingModel)
            .where(AssetEmbeddingModel.asset_id.in_(asset_ids))
            .order_by(AssetEmbeddingModel.created_at, AssetEmbeddingModel.id)
        ):
            latest[row.asset_id] = row
        result: dict[str, dict[str, Any]] = {}
        for asset_id, row in latest.items():
            raw = _stored_vector(session, row.id)
            if raw is None or len(raw) != row.dimensions * 4:
                continue
            result[asset_id] = {
                "embedding": {
                    "provider": row.provider,
                    "dimensions": row.dimensions,
                    "vector_b64_f32": b64url_encode(raw),
                }
            }
        return result

    # Writes from applied ops (after the apply transaction committed)

    async def write(self, asset_id: str, fields: Mapping[str, Any]) -> None:
        if "ocr_text" in fields or "pdf_pages" in fields:
            await self._write_text(asset_id, fields)
        if "embedding" in fields:
            await self._write_embedding(asset_id, fields["embedding"])

    async def remove(self, asset_id: str) -> None:
        await self._fts.remove_asset(asset_id)
        with session_scope(self._session_factory) as session:
            session.execute(delete(PDFPageModel).where(PDFPageModel.asset_id == asset_id))
        if self._vectors is not None:
            await self._vectors.remove_asset(asset_id)

    async def _write_text(self, asset_id: str, fields: Mapping[str, Any]) -> None:
        pages = _pages(fields.get("pdf_pages"))
        ocr_text = fields.get("ocr_text")
        with session_scope(self._session_factory) as session:
            session.execute(delete(OCRBlockModel).where(OCRBlockModel.asset_id == asset_id))
            session.execute(
                delete(AssetTextModel).where(AssetTextModel.asset_id == asset_id, AssetTextModel.source == "ocr")
            )
            if "pdf_pages" in fields:
                session.execute(delete(PDFPageModel).where(PDFPageModel.asset_id == asset_id))
        if pages:
            for page_number, page_text in pages:
                await self._pages.save_page_text(asset_id=asset_id, page_number=page_number, text=page_text)
                if page_text.strip():
                    await self._fts.index_ocr(
                        OCRBlock(id=_block_id(asset_id, page_number), asset_id=asset_id, text=page_text, page_number=page_number)
                    )
        elif isinstance(ocr_text, str) and ocr_text.strip():
            await self._fts.index_ocr(OCRBlock(id=_block_id(asset_id, None), asset_id=asset_id, text=ocr_text))

    async def _write_embedding(self, asset_id: str, value: Any) -> None:
        if self._vectors is None:
            return
        await self._vectors.remove_asset(asset_id)
        if value is None:
            return
        try:
            provider = str(value["provider"])
            dimensions = int(value["dimensions"])
            vector = decode_vector(str(value["vector_b64_f32"]), dimensions)
            record = EmbeddingRecord(
                id=f"embsync_{asset_id}"[:64],
                asset_id=asset_id,
                provider=provider,
                vector_ref=f"sync:{provider}"[:256],
                dimensions=dimensions,
            )
            await self._vectors.index_embedding_vector(record, vector)
        except (KeyError, TypeError, ValueError, ValidationFailedError) as exc:
            # Different local embedding dimensions or a malformed vector: search falls back to text.
            LOGGER.info("Skipped a synced embedding for an asset: %s", exc.__class__.__name__)


def _pages(value: Any) -> list[tuple[int, str]]:
    if not isinstance(value, list):
        return []
    pages: list[tuple[int, str]] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("page"), int) and isinstance(item.get("text"), str):
            pages.append((item["page"], item["text"]))
    return sorted(pages)


def _block_id(asset_id: str, page_number: int | None) -> str:
    suffix = f"_p{page_number}" if page_number is not None else ""
    return f"ocrsync_{asset_id}{suffix}"[:58]


def _stored_vector(session: Session, embedding_id: str) -> bytes | None:
    try:
        raw = session.execute(
            text("SELECT vector FROM asset_embedding_vectors_fallback WHERE embedding_id = :embedding_id"),
            {"embedding_id": embedding_id},
        ).scalar()
    except OperationalError:
        raw = None
    if raw is not None:
        return bytes(raw)
    if not _load_sqlite_vec(session):
        return None
    try:
        raw = session.execute(
            text(
                """
                SELECT v.embedding FROM asset_embedding_vec AS v
                JOIN asset_embedding_vector_map AS m ON m.rowid = v.rowid
                WHERE m.embedding_id = :embedding_id
                """
            ),
            {"embedding_id": embedding_id},
        ).scalar()
    except OperationalError:
        return None
    return bytes(raw) if raw is not None else None
