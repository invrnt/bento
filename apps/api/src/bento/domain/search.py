from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from bento.domain.assets import ProcessingState


class SearchResultType(StrEnum):
    ASSET = "asset"
    FOLDER = "folder"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    PDF_PAGE = "pdf_page"
    OCR_BLOCK = "ocr_block"
    ALBUM = "album"


class SearchOrigin(StrEnum):
    """`GET /search?origin=`: how this device obtained the asset (`assets.origin`, device-local)."""

    DEVICE = "device"
    """Picked on this device (upload, share, backup)."""
    PEER = "peer"
    """Arrived through sync from another device of the account (which device is not recorded)."""
    TELEGRAM = "telegram"
    """Either Telegram origin below."""
    TELEGRAM_INBOX = "telegram_inbox"
    TELEGRAM_IMPORT = "telegram_import"


class MatchReason(StrEnum):
    """Machine-readable explanation codes of a hit (`SearchHit.match_reasons`), strongest first."""

    OCR_TEXT = "ocr_text"
    FILENAME = "filename"
    FOLDER_NAME = "folder_name"
    ALBUM = "album"
    SEMANTIC = "semantic"
    METADATA = "metadata"
    DOCUMENT_TYPE = "document_type"
    EXIF_DATE = "exif_date"
    """Matched the capture date (EXIF `DateTimeOriginal` or the camera roll's date taken)."""
    DATE = "date"
    """Matched the date the file was added (no capture date known)."""
    INDEXED_TEXT = "indexed_text"
    RECENT = "recent"


MATCH_REASON_ORDER: tuple[MatchReason, ...] = tuple(MatchReason)


@dataclass(frozen=True, slots=True)
class SearchSnippet:
    """A short excerpt of the matched text. `highlights` are `[start, end)` offsets into `text` in UTF-16 code
    units (what Kotlin and JavaScript strings index by)."""

    text: str
    highlights: tuple[tuple[int, int], ...]
    source: MatchReason


@dataclass(frozen=True, slots=True)
class SearchQuery:
    text: str
    result_type: SearchResultType | None = None
    folder_id: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    limit: int = 50
    cursor: str | None = None
    origin: SearchOrigin | None = None


@dataclass(frozen=True, slots=True)
class SearchFacet:
    type: SearchResultType
    count: int


@dataclass(frozen=True, slots=True)
class SearchHit:
    id: str
    type: SearchResultType
    title: str
    score: float
    reason: str
    asset_id: str | None = None
    subtitle: str | None = None
    thumbnail_url: str | None = None
    processing_state: ProcessingState | None = None
    match_reasons: tuple[MatchReason, ...] = ()
    snippet: SearchSnippet | None = None
    folder_id: str | None = None
    folder_name: str | None = None
    mime_type: str | None = None
    origin: SearchOrigin | None = None


@dataclass(frozen=True, slots=True)
class SearchResults:
    items: tuple[SearchHit, ...]
    facets: tuple[SearchFacet, ...]
    next_cursor: str | None


SNIPPET_RADIUS = 60


def build_snippet(text: str, tokens: tuple[str, ...], source: MatchReason, *, radius: int = SNIPPET_RADIUS) -> SearchSnippet | None:
    """The excerpt around the first token found (case-insensitive) with every token occurrence highlighted;
    `None` when no token occurs."""
    flat = " ".join(text.split())
    lowered = flat.casefold()
    if len(lowered) != len(flat):  # casefold changed lengths (e.g. "ß"): fall back to lower(), length-stable
        lowered = flat.lower()
        if len(lowered) != len(flat):
            return None
    needles = sorted({token.casefold() for token in tokens if token.strip()}, key=len, reverse=True)
    positions = [index for index in (lowered.find(needle) for needle in needles) if index >= 0]
    if not positions:
        return None
    first = min(positions)
    start = max(first - radius, 0)
    end = min(first + radius * 2, len(flat))
    if start > 0:
        space = flat.rfind(" ", 0, start + 1)
        start = space + 1 if space >= 0 and first - space <= radius * 2 else start
    if end < len(flat):
        space = flat.find(" ", end)
        end = space if 0 <= space - end <= 20 else end
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(flat) else ""
    excerpt = flat[start:end]
    lowered_excerpt = lowered[start:end]
    spans: list[tuple[int, int]] = []
    for needle in needles:
        cursor = lowered_excerpt.find(needle)
        while cursor >= 0:
            spans.append((cursor, cursor + len(needle)))
            cursor = lowered_excerpt.find(needle, cursor + len(needle))
    merged: list[tuple[int, int]] = []
    for span_start, span_end in sorted(spans):
        if merged and span_start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], span_end))
        else:
            merged.append((span_start, span_end))
    shown = prefix + excerpt + suffix
    offset = _utf16_length(prefix)
    highlights = tuple(
        (offset + _utf16_length(excerpt[:span_start]), offset + _utf16_length(excerpt[:span_end])) for span_start, span_end in merged
    )
    return SearchSnippet(text=shown, highlights=highlights, source=source)


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2
