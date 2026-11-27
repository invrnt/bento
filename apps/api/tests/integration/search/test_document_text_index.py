"""Document text in `asset_text` (`source = "document"`): FTS and the embedding text read it, and it wins over OCR."""

from __future__ import annotations

import asyncio
from pathlib import Path

from bento.adapters.embeddings import SQLiteEmbeddingTextCatalog
from bento.adapters.search.sqlite_fts import SQLiteFTSSearchIndex
from bento.domain.indexing import ExtractedPage, OCRBlock
from bento.domain.search import SearchQuery
from tests.integration.db.support import FixedClock, migrated_session_factory
from tests.integration.search.vector_support import add_assets


def _hits(fts: SQLiteFTSSearchIndex, query: str) -> list[str]:
    return [item.asset_id or "" for item in asyncio.run(fts.search(SearchQuery(text=query))).items]


def test_document_text_is_searchable_ordered_by_page_and_replaces_ocr(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    fts = SQLiteFTSSearchIndex(factory, FixedClock())
    catalog = SQLiteEmbeddingTextCatalog(factory)
    asyncio.run(add_assets(factory, "asset_1"))
    asyncio.run(fts.index_ocr(OCRBlock(id="ocr_1", asset_id="asset_1", text="ocr garabato", page_number=1)))
    assert _hits(fts, "garabato") == ["asset_1"]
    assert asyncio.run(catalog.text_for_asset("asset_1")) == "ocr garabato"

    pages = [ExtractedPage(f"página {n} alquiler", n) for n in (10, 2, 1)]
    asyncio.run(fts.replace_document_text("asset_1", pages))

    assert asyncio.run(fts.has_document_text("asset_1"))
    assert _hits(fts, "alquiler") == ["asset_1"]
    assert _hits(fts, "garabato") == []  # the text layer wins over OCR
    assert asyncio.run(catalog.text_for_asset("asset_1")) == "página 1 alquiler\npágina 2 alquiler\npágina 10 alquiler"

    # Replacing with nothing removes it, and the OCR text is used again.
    asyncio.run(fts.replace_document_text("asset_1", []))
    assert not asyncio.run(fts.has_document_text("asset_1"))
    assert _hits(fts, "garabato") == ["asset_1"] and _hits(fts, "alquiler") == []
