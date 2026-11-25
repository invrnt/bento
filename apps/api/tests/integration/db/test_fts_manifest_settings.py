from __future__ import annotations

import asyncio
import json
from pathlib import Path

from bento.adapters.manifest import SQLiteManifestJournal
from bento.adapters.repositories import SQLiteAssetRepository
from bento.adapters.search.sqlite_fts import SQLiteFTSSearchIndex
from bento.adapters.settings import SettingsDefaults, SQLiteSettingsRepository
from bento.domain.indexing import IndexProviderState, OCRBlock
from bento.domain.manifest import ManifestEntityType, ManifestEventType
from bento.domain.search import SearchQuery, SearchResultType
from bento.domain.settings import WorkerStatus
from bento.domain.storage import StorageBackend

from tests.integration.db.support import FixedClock, migrated_session_factory, make_asset


def test_fts_indexes_asset_metadata_and_ocr_text(tmp_path: Path) -> None:
    async def scenario() -> None:
        factory = migrated_session_factory(tmp_path)
        clock = FixedClock()
        assets = SQLiteAssetRepository(factory)
        index = SQLiteFTSSearchIndex(factory, clock)
        asset = make_asset(filename="receipt.pdf")

        await assets.add(asset)
        await index.index_asset(asset)
        filename_results = await index.search(SearchQuery(text="receipt"))
        assert [hit.id for hit in filename_results.items] == [asset.id]

        await index.index_ocr(OCRBlock(id="ocr_1", asset_id=asset.id, text="Total cafe con leche"))
        ocr_results = await index.search(SearchQuery(text="cafe", result_type=SearchResultType.PDF_PAGE))
        assert [hit.asset_id for hit in ocr_results.items] == [asset.id]
        assert ocr_results.items[0].type == SearchResultType.PDF_PAGE

        await index.remove_asset(asset.id)
        assert (await index.search(SearchQuery(text="receipt"))).items == ()

    asyncio.run(scenario())


def test_manifest_append_and_idempotent_jsonl_export(tmp_path: Path) -> None:
    async def scenario() -> None:
        manifest = SQLiteManifestJournal(
            migrated_session_factory(tmp_path),
            FixedClock(),
            tmp_path / "journal",
        )

        await manifest.append(
            type=ManifestEventType.ASSET_CREATED,
            entity_type=ManifestEntityType.ASSET,
            entity_id="asset_1",
            payload={"filename": "receipt.pdf"},
        )
        await manifest.append(
            type=ManifestEventType.FOLDER_CREATED,
            entity_type=ManifestEntityType.FOLDER,
            entity_id="folder_1",
            payload={"name": "Docs"},
        )

        await manifest.export_jsonl()
        first_export = (tmp_path / "journal" / "manifest-events.jsonl").read_text(encoding="utf-8")
        await manifest.export_jsonl()
        second_export = (tmp_path / "journal" / "manifest-events.jsonl").read_text(encoding="utf-8")

        assert second_export == first_export
        rows = [json.loads(line) for line in second_export.splitlines()]
        assert [row["type"] for row in rows] == ["asset_created", "folder_created"]
        assert rows[0]["payload"] == {"filename": "receipt.pdf"}

    asyncio.run(scenario())


def test_settings_repository_merges_defaults_and_stored_values(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = SQLiteSettingsRepository(
            migrated_session_factory(tmp_path),
            FixedClock(),
            SettingsDefaults(
                storage_backend=StorageBackend.LOCAL,
                telegram_configured=False,
                ocr_state=IndexProviderState.DISABLED,
                embeddings_state=IndexProviderState.DISABLED,
                model_available=False,
                worker_status=WorkerStatus.STOPPED,
                worker_concurrency=1,
                data_paths={"db": "data/db"},
            ),
        )

        await settings.set_value("storage_backend", "telegram")
        await settings.set_value("telegram_configured", "true")
        await settings.set_value("ocr_state", "ready")
        await settings.set_value("worker_status", "running")
        await settings.set_value("worker_concurrency", "2")
        await settings.set_value("data_path.journal", "data/journal")

        public = await settings.get_public_settings()

        assert public.storage_backend == StorageBackend.TELEGRAM
        assert public.telegram_configured is True
        assert public.ocr_state == IndexProviderState.READY
        assert public.embeddings_state == IndexProviderState.DISABLED
        assert public.worker_status == WorkerStatus.RUNNING
        assert public.worker_concurrency == 2
        assert public.data_paths == {"db": "data/db", "journal": "data/journal"}

    asyncio.run(scenario())


def test_manifest_append_adds_one_line_without_reexporting(tmp_path: Path) -> None:
    """Regression: every append used to rewrite the whole journal, so ingest slowed linearly with library size."""

    async def scenario() -> None:
        manifest = SQLiteManifestJournal(migrated_session_factory(tmp_path), FixedClock(), tmp_path / "journal")
        target = tmp_path / "journal" / "manifest-events.jsonl"
        for index in range(3):
            await manifest.append(
                type=ManifestEventType.ASSET_CREATED,
                entity_type=ManifestEntityType.ASSET,
                entity_id=f"asset_{index}",
                payload={"n": index},
            )
        rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
        assert [row["entity_id"] for row in rows] == ["asset_0", "asset_1", "asset_2"]

        exports: list[None] = []
        original = manifest._export_all
        manifest._export_all = lambda: exports.append(None) or original()  # type: ignore[method-assign]
        await manifest.append(
            type=ManifestEventType.FOLDER_CREATED,
            entity_type=ManifestEntityType.FOLDER,
            entity_id="folder_1",
            payload={},
        )
        assert exports == []  # the mirror exists: one appended line, no full re-export
        appended = target.read_text(encoding="utf-8")
        await manifest.export_jsonl()
        assert target.read_text(encoding="utf-8") == appended  # incremental mirror == full export

        target.unlink()
        await manifest.append(
            type=ManifestEventType.FOLDER_CREATED,
            entity_type=ManifestEntityType.FOLDER,
            entity_id="folder_2",
            payload={},
        )
        assert len(target.read_text(encoding="utf-8").splitlines()) == 5  # a missing mirror is rebuilt whole

    asyncio.run(scenario())
