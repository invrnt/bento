"""Explicit `asset_index` ops: OCR text and embeddings travel to peers so they never re-run OCR/embeddings.

Size cap (architecture § Batches): an `asset_index` op whose fields exceed `MAX_INDEX_OP_BYTES` of JSON has its
`ocr_text` cut to `MAX_INDEX_TEXT_BYTES` and its `pdf_pages` to `MAX_INDEX_TEXT_BYTES` in total (pages kept in
order, the last one cut, later ones left out), measured as encoded JSON. Peers then index the first part of a
very long document only; the device that ran OCR keeps its full local index.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from bento.application.sync.codec import encode_vector
from bento.application.sync.state import CAPTURE
from bento.domain.sync import SyncEntity, SyncOperation, SyncOpKind
from bento.domain.vault import canonical_json
from bento.ports.sync import HlcSourcePort, SyncOutboxPort, SyncStateRepositoryPort

LOGGER = logging.getLogger("bento.sync.asset_index")

KIB = 1024
MAX_INDEX_OP_BYTES = 1024 * KIB
"""`asset_index` fields larger than this (canonical JSON) are cut down before they are recorded or published."""
MAX_INDEX_TEXT_BYTES = 512 * KIB
"""Encoded JSON budget of `ocr_text`, and separately of all `pdf_pages`, once a field set is cut down."""


def ocr_fields(*, ocr_text: str, pdf_pages: Sequence[tuple[int, str]], language: str | None) -> dict[str, Any]:
    return fit_index_fields(
        {
            "ocr_text": ocr_text,
            "pdf_pages": [{"page": int(page), "text": text} for page, text in pdf_pages],
            "language": language,
        }
    )


def fit_index_fields(fields: Mapping[str, Any], *, max_bytes: int = MAX_INDEX_OP_BYTES) -> dict[str, Any]:
    """`asset_index` fields that fit the sync op cap: OCR text beyond the text budget is left out."""
    fitted = dict(fields)
    if len(canonical_json(fitted)) <= max_bytes:
        return fitted
    budget = min(MAX_INDEX_TEXT_BYTES, max_bytes // 2)
    if isinstance(fitted.get("ocr_text"), str):
        fitted["ocr_text"] = _cut_text(fitted["ocr_text"], budget)
    if isinstance(fitted.get("pdf_pages"), list):
        fitted["pdf_pages"] = _cut_pages(fitted["pdf_pages"], budget)
    LOGGER.info("Cut the OCR text of an asset_index op to the sync size cap")
    return fitted


def _encoded_size(value: Any) -> int:
    return len(canonical_json(value))


def _cut_text(text: str, budget: int) -> str:
    """Longest prefix whose JSON string (quotes included) takes at most `budget` bytes."""
    if _encoded_size(text) <= budget:
        return text
    low, high = 0, min(len(text), budget)
    while low < high:
        middle = (low + high + 1) // 2
        if _encoded_size(text[:middle]) <= budget:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def _cut_pages(pages: list[Any], budget: int) -> list[Any]:
    kept: list[Any] = []
    used = 2  # the list brackets
    for page in pages:
        size = _encoded_size(page) + (1 if kept else 0)
        if used + size <= budget:
            kept.append(page)
            used += size
            continue
        if isinstance(page, dict) and isinstance(page.get("text"), str):
            empty = {**page, "text": ""}
            room = budget - used - (_encoded_size(empty) + (1 if kept else 0))
            if room > 0:
                kept.append({**page, "text": _cut_text(page["text"], room + 2)})
        break
    return kept


def embedding_fields(*, provider: str, dimensions: int, vector: Sequence[float]) -> dict[str, Any]:
    return {"embedding": {"provider": provider, "dimensions": int(dimensions), "vector_b64_f32": encode_vector(vector)}}


class AssetIndexRecorder:
    """`AssetIndexRecorderPort` over the outbox. A no-op until the vault is ready on this device."""

    def __init__(self, *, outbox: SyncOutboxPort, hlc: HlcSourcePort, state: SyncStateRepositoryPort) -> None:
        self._outbox = outbox
        self._hlc = hlc
        self._state = state

    async def record_ocr(
        self, asset_id: str, *, ocr_text: str, pdf_pages: Sequence[tuple[int, str]], language: str | None = None
    ) -> None:
        await self._record(asset_id, ocr_fields(ocr_text=ocr_text, pdf_pages=pdf_pages, language=language))

    async def record_embedding(self, asset_id: str, *, provider: str, dimensions: int, vector: Sequence[float]) -> None:
        await self._record(asset_id, embedding_fields(provider=provider, dimensions=dimensions, vector=vector))

    async def _record(self, asset_id: str, fields: dict[str, Any]) -> None:
        device_id = await self._device_id()
        if device_id is None:
            return
        fields = fit_index_fields(fields)
        operation = SyncOperation(
            op_id=str(uuid.uuid4()),
            hlc=await self._hlc.next(),
            device_id=device_id,
            entity=SyncEntity.ASSET_INDEX,
            entity_id=asset_id,
            kind=SyncOpKind.UPSERT,
            fields=fields,
        )
        await self._outbox.record(operation)

    async def _device_id(self) -> str | None:
        raw = await self._state.get_value(CAPTURE)
        if raw is None:
            return None
        try:
            device_id = json.loads(raw).get("device_id")
        except (ValueError, AttributeError):
            return None
        return device_id if isinstance(device_id, str) and device_id else None
