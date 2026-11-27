"""Snapshots publish text read from the file itself (`text_extract`) in place of OCR text, as local search uses it."""

from __future__ import annotations

import asyncio
from pathlib import Path

from bento.adapters.search.sqlite_fts import SQLiteFTSSearchIndex
from bento.adapters.sync.index_data import AssetIndexData
from bento.domain.indexing import ExtractedPage, OCRBlock
from bento.infrastructure.db.engine import session_scope
from tests.integration.db.support import FixedClock, migrated_session_factory
from tests.integration.search.vector_support import add_assets


def test_snapshot_prefers_document_text_over_ocr(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    clock = FixedClock()
    fts = SQLiteFTSSearchIndex(factory, clock)
    asyncio.run(add_assets(factory, "asset_scan", "asset_text"))
    asyncio.run(fts.index_ocr(OCRBlock(id="ocr_scan", asset_id="asset_scan", text="texto del escaneo")))
    asyncio.run(fts.index_ocr(OCRBlock(id="ocr_text", asset_id="asset_text", text="ocr ruidoso")))
    asyncio.run(
        fts.replace_document_text(
            "asset_text", [ExtractedPage("capa de texto, página uno", 1), ExtractedPage("página dos", 2)]
        )
    )
    data = AssetIndexData(factory, clock)

    with session_scope(factory) as session:
        assert data.indexed_asset_ids(session) == ["asset_scan", "asset_text"]
        snapshot = data.read(session, ["asset_scan", "asset_text"])

    assert snapshot["asset_scan"]["ocr_text"] == "texto del escaneo"
    assert snapshot["asset_text"]["ocr_text"] == "capa de texto, página uno\npágina dos"
