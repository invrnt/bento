"""The text layer of PDFs through pypdfium2: page by page, capped, never rendered (no OCR)."""

from __future__ import annotations

import asyncio
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bento.domain.errors import ValidationFailedError
from bento.domain.indexing import (
    MAX_DOCUMENT_TEXT_CHARS,
    MAX_TEXT_LAYER_PAGES,
    ExtractedPage,
    ExtractedText,
    cap_extracted_pages,
    normalized_mime_type,
)

PDF_MIME_TYPE = "application/pdf"


class Pypdfium2TextLayerExtractor:
    """pypdfium2 4.x: `PdfDocument(path)`, `len(doc)`, `doc[i]`, `page.get_textpage().get_text_bounded()` (the whole
    page; 4.30 redirects a default `get_text_range()` call to it anyway), `PdfiumError` for unreadable files."""

    def __init__(self, *, max_pages: int = MAX_TEXT_LAYER_PAGES, max_chars: int = MAX_DOCUMENT_TEXT_CHARS) -> None:
        if max_pages < 1 or max_chars < 1:
            raise ValueError("limits must be positive")
        self._max_pages = max_pages
        self._max_chars = max_chars

    def supports(self, mime_type: str) -> bool:
        return normalized_mime_type(mime_type) == PDF_MIME_TYPE

    async def extract(
        self, source_path: Path, mime_type: str, *, checkpoint: Callable[[], None] | None = None
    ) -> ExtractedText:
        if not self.supports(mime_type):
            raise ValidationFailedError("Not a PDF", {"mime_type": normalized_mime_type(mime_type)})
        return await asyncio.to_thread(self._extract_sync, source_path, checkpoint)

    def _extract_sync(self, source_path: Path, checkpoint: Callable[[], None] | None) -> ExtractedText:
        import pypdfium2 as pdfium

        _require_regular_file(source_path)
        try:
            document = pdfium.PdfDocument(str(source_path))
        except pdfium.PdfiumError as exc:
            if "password" in str(exc).lower():
                return ExtractedText()  # encrypted: no readable text layer, not a broken file
            raise ValidationFailedError("The PDF could not be read") from exc
        pages: list[ExtractedPage] = []
        chars = 0
        truncated = False
        try:
            total = len(document)
            readable = min(total, self._max_pages)
            truncated = total > readable
            for index in range(readable):
                if checkpoint is not None:
                    checkpoint()
                text = _page_text(document, index, pdfium.PdfiumError)
                pages.append(ExtractedPage(text=text, page_number=index + 1))
                chars += len(text)
                if chars >= self._max_chars:
                    truncated = truncated or index + 1 < total
                    break
        finally:
            document.close()
        kept, cut = cap_extracted_pages(pages, max_chars=self._max_chars)
        visible = tuple(page for page in kept if page.text.strip())
        return ExtractedText(pages=visible, pages_read=len(pages), truncated=truncated or cut)


def _page_text(document: Any, index: int, error: type[Exception]) -> str:
    page = textpage = None
    try:
        page = document[index]
        textpage = page.get_textpage()
        raw = textpage.get_text_bounded()
    except error as exc:
        raise ValidationFailedError("A PDF page could not be read", {"page": index + 1}) from exc
    finally:
        if textpage is not None:
            textpage.close()
        if page is not None:
            page.close()
    return str(raw or "").replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")


def _require_regular_file(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ValidationFailedError("The file could not be opened for text extraction") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ValidationFailedError("Only regular files are read for text extraction")
