"""`OCRProviderPort` on the `Ocr` bridge (ML Kit Text Recognition v2, bundled Latin model, on-device)."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from bento.adapters.android.bridge import BridgeError, call, call_json
from bento.domain.indexing import OCRBlock

OCR_MAX_SIDE = 2048


class MLKitOCRAdapter:
    """Same result shape as `RapidOCRAdapter`: one `OCRBlock` per recognized line, with its confidence."""

    def __init__(self, bridge: Any, *, max_side: int = OCR_MAX_SIDE) -> None:
        self._bridge = bridge
        self._max_side = max_side
        self._available: bool | None = None

    async def is_enabled(self) -> bool:
        if self._available is None:
            try:
                self._available = bool(await asyncio.to_thread(call, self._bridge, "available"))
            except BridgeError:
                return False
        return self._available

    async def extract_text(self, asset_id: str, source_ref: str) -> tuple[OCRBlock, ...]:
        result = await asyncio.to_thread(call_json, self._bridge, "recognize", source_ref, self._max_side)
        lines = result.get("lines") if isinstance(result, dict) else None
        if not isinstance(lines, list) or not lines:
            text = str(result.get("text") or "") if isinstance(result, dict) else ""
            lines = [{"text": line} for line in text.splitlines()]
        blocks = []
        for index, line in enumerate(lines):
            if not isinstance(line, dict):
                continue
            text = str(line.get("text") or "")
            if not text.strip():
                continue
            confidence = line.get("confidence")
            blocks.append(
                OCRBlock(
                    id=_block_id(asset_id, source_ref, index),
                    asset_id=asset_id,
                    text=text,
                    confidence=float(confidence) if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else None,
                )
            )
        return tuple(blocks)


def _block_id(asset_id: str, source_ref: str, index: int) -> str:
    digest = hashlib.sha1(f"{asset_id}:{source_ref}:{index}".encode("utf-8")).hexdigest()[:16]
    return f"ocr_{digest}"
