from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest

from bento.application.indexing.embedding import ChunkVector, EmbeddingIndexingService
from bento.application.work_budget import WorkBudgetExceeded, work_deadline
from bento.domain.assets import AssetKind, ProcessingState
from bento.domain.indexing import EmbeddingRecord
from bento.domain.manifest import ManifestEventType
from bento.domain.smart_search import (
    MAX_CHUNKS_PER_ASSET,
    EmbeddingSpace,
    estimate_tokens,
    space_id_for,
)
from bento.domain.storage import BlobKind, BlobRef, StorageBackend
from tests.unit.embeddings.test_embedding_service import (
    FakeAssets,
    FakeBlobRefs,
    FakeClock,
    FakeManifest,
    FakeResolver,
    FakeTextCatalog,
    FakeVectorIndex,
    make_asset,
)

SPACE = EmbeddingSpace(
    id=space_id_for("embeddinggemma-2-q8_0", "6ea3e3a309d12a4779cfda98b8c19800d2d5da71", 4),
    model_id="embeddinggemma-2-q8_0",
    revision="6ea3e3a309d12a4779cfda98b8c19800d2d5da71",
    dims=4,
)


@dataclass
class FakeSpaceProvider:
    """Smart search provider: records each `embed_documents` call; returns one-hot-ish unit vectors."""

    calls: list[tuple[tuple[str, ...], str | None]] = field(default_factory=list)
    images: list[Path] = field(default_factory=list)
    fail: bool = False

    @property
    def space(self) -> EmbeddingSpace:
        return SPACE

    async def is_enabled(self) -> bool:
        return True

    async def embed_query(self, text: str) -> tuple[float, ...]:
        raise AssertionError(text)

    async def embed_documents(self, texts: Sequence[str], *, title: str | None = None) -> tuple[tuple[float, ...], ...]:
        if self.fail:
            raise RuntimeError("server down")
        self.calls.append((tuple(texts), title))
        start = sum(len(batch) for batch, _ in self.calls[:-1])
        return tuple(_unit(start + offset) for offset in range(len(texts)))

    async def embed_image(self, path: Path) -> tuple[float, ...]:
        self.images.append(path)
        raise AssertionError("pixels are not embedded in text-only spaces")


def _unit(index: int) -> tuple[float, ...]:
    values = [0.0, 0.0, 0.0, 0.0]
    values[index % 4] = 1.0
    return tuple(values)


@dataclass
class FakeChunkIndex:
    calls: list[tuple[str, EmbeddingRecord, tuple[ChunkVector, ...]]] = field(default_factory=list)

    async def index_chunk_vectors(self, space_id: str, record: EmbeddingRecord, chunks: Sequence[ChunkVector]) -> None:
        self.calls.append((space_id, record, tuple(chunks)))


@dataclass
class FakeRecorder:
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def record_embedding(
        self,
        asset_id: str,
        *,
        provider: str,
        dimensions: int,
        vector: Sequence[float],
        space: str | None = None,
        chunks: Sequence[Sequence[float]] | None = None,
        pages: Sequence[int | None] | None = None,
    ) -> None:
        self.calls.append(
            {
                "asset_id": asset_id,
                "provider": provider,
                "dimensions": dimensions,
                "vector": tuple(vector),
                "space": space,
                "chunks": None if chunks is None else [tuple(chunk) for chunk in chunks],
                "pages": None if pages is None else list(pages),
            }
        )


def build(
    tmp_path: Path,
    asset: Any,
    *,
    provider: Any,
    index: Any,
    text: str | None,
    assets: FakeAssets | None = None,
    manifest: FakeManifest | None = None,
    recorder: FakeRecorder | None = None,
) -> EmbeddingIndexingService:
    source = tmp_path / asset.filename
    source.write_bytes(b"source")
    blob = BlobRef(
        id="blob_1",
        asset_id=asset.id,
        backend=StorageBackend.LOCAL,
        kind=BlobKind.ORIGINAL,
        object_key=source.name,
        size_bytes=source.stat().st_size,
        sha256=asset.metadata.sha256,
    )
    return EmbeddingIndexingService(
        assets=assets or FakeAssets(asset),
        blob_refs=FakeBlobRefs(blob),
        resolver=FakeResolver(tmp_path),
        provider=provider,
        index=index,
        manifest=manifest or FakeManifest(),
        clock=FakeClock(),
        text_catalog=FakeTextCatalog(text),
        index_recorder=recorder,
    )


LONG_TEXT = " ".join(f"La factura número {n} de la luz vence el mes que viene y hay que pagarla." for n in range(900))


