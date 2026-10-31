from __future__ import annotations

from pathlib import Path

from bento.adapters.storage.local_blob_store import LocalBlobStoreAdapter
from bento.infrastructure.settings import Settings
from bento.ports.blob_store import BlobStorePort


def create_blob_store(settings: Settings) -> BlobStorePort:
    """The local blob store, for every storage backend.

    Ingestion is local-first; encrypted copies in the Telegram vault come from
    `bento.infrastructure.services.get_remote_blob_store`.
    """
    return LocalBlobStoreAdapter(_local_blob_root(settings))


def _local_blob_root(settings: Settings) -> Path:
    return Path(settings.data_dir) / "uploads"
