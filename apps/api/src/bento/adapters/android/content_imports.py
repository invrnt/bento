"""`ContentImportsPort` over the `ContentImports` bridge (`describe(handle)`, `adopt(handle): Int`)."""

from __future__ import annotations

import os
from typing import Any

from bento.adapters.android.bridge import BridgeError, call, call_json
from bento.ports.device import ContentDescription, ContentHandleError


class BridgeContentImports:
    def __init__(self, bridge: Any) -> None:
        self._bridge = bridge

    def describe(self, handle: int) -> ContentDescription:
        try:
            data = call_json(self._bridge, "describe", int(handle))
        except BridgeError as exc:
            raise ContentHandleError(exc.code) from None
        if not isinstance(data, dict):
            raise ContentHandleError("io")
        size = data.get("size_bytes")
        return ContentDescription(
            display_name=str(data.get("display_name") or ""),
            mime_type=str(data.get("mime_type") or "application/octet-stream"),
            size_bytes=int(size) if isinstance(size, int) and not isinstance(size, bool) and size >= 0 else None,
        )

    def adopt(self, handle: int) -> int:
        try:
            descriptor = int(call(self._bridge, "adopt", int(handle)))
        except BridgeError as exc:
            raise ContentHandleError(exc.code) from None
        except (TypeError, ValueError):
            raise ContentHandleError("io") from None
        if descriptor < 0:
            raise ContentHandleError("io")
        try:
            os.fstat(descriptor)
        except OSError:
            raise ContentHandleError("io") from None
        return descriptor
