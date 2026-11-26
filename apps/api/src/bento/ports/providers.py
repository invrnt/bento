from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from bento.domain.indexing import EmbeddingRecord, OCRBlock
from bento.domain.smart_search import EmbeddingSpace, Vector


class OCRProviderPort(Protocol):
    async def is_enabled(self) -> bool: ...

    async def extract_text(self, asset_id: str, source_ref: str) -> tuple[OCRBlock, ...]: ...


class EmbeddingProviderPort(Protocol):
    async def is_enabled(self) -> bool: ...

    async def embed_asset(self, asset_id: str, source_ref: str) -> EmbeddingRecord: ...

    # Smart search (Stage 23 contract). Vectors are already truncated to `space.dims`
    # and L2-normalised; the provider applies the model's query/document prefixes.

    @property
    def space(self) -> EmbeddingSpace: ...

    async def embed_query(self, text: str) -> Vector: ...

    async def embed_documents(self, texts: Sequence[str], *, title: str | None = None) -> tuple[Vector, ...]: ...

    async def embed_image(self, path: Path) -> Vector:
        """Raises `UnsupportedModalityError` when the space is text-only."""
        ...
