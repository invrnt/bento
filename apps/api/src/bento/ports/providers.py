from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from bento.domain.indexing import EmbeddingRecord, ExtractedText, OCRBlock
from bento.domain.smart_search import EmbeddingSpace, Vector


class OCRProviderPort(Protocol):
    async def is_enabled(self) -> bool: ...

    async def extract_text(self, asset_id: str, source_ref: str) -> tuple[OCRBlock, ...]: ...


class TextExtractorPort(Protocol):
    """Reads the text a document already contains (plain text files, a PDF's text layer); never OCR, never renders.

    Implementations cap what they read (`domain.indexing` limits), return an empty `ExtractedText` for files that
    hold no readable text (binary content, encrypted PDFs), and raise `ValidationFailedError` for files they cannot
    parse. `checkpoint` is called between pages: bounded worker runs stop there (`check_safe_boundary`)."""

    def supports(self, mime_type: str) -> bool: ...

    async def extract(
        self, source_path: Path, mime_type: str, *, checkpoint: Callable[[], None] | None = None
    ) -> ExtractedText: ...


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
