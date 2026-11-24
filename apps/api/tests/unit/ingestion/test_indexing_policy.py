from __future__ import annotations

import asyncio
from pathlib import Path

from bento.application.ingestion import AssetIngestionService, IndexingPolicy, UploadedAssetFile
from bento.application.ingestion.metadata import ExtractedUploadMetadata
from bento.application.upload import UploadAssetCommand


class _Upload:
    def __init__(self) -> None:
        self.commands: list[UploadAssetCommand] = []

    async def execute(self, command: UploadAssetCommand):  # noqa: ANN201 - test double
        self.commands.append(command)

        class _Result:
            blob_ref = None

        return _Result()


class _Extractor:
    async def extract(self, source_path: Path, *, original_filename: str, declared_mime_type: str | None):
        return ExtractedUploadMetadata(
            filename=original_filename, mime_type="image/png", size_bytes=1, sha256="a" * 64, taken_at=None, exif=None
        )


class _BlobRefs:
    async def add(self, blob_ref) -> None: ...

    async def latest_for_asset(self, asset_id, kind):
        return None


def _ingest(policy: IndexingPolicy | None) -> UploadAssetCommand:
    upload = _Upload()
    service = AssetIngestionService(
        upload=upload,  # type: ignore[arg-type]
        blob_refs=_BlobRefs(),
        metadata_extractor=_Extractor(),
        indexing=policy,
    )
    asyncio.run(service.upload_file(UploadedAssetFile(source_path=Path("x.png"), original_filename="x.png")))
    return upload.commands[0]


def test_uploads_queue_index_jobs_from_the_configured_providers() -> None:
    command = _ingest(IndexingPolicy.from_providers(ocr_provider="mlkit", embeddings_provider="disabled"))
    assert command.ocr_enabled is True
    assert command.embeddings_enabled is False


def test_disabled_providers_queue_nothing() -> None:
    command = _ingest(IndexingPolicy.from_providers(ocr_provider="disabled", embeddings_provider="disabled"))
    assert (command.ocr_enabled, command.embeddings_enabled) == (False, False)
    assert _ingest(None).ocr_enabled is False
