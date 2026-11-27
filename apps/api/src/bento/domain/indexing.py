from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IndexProviderState(StrEnum):
    DISABLED = "disabled"
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class OCRBlock:
    id: str
    asset_id: str
    text: str
    page_number: int | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingRecord:
    id: str
    asset_id: str
    provider: str
    vector_ref: str
    dimensions: int


@dataclass(frozen=True, slots=True)
class PDFPage:
    id: str
    asset_id: str
    page_number: int
    text: str | None = None


@dataclass(frozen=True, slots=True)
class VideoSegment:
    id: str
    asset_id: str
    start_ms: int
    end_ms: int


# Document text extraction (no OCR): plain text files and the text layer of PDFs -------------------------------

TEXT_EXTRACTION_MIME_TYPES = frozenset({"text/plain", "text/markdown", "text/csv", "application/pdf"})
"""MIME types whose text is read directly. Everything else (images, scanned pages) needs OCR."""
MAX_TEXT_FILE_BYTES = 4 * 1024 * 1024
"""Bytes read from a plain text file; the rest of a bigger file is not indexed."""
MAX_TEXT_LAYER_PAGES = 500
"""PDF pages whose text layer is read, first pages first."""
MAX_DOCUMENT_TEXT_CHARS = 2_000_000
"""Characters kept per document after extraction (FTS and the embedding text read from these)."""
MIN_TEXT_LAYER_CHARS_PER_PAGE = 16
"""Below this many non-blank characters per page on average, a PDF's text layer counts as near-empty (a scan
with page numbers or a stamp): OCR, when enabled, reads the pages instead."""


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    """Text read from a document without OCR. `page_number` is 1-based for PDFs and None for plain text."""

    text: str
    page_number: int | None = None


@dataclass(frozen=True, slots=True)
class ExtractedText:
    pages: tuple[ExtractedPage, ...] = ()
    pages_read: int = 0
    """Pages looked at (PDFs), including blank ones; 1 for a plain text file."""
    truncated: bool = False

    @property
    def text(self) -> str:
        return "\n".join(page.text for page in self.pages if page.text.strip())

    @property
    def visible_chars(self) -> int:
        return sum(len("".join(page.text.split())) for page in self.pages)

    @property
    def empty(self) -> bool:
        return self.visible_chars == 0


def normalized_mime_type(mime_type: str) -> str:
    """`Text/Plain; charset=utf-8` -> `text/plain`."""
    return mime_type.split(";", 1)[0].strip().lower()


def supports_text_extraction(mime_type: str) -> bool:
    return normalized_mime_type(mime_type) in TEXT_EXTRACTION_MIME_TYPES


def usable_text_layer(extracted: ExtractedText) -> bool:
    """Whether a PDF's text layer is real text rather than near-empty: then OCR is not needed for it."""
    if extracted.empty:
        return False
    return extracted.visible_chars >= MIN_TEXT_LAYER_CHARS_PER_PAGE * max(1, extracted.pages_read)


def cap_extracted_pages(pages: list[ExtractedPage], *, max_chars: int = MAX_DOCUMENT_TEXT_CHARS) -> tuple[tuple[ExtractedPage, ...], bool]:
    """Keep pages in order until `max_chars` characters; returns the kept pages and whether text was cut."""
    kept: list[ExtractedPage] = []
    budget = max_chars
    for page in pages:
        if budget <= 0:
            return tuple(kept), True
        if len(page.text) > budget:
            kept.append(ExtractedPage(text=page.text[:budget], page_number=page.page_number))
            return tuple(kept), True
        kept.append(page)
        budget -= len(page.text)
    return tuple(kept), False
