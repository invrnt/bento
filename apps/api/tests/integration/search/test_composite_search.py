from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from bento.adapters.repositories import SQLiteAssetRepository, SQLiteFolderRepository
from bento.adapters.search.composite import CompositeSearchIndex
from bento.adapters.search.sqlite_fts import SQLiteFTSSearchIndex
from bento.adapters.search.sqlite_vec import SQLiteVecSearchIndex
from bento.domain.assets import AssetKind, AssetMetadata, AssetMode
from bento.domain.drive import Folder
from bento.domain.indexing import EmbeddingRecord, OCRBlock
from bento.domain.search import SearchQuery, SearchResultType

from tests.integration.db.support import FixedClock, migrated_session_factory, make_asset
from tests.integration.search.vector_support import seeded_unit


def test_filename_only_search_works_with_embeddings_disabled(tmp_path: Path) -> None:
    async def scenario() -> None:
        factory = migrated_session_factory(tmp_path)
        clock = FixedClock()
        assets = SQLiteAssetRepository(factory)
        fts = SQLiteFTSSearchIndex(factory, clock)
        search = CompositeSearchIndex(factory, clock, text_index=fts)
        asset = make_asset("asset_receipt", filename="receipt-2026.pdf")

        await assets.add(asset)
        await search.index_asset(asset)

        results = await search.search(SearchQuery(text="receipt"))

        assert [item.asset_id for item in results.items] == [asset.id]
        assert results.items[0].reason
        assert results.items[0].processing_state is not None

    asyncio.run(scenario())


def test_ocr_search_returns_explanation(tmp_path: Path) -> None:
    async def scenario() -> None:
        factory = migrated_session_factory(tmp_path)
        clock = FixedClock()
        assets = SQLiteAssetRepository(factory)
        search = CompositeSearchIndex(factory, clock, text_index=SQLiteFTSSearchIndex(factory, clock))
        asset = make_asset("asset_ocr", filename="scan.pdf")

        await assets.add(asset)
        await search.index_asset(asset)
        await search.index_ocr(OCRBlock(id="ocr_1", asset_id=asset.id, text="Total cafe con leche"))

        results = await search.search(SearchQuery(text="cafe"))

        assert results.items
        assert results.items[0].asset_id == asset.id
        assert "OCR" in results.items[0].reason

    asyncio.run(scenario())


class _LegacyQueryProvider:
    """A provider from before embedding spaces: one `embed_text` for queries and documents."""

    def __init__(self, dimensions: int) -> None:
        self._dimensions = dimensions

    async def is_enabled(self) -> bool:
        return True

    async def embed_text(self, asset_id: str, text: str) -> tuple[EmbeddingRecord, tuple[float, ...]]:
        record = EmbeddingRecord(
            id=f"emb_{asset_id}", asset_id=asset_id, provider="mock", vector_ref="mock:text", dimensions=self._dimensions
        )
        return record, seeded_unit(text, self._dimensions)


def test_vector_search_uses_a_legacy_provider_when_available(tmp_path: Path) -> None:
    async def scenario() -> None:
        factory = migrated_session_factory(tmp_path)
        clock = FixedClock()
        assets = SQLiteAssetRepository(factory)
        provider = _LegacyQueryProvider(dimensions=3)
        vector = SQLiteVecSearchIndex(factory, clock, dimensions=3, prefer_sqlite_vec=False)
        search = CompositeSearchIndex(
            factory,
            clock,
            text_index=SQLiteFTSSearchIndex(factory, clock),
            vector_index=vector,
            query_embedding_provider=provider,
        )
        asset = make_asset("asset_scene", filename="vacation.jpg", kind=AssetKind.IMAGE)
        _, query_vector = await provider.embed_text("query", "playa atardecer")
        record = EmbeddingRecord(
            id="emb_scene",
            asset_id=asset.id,
            provider="mock",
            vector_ref="mock:scene",
            dimensions=3,
        )

        await assets.add(asset)
        await search.index_embedding(record)
        # No space named: the record's legacy space (`legacy:mock/3`), which is also the query's.
        await vector.index_embedding_vector(record, query_vector)

        results = await search.search(SearchQuery(text="playa atardecer"))

        assert [item.asset_id for item in results.items] == [asset.id]
        assert "busqueda semantica" in results.items[0].reason

    asyncio.run(scenario())


