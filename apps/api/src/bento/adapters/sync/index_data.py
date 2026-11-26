"""`asset_index` entity data: read back from the local search tables, written through the search adapters."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.ocr.sqlite_pages import SQLitePDFPageTextCatalog
from bento.adapters.search.sqlite_fts import SQLiteFTSSearchIndex
from bento.adapters.search.sqlite_vec import (
    CHUNKS_TABLE,
    SQLiteVecSearchIndex,
    StoredEmbedding,
    active_space_id,
    is_unknown_peer_space,
    stored_embeddings,
    unknown_peer_space_id,
)
from bento.application.sync.asset_index import ocr_fields
from bento.application.sync.codec import b64url_encode, decode_vector
from bento.domain.errors import ValidationFailedError
from bento.domain.indexing import EmbeddingRecord, OCRBlock
from bento.domain.smart_search import (
    InvalidEmbeddingSpaceError,
    PeerVectorDecision,
    legacy_space_id,
    parse_space_id,
    peer_vector_decision,
)
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AssetTextModel, OCRBlockModel, PDFPageModel
from bento.ports.repositories import ClockPort

ActiveSpaceResolver = Callable[[], Awaitable[str | None]]

LOGGER = logging.getLogger("bento.sync.index")
_CHUNK = 500


@dataclass(frozen=True, slots=True)
class _SyncedEmbedding:
    provider: str
    dimensions: int
    space_id: str | None
    vectors: tuple[tuple[float, ...], ...]
    pages: tuple[int | None, ...]


class AssetIndexData:
    """Synced embeddings carry their `space`: they are indexed only when it equals this device's active space
    (`peer_vector_decision`), and stored otherwise, so a later switch to that space can index them. Peers that
    send no `space` are an unknown space: stored under `legacy:unknown.<provider>/<dims>`, never searched.

    The local active space is the active `embedding_spaces` row, else `active_space()` when given, else the legacy
    space of `legacy_provider` at `vector_dimensions` (mock and custom providers that predate managed spaces).
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        clock: ClockPort,
        *,
        vector_dimensions: int | None = None,
        legacy_provider: str | None = None,
        active_space: ActiveSpaceResolver | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._fts = SQLiteFTSSearchIndex(session_factory, clock)
        self._pages = SQLitePDFPageTextCatalog(session_factory, clock)
        self._vectors = SQLiteVecSearchIndex(session_factory, clock, dimensions=vector_dimensions)
        self._vector_dimensions = vector_dimensions
        self._legacy_provider = legacy_provider if legacy_provider not in {None, "", "disabled"} else None
        self._active_space = active_space

    async def local_active_space_id(self) -> str | None:
        active = await self._vectors.active_space_id()
        if active is not None:
            return active
        if self._active_space is not None:
            resolved = await self._active_space()
            if resolved is not None:
                return resolved
        if self._legacy_provider is not None and self._vector_dimensions:
            return legacy_space_id(self._legacy_provider, self._vector_dimensions)
        return None

    # Read-back (initial publish, snapshots)

    def indexed_asset_ids(self, session: Session) -> list[str]:
        ids: set[str] = set(session.scalars(select(OCRBlockModel.asset_id).distinct()))
        ids.update(session.scalars(select(PDFPageModel.asset_id).distinct()))
        ids.update(str(value) for value in session.execute(text(f"SELECT DISTINCT asset_id FROM {CHUNKS_TABLE}")).scalars())
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
        """One embedding per asset: the one in the active space, else the newest stored one."""
        active = active_space_id(session)
        result: dict[str, dict[str, Any]] = {}
        for asset_id, stored in stored_embeddings(session, asset_ids).items():
            chosen = next((item for item in stored if item.space_id == active), stored[0])
            result[asset_id] = {"embedding": _embedding_value(chosen)}
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
        if value is None:
            await self._vectors.remove_asset(asset_id)
            return
        try:
            synced = _parse_embedding(value)
        except (KeyError, TypeError, ValueError, ValidationFailedError) as exc:
            LOGGER.info("Skipped a synced embedding for an asset: %s", exc.__class__.__name__)
            return
        active = await self.local_active_space_id()
        decision = peer_vector_decision(active, synced.space_id, synced.dimensions)
        space_id = synced.space_id or unknown_peer_space_id(synced.provider, synced.dimensions)
        record = EmbeddingRecord(
            id=f"embsync_{asset_id}"[:64],
            asset_id=asset_id,
            provider=synced.provider,
            vector_ref=f"sync:{synced.provider}"[:256],
            dimensions=synced.dimensions,
        )
        try:
            await self._vectors.index_chunks(
                record,
                synced.vectors,
                space_id=space_id,
                pages=synced.pages,
                searchable=decision is PeerVectorDecision.INDEX,
            )
        except (ValueError, InvalidEmbeddingSpaceError, IntegrityError) as exc:
            LOGGER.info("Skipped a synced embedding for an asset: %s", exc.__class__.__name__)


def _parse_embedding(value: Any) -> _SyncedEmbedding:
    provider = str(value["provider"])
    dimensions = int(value["dimensions"])
    space_id = _valid_space(value.get("space"), dimensions)
    vectors: list[tuple[float, ...]] = []
    pages: list[int | None] = []
    chunks = value.get("chunks")
    if isinstance(chunks, list) and chunks:
        for chunk in sorted(chunks, key=lambda item: int(item["chunk_no"])):
            vectors.append(decode_vector(str(chunk["vector_b64_f32"]), dimensions))
            page = chunk.get("page")
            pages.append(page if isinstance(page, int) else None)
    else:
        vectors.append(decode_vector(str(value["vector_b64_f32"]), dimensions))
        pages.append(None)
    return _SyncedEmbedding(
        provider=provider, dimensions=dimensions, space_id=space_id, vectors=tuple(vectors), pages=tuple(pages)
    )


def _valid_space(value: Any, dimensions: int) -> str | None:
    """The peer's space id, or `None` (unknown space) when missing, malformed or not matching the vector."""
    if not isinstance(value, str) or not value or is_unknown_peer_space(value):
        return None
    try:
        _, _, dims = parse_space_id(value)
    except InvalidEmbeddingSpaceError:
        return None
    return value if dims == dimensions else None


def _embedding_value(stored: StoredEmbedding) -> dict[str, Any]:
    value: dict[str, Any] = {
        "provider": stored.provider,
        "dimensions": stored.dimensions,
        "vector_b64_f32": b64url_encode(stored.chunks[0].vector),
    }
    if not is_unknown_peer_space(stored.space_id):
        value["space"] = stored.space_id
    if len(stored.chunks) > 1:
        value["chunks"] = [
            {"chunk_no": chunk.chunk_no, "page": chunk.page, "vector_b64_f32": b64url_encode(chunk.vector)}
            for chunk in stored.chunks
        ]
    return value


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
