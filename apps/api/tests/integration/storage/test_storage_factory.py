from __future__ import annotations

from pathlib import Path

import pytest

from bento.adapters.storage.local_blob_store import LocalBlobStoreAdapter
from bento.infrastructure.settings import Settings
from bento.infrastructure.storage import create_blob_store


@pytest.mark.parametrize("backend", ["local", "telegram", "fake"])
def test_ingestion_blob_store_is_always_local(tmp_path: Path, backend: str) -> None:
    settings = Settings(storage_backend=backend, data_dir=str(tmp_path))

    blob_store = create_blob_store(settings)

    assert isinstance(blob_store, LocalBlobStoreAdapter)