def test_date_type_folder_filters_and_facets(tmp_path: Path) -> None:
    async def scenario() -> None:
        factory = migrated_session_factory(tmp_path)
        clock = FixedClock()
        assets = SQLiteAssetRepository(factory)
        folders = SQLiteFolderRepository(factory)
        search = CompositeSearchIndex(factory, clock, text_index=SQLiteFTSSearchIndex(factory, clock))
        folder = Folder(
            id="folder_docs",
            name="Documentos",
            parent_id=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        matching = _dated_asset(
            "asset_photo",
            filename="playa.jpg",
            folder_id=folder.id,
            kind=AssetKind.IMAGE,
            taken_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
        filtered_out = _dated_asset(
            "asset_pdf",
            filename="playa.pdf",
            folder_id=folder.id,
            kind=AssetKind.PDF,
            taken_at=datetime(2026, 3, 15, tzinfo=UTC),
            sha256="c" * 64,
        )

        await folders.add(folder)
        await assets.add(matching)
        await assets.add(filtered_out)
        await search.index_asset(matching)
        await search.index_asset(filtered_out)

        results = await search.search(
            SearchQuery(
                text="playa marzo 2026",
                result_type=SearchResultType.PHOTO,
                folder_id=folder.id,
            )
        )

        assert [item.asset_id for item in results.items] == [matching.id]
        assert [(facet.type, facet.count) for facet in results.facets] == [(SearchResultType.PHOTO, 1)]

    asyncio.run(scenario())


def test_folder_results_are_first_class(tmp_path: Path) -> None:
    async def scenario() -> None:
        factory = migrated_session_factory(tmp_path)
        clock = FixedClock()
        folders = SQLiteFolderRepository(factory)
        search = CompositeSearchIndex(factory, clock, text_index=SQLiteFTSSearchIndex(factory, clock))
        folder = Folder(
            id="folder_work",
            name="Trabajo",
            parent_id=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        await folders.add(folder)

        results = await search.search(SearchQuery(text="Trabajo", result_type=SearchResultType.FOLDER))

        assert results.items[0].id == folder.id
        assert results.items[0].type == SearchResultType.FOLDER
        assert results.items[0].reason

    asyncio.run(scenario())


def _dated_asset(
    asset_id: str,
    *,
    filename: str,
    folder_id: str,
    kind: AssetKind,
    taken_at: datetime,
    sha256: str = "b" * 64,
):
    asset = make_asset(
        asset_id,
        filename=filename,
        folder_id=folder_id,
        kind=kind,
        mode=AssetMode.PHOTOS if kind == AssetKind.IMAGE else AssetMode.DRIVE,
        sha256=sha256,
    )
    return replace(
        asset,
        metadata=AssetMetadata(
            original_filename=filename,
            mime_type="image/jpeg" if kind == AssetKind.IMAGE else "application/pdf",
            size_bytes=128,
            sha256=sha256,
            taken_at=taken_at,
        ),
        created_at=taken_at,
        updated_at=taken_at,
    )


def test_hits_carry_reason_codes_snippet_folder_mime_and_origin(tmp_path: Path) -> None:
    from bento.adapters.repositories import SQLiteAlbumRepository
    from bento.domain.assets import AssetOrigin
    from bento.domain.photos import Album
    from bento.domain.search import MatchReason, SearchOrigin

    async def scenario() -> None:
        factory = migrated_session_factory(tmp_path)
        clock = FixedClock()
        assets = SQLiteAssetRepository(factory)
        folders = SQLiteFolderRepository(factory)
        search = CompositeSearchIndex(factory, clock, text_index=SQLiteFTSSearchIndex(factory, clock))
        now = datetime(2026, 1, 1, tzinfo=UTC)
        await folders.add(Folder(id="folder_tax", name="Impuestos", parent_id=None, created_at=now, updated_at=now))
        scan = replace(make_asset("asset_scan", filename="scan.pdf", folder_id="folder_tax"), origin=AssetOrigin.DEVICE)
        inbox = replace(make_asset("asset_inbox", filename="otro.pdf", sha256="b" * 64), origin=AssetOrigin.TELEGRAM_INBOX)
        photo = replace(
            make_asset("asset_beach", filename="IMG_1.jpg", sha256="c" * 64, kind=AssetKind.IMAGE), origin=None
        )
        for asset in (scan, inbox, photo):
            await assets.add(asset)
            await search.index_asset(asset)
        await search.index_ocr(
            OCRBlock(id="ocr_1", asset_id=scan.id, text="Factura número 42. Total a pagar: 99 € por el café de la mañana")
        )
        await search.index_ocr(OCRBlock(id="ocr_2", asset_id=inbox.id, text="Otro café"))
        await SQLiteAlbumRepository(factory).add(
            Album(id="album_sea", title="Playa", asset_ids=frozenset({photo.id}), created_at=now, updated_at=now)
        )

        results = await search.search(SearchQuery(text="café"))
        scan_hit = next(item for item in results.items if item.asset_id == scan.id and item.type != SearchResultType.OCR_BLOCK)
        assert scan_hit.match_reasons[0] == MatchReason.OCR_TEXT
        assert scan_hit.snippet is not None and scan_hit.snippet.source == MatchReason.OCR_TEXT
        start, end = scan_hit.snippet.highlights[0]
        assert scan_hit.snippet.text[start:end].casefold() == "café"
        assert (scan_hit.folder_id, scan_hit.folder_name) == ("folder_tax", "Impuestos")
        assert scan_hit.mime_type == "application/pdf"
        assert scan_hit.origin == SearchOrigin.DEVICE

        only_device = await search.search(SearchQuery(text="café", origin=SearchOrigin.DEVICE))
        assert {item.asset_id for item in only_device.items} == {scan.id}
        only_telegram = await search.search(SearchQuery(text="café", origin=SearchOrigin.TELEGRAM))
        assert {item.asset_id for item in only_telegram.items} == {inbox.id}

        in_folder = await search.search(SearchQuery(text="impuestos"))
        folder_hit = next(item for item in in_folder.items if item.type == SearchResultType.FOLDER)
        assert folder_hit.match_reasons == (MatchReason.FOLDER_NAME,) and folder_hit.origin is None
        member = next(item for item in in_folder.items if item.asset_id == scan.id)
        assert MatchReason.FOLDER_NAME in member.match_reasons
        assert member.snippet is not None and member.snippet.text == "Impuestos"
        assert member.snippet.highlights == ((0, 9),)

        in_album = await search.search(SearchQuery(text="playa"))
        beach = next(item for item in in_album.items if item.asset_id == photo.id)
        assert MatchReason.ALBUM in beach.match_reasons
        assert beach.origin == SearchOrigin.PEER
        peers = await search.search(SearchQuery(text="playa", origin=SearchOrigin.PEER))
        assert [item.asset_id for item in peers.items] == [photo.id]  # the album itself is left out

    asyncio.run(scenario())


def test_filename_match_finds_an_asset_older_than_the_candidate_window(tmp_path: Path) -> None:
    """An image with no indexed text (OCR off) is found by name even when many newer assets exist."""

    async def scenario() -> None:
        factory = migrated_session_factory(tmp_path)
        clock = FixedClock()
        assets = SQLiteAssetRepository(factory)
        search = CompositeSearchIndex(factory, clock, text_index=SQLiteFTSSearchIndex(factory, clock))
        old = make_asset("asset_old", filename="endesa-recibo-abril.png", kind=AssetKind.IMAGE, sha256="0" * 64)
        await assets.add(replace(old, created_at=datetime(2020, 1, 1, tzinfo=UTC), updated_at=datetime(2020, 1, 1, tzinfo=UTC)))
        for index in range(60):
            await assets.add(make_asset(f"asset_new_{index:02d}", filename=f"photo-{index:02d}.jpg", kind=AssetKind.IMAGE, sha256=f"{index + 1:064x}"))

        results = await search.search(SearchQuery(text="endesa", limit=6))

        assert [item.asset_id for item in results.items] == ["asset_old"]
        assert "filename" in results.items[0].match_reasons

    asyncio.run(scenario())
