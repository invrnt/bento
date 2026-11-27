from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from bento.domain.errors import ValidationFailedError
from bento.domain.indexing import ExtractedText, normalized_mime_type
from bento.ports.providers import TextExtractorPort


class CompositeTextExtractor:
    """Routes each MIME type to the first extractor that supports it."""

    def __init__(self, extractors: Sequence[TextExtractorPort]) -> None:
        self._extractors = tuple(extractors)

    def supports(self, mime_type: str) -> bool:
        return any(extractor.supports(mime_type) for extractor in self._extractors)

    async def extract(
        self, source_path: Path, mime_type: str, *, checkpoint: Callable[[], None] | None = None
    ) -> ExtractedText:
        for extractor in self._extractors:
            if extractor.supports(mime_type):
                return await extractor.extract(source_path, mime_type, checkpoint=checkpoint)
        raise ValidationFailedError("No text extractor for this file type", {"mime_type": normalized_mime_type(mime_type)})
