"""Explicit `asset_index` ops: OCR text and embeddings travel to peers so they never re-run OCR/embeddings."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from typing import Any

from bento.application.sync.codec import encode_vector
from bento.application.sync.state import CAPTURE
from bento.domain.sync import SyncEntity, SyncOperation, SyncOpKind
from bento.ports.sync import HlcSourcePort, SyncOutboxPort, SyncStateRepositoryPort

LOGGER = logging.getLogger("bento.sync.asset_index")


def ocr_fields(*, ocr_text: str, pdf_pages: Sequence[tuple[int, str]], language: str | None) -> dict[str, Any]:
    return {
        "ocr_text": ocr_text,
        "pdf_pages": [{"page": int(page), "text": text} for page, text in pdf_pages],
        "language": language,
    }


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
