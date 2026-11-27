"""Plain text files (`text/plain`, `text/markdown`, `text/csv`): decode safely, read at most `MAX_TEXT_FILE_BYTES`."""

from __future__ import annotations

import asyncio
import codecs
import os
import stat
from collections.abc import Callable
from pathlib import Path

from bento.domain.errors import ValidationFailedError
from bento.domain.indexing import (
    MAX_DOCUMENT_TEXT_CHARS,
    MAX_TEXT_FILE_BYTES,
    ExtractedPage,
    ExtractedText,
    cap_extracted_pages,
    normalized_mime_type,
)

PLAIN_TEXT_MIME_TYPES = frozenset({"text/plain", "text/markdown", "text/csv"})
# Above this share of control bytes (NUL included) the content is binary or garbage, not text.
_MAX_CONTROL_RATIO = 0.05
_ALLOWED_CONTROLS = frozenset(b"\t\n\r\f\v\x1b")
_BOMS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)


class PlainTextExtractor:
    def __init__(self, *, max_bytes: int = MAX_TEXT_FILE_BYTES, max_chars: int = MAX_DOCUMENT_TEXT_CHARS) -> None:
        if max_bytes < 1 or max_chars < 1:
            raise ValueError("limits must be positive")
        self._max_bytes = max_bytes
        self._max_chars = max_chars

    def supports(self, mime_type: str) -> bool:
        return normalized_mime_type(mime_type) in PLAIN_TEXT_MIME_TYPES

    async def extract(
        self, source_path: Path, mime_type: str, *, checkpoint: Callable[[], None] | None = None
    ) -> ExtractedText:
        if not self.supports(mime_type):
            raise ValidationFailedError("Not a plain text file", {"mime_type": normalized_mime_type(mime_type)})
        data, truncated = await asyncio.to_thread(read_capped, source_path, self._max_bytes)
        text = decode_text(data, truncated=truncated)
        if text is None or not text.strip():
            return ExtractedText(pages_read=1, truncated=truncated)
        pages, cut = cap_extracted_pages([ExtractedPage(text=text)], max_chars=self._max_chars)
        return ExtractedText(pages=pages, pages_read=1, truncated=truncated or cut)


def read_capped(path: Path, max_bytes: int) -> tuple[bytes, bool]:
    """At most `max_bytes` of a regular file (symlinks, devices and FIFOs are refused), and whether it is longer."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValidationFailedError("The file could not be opened for text extraction") from exc
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValidationFailedError("Only regular files are read for text extraction")
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(max_bytes + 1)
    return data[:max_bytes], len(data) > max_bytes


def decode_text(data: bytes, *, truncated: bool = False) -> str | None:
    """Text from bytes of unknown encoding, or None when they are not text.

    A BOM wins (UTF-8/16/32). Otherwise UTF-8 strict (a sequence cut by the read cap is dropped), then
    Windows-1252, then Latin-1, which decodes anything. NULs are removed and newlines normalised to `\\n`."""
    if not data:
        return ""
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            body = data[len(bom) :]
            if truncated:
                body = _trim_partial(body, encoding)
            return _clean(body.decode(encoding, errors="replace"))
    if _looks_binary(data):
        return None
    try:
        return _clean(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        # Only a multi-byte sequence cut at the end by the cap is forgiven; anything else is not UTF-8.
        if truncated and exc.start >= len(data) - 3 and exc.reason == "unexpected end of data":
            return _clean(data[: exc.start].decode("utf-8"))
    for encoding in ("cp1252", "latin-1"):
        try:
            return _clean(data.decode(encoding))
        except UnicodeDecodeError:
            continue
    return None  # pragma: no cover - latin-1 decodes every byte


def _looks_binary(data: bytes) -> bool:
    sample = data[: 64 * 1024]
    controls = sum(1 for byte in sample if (byte < 0x20 or byte == 0x7F) and byte not in _ALLOWED_CONTROLS)
    return controls > len(sample) * _MAX_CONTROL_RATIO


def _trim_partial(body: bytes, encoding: str) -> bytes:
    unit = 4 if encoding.startswith("utf-32") else 2 if encoding.startswith("utf-16") else 1
    if unit > 1:
        return body[: len(body) - len(body) % unit]
    try:
        body.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.start >= len(body) - 3:
            return body[: exc.start]
    return body


def _clean(text: str) -> str:
    return text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
