from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from bento.application.media.service import BlobPathResolverPort, BlobRefCatalogPort
from bento.application.work_budget import WorkBudgetExceeded, check_safe_boundary
from bento.domain.assets import Asset, AssetKind, ProcessingState
from bento.domain.errors import AssetNotFoundError, ValidationFailedError
from bento.domain.indexing import EmbeddingRecord
from bento.domain.manifest import ManifestEntityType, ManifestEventType
from bento.domain.smart_search import (
    DEFAULT_CHUNK_TOKENS,
    EMBEDDING_BATCH_SIZE,
    MAX_CHUNKS_PER_ASSET,
    EmbeddingSpace,
    InvalidEmbeddingSpaceError,
    TextChunk,
    batched,
    chunk_text,
    legacy_space_id,
    truncate_and_renormalize,
)
from bento.domain.storage import BlobKind
from bento.ports.manifest import ManifestJournalPort
from bento.ports.repositories import AssetRepositoryPort, ClockPort

LOGGER = logging.getLogger("bento.indexing.embedding")

Vector = tuple[float, ...]


class EmbeddingVectorProviderPort(Protocol):
    """Pre-Stage-24 providers (`mock`, `disabled`): one vector per asset, no space, no prefixes."""

    async def is_enabled(self) -> bool: ...

    async def embed_text(self, asset_id: str, text: str) -> tuple[EmbeddingRecord, Vector]: ...

    async def embed_image(self, asset_id: str, image_path: Path) -> tuple[EmbeddingRecord, Vector]: ...


@runtime_checkable
class SpaceEmbeddingProviderPort(Protocol):
    """The smart search slice of `ports.providers.EmbeddingProviderPort` this service uses: vectors are
    already truncated to `space.dims` and normalised, and the provider applies the document prefix."""

    async def is_enabled(self) -> bool: ...

    @property
    def space(self) -> EmbeddingSpace: ...

    async def embed_documents(self, texts: Sequence[str], *, title: str | None = None) -> tuple[Vector, ...]: ...


class EmbeddingVectorIndexPort(Protocol):
    async def index_embedding_vector(self, record: EmbeddingRecord, vector: Vector) -> None: ...


@dataclass(frozen=True, slots=True)
class ChunkVector:
    chunk_no: int
    page: int | None
    vector: Vector


@runtime_checkable
class ChunkVectorIndexPort(Protocol):
    """Vector store for smart search spaces (`asset_embeddings` + `asset_embedding_chunks`, Stage 24)."""

    async def index_chunk_vectors(self, space_id: str, record: EmbeddingRecord, chunks: Sequence[ChunkVector]) -> None:
        """Replace the asset's rows in `space_id`: its `asset_embeddings` row for `record` and every chunk."""
        ...


class EmbeddingTextCatalogPort(Protocol):
    async def text_for_asset(self, asset_id: str) -> str | None: ...


class EmbeddingIndexRecorderPort(Protocol):
    """Publishes the asset's embedding to other devices (`asset_index` op, which carries `space`, and every
    chunk with its page when there is more than one). `application.sync.ports.AssetIndexRecorderPort`."""

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
    ) -> None: ...