def test_long_document_is_chunked_capped_and_sent_in_batches_of_eight(tmp_path: Path) -> None:
    async def scenario() -> None:
        asset = make_asset(AssetKind.PDF, filename="facturas.pdf")
        assets, manifest = FakeAssets(asset), FakeManifest()
        provider, index, recorder = FakeSpaceProvider(), FakeChunkIndex(), FakeRecorder()
        service = build(
            tmp_path, asset, provider=provider, index=index, text=LONG_TEXT, assets=assets, manifest=manifest, recorder=recorder
        )

        record = await service.process_asset_embedding(asset.id)

        assert record is not None
        assert [len(batch) for batch, _ in provider.calls] == [8, 8]
        assert {title for _, title in provider.calls} == {"facturas.pdf"}
        assert all(estimate_tokens(text) <= 512 for batch, _ in provider.calls for text in batch)
        ((space_id, indexed_record, chunks),) = index.calls
        assert space_id == SPACE.id
        assert indexed_record == record
        assert record.dimensions == 4 and record.provider == SPACE.model_id
        assert [chunk.chunk_no for chunk in chunks] == list(range(MAX_CHUNKS_PER_ASSET))
        assert chunks[0].vector == (1.0, 0.0, 0.0, 0.0)
        assert assets.by_id[asset.id].processing_state == ProcessingState.INDEXED
        (event,) = manifest.events
        assert event.type == ManifestEventType.EMBEDDING_INDEXED
        assert event.payload["space_id"] == SPACE.id and event.payload["chunks"] == 16
        (sync,) = recorder.calls
        assert sync["space"] == SPACE.id and sync["dimensions"] == 4
        assert math.isclose(math.fsum(v * v for v in sync["vector"]), 1.0)
        assert sync["vector"] == pytest.approx((0.5, 0.5, 0.5, 0.5))
        # Every chunk travels to peers, in order, with its page.
        assert sync["chunks"] == [chunk.vector for chunk in chunks]
        assert sync["pages"] == [chunk.page for chunk in chunks]

    asyncio.run(scenario())


def test_mock_provider_publishes_its_legacy_space(tmp_path: Path) -> None:
    from bento.adapters.embeddings.mock import MockEmbeddingProvider
    from bento.domain.smart_search import legacy_space_id

    async def scenario() -> None:
        asset = make_asset(AssetKind.PDF, filename="nota.pdf")
        index, recorder = FakeVectorIndex(), FakeRecorder()
        service = build(
            tmp_path, asset, provider=MockEmbeddingProvider(dimensions=4), index=index, text="hola", recorder=recorder
        )

        await service.process_asset_embedding(asset.id)

        (sync,) = recorder.calls
        assert sync["space"] == legacy_space_id("mock", 4)
        assert sync["chunks"] is None and sync["pages"] is None

    asyncio.run(scenario())


def test_image_uses_ocr_text_and_metadata_not_pixels(tmp_path: Path) -> None:
    async def scenario() -> None:
        asset = make_asset(AssetKind.IMAGE, filename="playa.jpg")
        asset = replace(asset, metadata=replace(asset.metadata, exif={"place": "Playa de la Concha"}))
        provider, index = FakeSpaceProvider(), FakeChunkIndex()
        service = build(tmp_path, asset, provider=provider, index=index, text="FELIZ CUMPLE")

        await service.process_asset_embedding(asset.id)

        ((batch, title),) = provider.calls
        assert title == "playa.jpg"
        assert len(batch) == 1
        assert "FELIZ CUMPLE" in batch[0] and "Playa de la Concha" in batch[0] and "playa.jpg" in batch[0]
        assert provider.images == []

    asyncio.run(scenario())


def test_document_without_indexed_text_embeds_its_metadata(tmp_path: Path) -> None:
    async def scenario() -> None:
        asset = make_asset(AssetKind.PDF, filename="contrato_alquiler.pdf")
        provider, index = FakeSpaceProvider(), FakeChunkIndex()
        service = build(tmp_path, asset, provider=provider, index=index, text=None)

        await service.process_asset_embedding(asset.id)

        ((batch, _),) = provider.calls
        assert batch == ("contrato_alquiler.pdf contrato_alquiler.pdf application/pdf",)

    asyncio.run(scenario())


def test_index_without_chunk_tables_gets_the_asset_vector(tmp_path: Path) -> None:
    async def scenario() -> None:
        asset = make_asset(AssetKind.PDF)
        provider, index = FakeSpaceProvider(), FakeVectorIndex()
        service = build(tmp_path, asset, provider=provider, index=index, text="Texto corto.")

        record = await service.process_asset_embedding(asset.id)

        assert index.records == [record]
        assert index.vectors == [(1.0, 0.0, 0.0, 0.0)]

    asyncio.run(scenario())


def test_budget_exhaustion_requeues_without_failing_the_asset(tmp_path: Path) -> None:
    async def scenario() -> None:
        asset = make_asset(AssetKind.PDF)
        assets = FakeAssets(asset)
        provider, index = FakeSpaceProvider(), FakeChunkIndex()
        service = build(tmp_path, asset, provider=provider, index=index, text=LONG_TEXT, assets=assets)

        with work_deadline(0.0, clock=lambda: 1.0):
            with pytest.raises(WorkBudgetExceeded):
                await service.process_asset_embedding(asset.id)

        assert provider.calls == []
        assert index.calls == []
        assert assets.by_id[asset.id].processing_state == ProcessingState.EMBEDDING_PENDING

    asyncio.run(scenario())


def test_provider_failure_marks_partial_failure(tmp_path: Path) -> None:
    async def scenario() -> None:
        asset = make_asset(AssetKind.PDF)
        assets = FakeAssets(asset)
        service = build(
            tmp_path, asset, provider=FakeSpaceProvider(fail=True), index=FakeChunkIndex(), text="hola", assets=assets
        )

        with pytest.raises(RuntimeError, match="server down"):
            await service.process_asset_embedding(asset.id)

        assert assets.by_id[asset.id].processing_state == ProcessingState.FAILED_PARTIAL

    asyncio.run(scenario())
