from __future__ import annotations

from pathlib import Path
from typing import Protocol


class AssetContentPort(Protocol):
    """Plaintext access to an asset's original, from the local cache or downloaded on demand."""

    async def materialize_original(self, asset_id: str) -> Path:
        """Local plaintext path of the original (cached; callers must not delete it)."""
        ...

    async def read_range(self, asset_id: str, start: int, length: int) -> bytes: ...