class EmbeddingIndexingService:
    def __init__(
        self,
        *,
        assets: AssetRepositoryPort,
        blob_refs: BlobRefCatalogPort,
        resolver: BlobPathResolverPort,
        provider: EmbeddingVectorProviderPort | SpaceEmbeddingProviderPort,
        index: EmbeddingVectorIndexPort | ChunkVectorIndexPort,
        manifest: ManifestJournalPort,
        clock: ClockPort,
        text_catalog: EmbeddingTextCatalogPort | None = None,
        index_recorder: EmbeddingIndexRecorderPort | None = None,
        chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
        max_chunks: int = MAX_CHUNKS_PER_ASSET,
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ) -> None:
        self._assets = assets
        self._blob_refs = blob_refs
        self._resolver = resolver
        self._provider = provider
        self._index = index
        self._manifest = manifest
        self._clock = clock
        self._text_catalog = text_catalog
        self._index_recorder = index_recorder
        self._chunk_tokens = chunk_tokens
        self._max_chunks = max_chunks
        self._batch_size = batch_size

    async def process_asset_embedding(self, asset_id: str) -> EmbeddingRecord | None:
        asset = await self._assets.get(asset_id)
        if asset is None:
            raise AssetNotFoundError(asset_id)
        if not asset.ai_indexing_allowed:
            LOGGER.info(
                "Skipped embedding of asset %s (origin %s): only this device's own files are indexed", asset.id, asset.origin
            )
            return None

        pending_asset = await self._mark_embedding_pending(asset)
        space: EmbeddingSpace | None = None
        chunk_vectors: tuple[ChunkVector, ...] = ()
        try:
            if not await self._provider.is_enabled():
                await self._mark_indexed(pending_asset)
                return None

            if isinstance(self._provider, SpaceEmbeddingProviderPort):
                record, vector, chunk_vectors, space = await self._embed_chunks(self._provider, pending_asset)
            else:
                original_ref = await self._blob_refs.latest_for_asset(asset.id, BlobKind.ORIGINAL)
                if original_ref is None:
                    raise AssetNotFoundError(asset_id)
                source_path = self._resolver.resolve(original_ref)
                record, vector = await self._embed_asset(self._provider, pending_asset, source_path)
                await self._write_vector(record, vector)
            await self._mark_indexed(pending_asset)
            payload: dict[str, object] = {
                "asset_id": asset.id,
                "embedding_id": record.id,
                "provider": record.provider,
                "dimensions": record.dimensions,
            }
            if space is not None:
                payload["space_id"] = space.id
                payload["chunks"] = len(chunk_vectors)
            await self._manifest.append(
                type=ManifestEventType.EMBEDDING_INDEXED,
                entity_type=ManifestEntityType.ASSET,
                entity_id=asset.id,
                payload=payload,
            )
        except WorkBudgetExceeded:
            raise  # requeued by the worker; the asset stays pending, not failed
        except Exception:
            await self._mark_partial_failure(pending_asset)
            raise
        await self._record_index(record, vector, space, chunk_vectors)
        return record

    # Smart search spaces: chunks + document prefix + batches of 8 ---------------------

    async def _embed_chunks(
        self, provider: SpaceEmbeddingProviderPort, asset: Asset
    ) -> tuple[EmbeddingRecord, Vector, tuple[ChunkVector, ...], EmbeddingSpace]:
        chunks = await self._chunks_for_asset(asset)
        vectors: list[Vector] = []
        for batch in batched([chunk.text for chunk in chunks], self._batch_size):
            check_safe_boundary()
            vectors.extend(await provider.embed_documents(batch, title=asset.filename))
        if len(vectors) != len(chunks):
            raise ValidationFailedError("The embedding provider returned a wrong number of vectors", {"asset_id": asset.id})
        space = provider.space  # after embedding: the runtime may have just started the status's space
        chunk_vectors = tuple(
            ChunkVector(chunk_no=chunk.chunk_no, page=chunk.page, vector=vector)
            for chunk, vector in zip(chunks, vectors, strict=True)
        )
        asset_vector = _asset_vector(vectors, space.dims)
        record = _space_record(asset.id, space, len(chunk_vectors))
        if isinstance(self._index, ChunkVectorIndexPort):
            await self._index.index_chunk_vectors(space.id, record, chunk_vectors)
        else:
            await self._index.index_embedding_vector(record, asset_vector)
        return record, asset_vector, chunk_vectors, space

    async def _chunks_for_asset(self, asset: Asset) -> tuple[TextChunk, ...]:
        """Images in v1: OCR text plus metadata as text (pixels only for multimodal spaces, Stage 26)."""
        indexed = await self._indexed_text(asset)
        metadata = _asset_metadata_text(asset)
        if asset.kind == AssetKind.IMAGE:
            text = "\n".join(part for part in (indexed, metadata) if part)
        else:
            text = indexed or metadata
        chunks = chunk_text(text, max_tokens=self._chunk_tokens, max_chunks=self._max_chunks) if text.strip() else ()
        if not chunks:
            raise ValidationFailedError("No text is available for embedding", {"asset_id": asset.id})
        return chunks

    async def _indexed_text(self, asset: Asset) -> str:
        if self._text_catalog is None:
            return ""
        return (await self._text_catalog.text_for_asset(asset.id) or "").strip()

    # Pre-Stage-24 providers ------------------------------------------------------------

    async def _write_vector(self, record: EmbeddingRecord, vector: Vector) -> None:
        index = self._index
        if isinstance(index, ChunkVectorIndexPort):
            if not hasattr(index, "index_embedding_vector"):
                raise ValidationFailedError(
                    "This vector index needs a smart search provider", {"asset_id": record.asset_id}
                )
            index = cast(EmbeddingVectorIndexPort, index)
        await index.index_embedding_vector(record, vector)

    async def _embed_asset(
        self, provider: EmbeddingVectorProviderPort, asset: Asset, source_path: Path
    ) -> tuple[EmbeddingRecord, Vector]:
        if asset.kind == AssetKind.IMAGE:
            return await provider.embed_image(asset.id, source_path)

        text = await self._text_for_asset(asset)
        if not text.strip():
            raise ValidationFailedError("No text is available for embedding", {"asset_id": asset.id})
        return await provider.embed_text(asset.id, text)

    async def _text_for_asset(self, asset: Asset) -> str:
        if self._text_catalog is not None:
            indexed_text = await self._text_catalog.text_for_asset(asset.id)
            if indexed_text:
                return indexed_text
        return _asset_metadata_text(asset)

    # Shared ------------------------------------------------------------------------------

    async def _record_index(
        self,
        record: EmbeddingRecord,
        vector: Vector,
        space: EmbeddingSpace | None,
        chunks: Sequence[ChunkVector] = (),
    ) -> None:
        """Publish the embedding to other devices (`asset_index` op); sync failures never fail indexing.

        Pre-Stage-24 providers (`mock`) publish one vector in their legacy space (`legacy:<provider>/<dims>`)."""
        if self._index_recorder is None:
            return
        try:
            if space is None:
                await self._index_recorder.record_embedding(
                    record.asset_id,
                    provider=record.provider,
                    dimensions=record.dimensions,
                    vector=vector,
                    space=legacy_space_id(record.provider, record.dimensions),
                )
            else:
                ordered = sorted(chunks, key=lambda chunk: chunk.chunk_no)
                await self._index_recorder.record_embedding(
                    record.asset_id,
                    provider=record.provider,
                    dimensions=record.dimensions,
                    vector=vector,
                    space=space.id,
                    chunks=[chunk.vector for chunk in ordered] or None,
                    pages=[chunk.page for chunk in ordered] or None,
                )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not queue the embedding for sync: %s", exc.__class__.__name__)

    async def _mark_embedding_pending(self, asset: Asset) -> Asset:
        if asset.processing_state in {
            ProcessingState.EMBEDDING_PENDING,
            ProcessingState.EMBEDDING_READY,
            ProcessingState.INDEXED,
        }:
            return asset
        pending = asset.transition_to(ProcessingState.EMBEDDING_PENDING, self._clock.now())
        await self._assets.save(pending)
        return pending

    async def _mark_indexed(self, asset: Asset) -> None:
        if asset.processing_state == ProcessingState.INDEXED:
            return
        await self._assets.save(asset.transition_to(ProcessingState.INDEXED, self._clock.now()))

    async def _mark_partial_failure(self, asset: Asset) -> None:
        if asset.processing_state == ProcessingState.FAILED_PARTIAL:
            return
        await self._assets.save(asset.transition_to(ProcessingState.FAILED_PARTIAL, self._clock.now()))


def _space_record(asset_id: str, space: EmbeddingSpace, chunks: int) -> EmbeddingRecord:
    digest = hashlib.sha1(f"{space.id}:{asset_id}".encode("utf-8")).hexdigest()
    return EmbeddingRecord(
        id=f"emb_{digest[:24]}",
        asset_id=asset_id,
        provider=space.model_id,
        vector_ref=f"chunks:{chunks}",
        dimensions=space.dims,
    )


def _asset_vector(vectors: Sequence[Vector], dims: int) -> Vector:
    """One vector per asset for sync and pre-chunk indexes: the normalised mean of its chunks."""
    if len(vectors) == 1:
        return vectors[0]
    mean = [math.fsum(column) / len(vectors) for column in zip(*vectors, strict=True)]
    try:
        return truncate_and_renormalize(mean, dims)
    except InvalidEmbeddingSpaceError:
        return vectors[0]


def _asset_metadata_text(asset: Asset) -> str:
    parts = [asset.filename, asset.metadata.original_filename, asset.metadata.mime_type]
    if asset.metadata.exif:
        parts.append(json.dumps(dict(asset.metadata.exif), ensure_ascii=False, sort_keys=True))
    return " ".join(part for part in parts if part)
