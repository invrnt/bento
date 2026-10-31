from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from bento.domain.storage import BlobKind, StorageBackend
from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app
from tests.integration.storage_pipeline.support import (
    JobRunner,
    RemoteSwitch,
    migrated_data_dir,
    pipeline_for,
    vault_remote_store,
)

CONTENT = bytes(range(256)) * 600  # 153,600 bytes: many 4 KiB segments across several 8 KiB parts


def _client(tmp_path: Path, *, remote: bool = True, threshold: int = 0):
    data_dir = migrated_data_dir(tmp_path)
    store = asyncio.run(vault_remote_store(tmp_path, part_size=8192)) if remote else None
    components = pipeline_for(data_dir, RemoteSwitch(store), full_fetch_threshold=threshold)
    app = create_app(Settings(data_dir=str(data_dir), storage_backend="fake"))
    app.state.storage_pipeline = components
    return TestClient(app), components, store


def _upload(client: TestClient, name: str = "clip.mp4", content: bytes = CONTENT, mime: str = "video/mp4") -> str:
    response = client.post("/api/assets/upload", files={"file": (name, content, mime)})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _make_remote_only(components, asset_id: str) -> str:
    asyncio.run(JobRunner(components).run_all())
    ref = asyncio.run(components.blob_refs.latest_for_asset(asset_id, BlobKind.ORIGINAL))
    assert ref.backend == StorageBackend.TELEGRAM
    asyncio.run(components.cache.remove((ref.id,)))
    assert asyncio.run(components.content.local_path(ref)) is None
    return ref.id


def test_content_serves_local_files_with_ranges_and_headers(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path, remote=False)
    asset_id = _upload(client, "nota.txt", b"0123456789abcdef", "text/plain")
    url = f"/api/assets/{asset_id}/content"

    full = client.get(url)
    assert full.status_code == 200 and full.content == b"0123456789abcdef"
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-type"].startswith("text/plain")
    assert full.headers["content-disposition"].startswith('inline; filename="nota.txt"')
    assert full.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in full.headers["content-security-policy"]

    part = client.get(url, headers={"Range": "bytes=2-5"})
    assert part.status_code == 206 and part.content == b"2345"
    assert part.headers["content-range"] == "bytes 2-5/16" and part.headers["content-length"] == "4"
    assert client.get(url, headers={"Range": "bytes=-3"}).content == b"def"
    assert client.get(url, headers={"Range": "bytes=10-"}).content == b"abcdef"
    assert client.get(url, headers={"Range": "bytes=15-99"}).headers["content-range"] == "bytes 15-15/16"
    assert client.get(url, headers={"Range": "bytes=0-1,4-5"}).status_code == 200

    for invalid in ("bytes=16-", "bytes=9-3", "bytes=x-1", "bytes=-0"):
        response = client.get(url, headers={"Range": invalid})
        assert response.status_code == 416, invalid
        assert response.headers["content-range"] == "bytes */16"

    head = client.head(url, headers={"Range": "bytes=0-3"})
    assert head.status_code == 206 and head.content == b"" and head.headers["content-length"] == "4"
    assert client.get("/api/assets/asset_missing/content").status_code == 404


def test_remote_only_content_streams_ranges_from_the_vault(tmp_path: Path) -> None:
    client, components, store = _client(tmp_path)
    asset_id = _upload(client)
    _make_remote_only(components, asset_id)
    url = f"/api/assets/{asset_id}/content"

    for start, end in ((0, 0), (4095, 4096), (8190, 8200), (100_000, 140_000), (len(CONTENT) - 7, len(CONTENT) - 1)):
        response = client.get(url, headers={"Range": f"bytes={start}-{end}"})
        assert response.status_code == 206
        assert response.content == CONTENT[start : end + 1], (start, end)
        assert response.headers["content-range"] == f"bytes {start}-{end}/{len(CONTENT)}"
        assert response.headers["content-type"] == "video/mp4"
    assert store.range_reads and store.downloads == []

    whole = client.get(url)
    assert whole.status_code == 200 and whole.content == CONTENT
    assert client.get(url, headers={"Range": f"bytes={len(CONTENT)}-"}).status_code == 416


def test_download_and_thumbnail_fetch_remote_blobs_lazily_into_the_cache(tmp_path: Path) -> None:
    client, components, store = _client(tmp_path, threshold=32 * 1024 * 1024)
    asset_id = _upload(client, "informe.pdf", b"%PDF-1.4 " + CONTENT, "application/pdf")
    blob_id = _make_remote_only(components, asset_id)

    download = client.get(f"/api/assets/{asset_id}/download")
    assert download.status_code == 200 and download.content == b"%PDF-1.4 " + CONTENT
    assert download.headers["cache-control"] == "no-store"
    assert store.downloads == [blob_id]
    cached = asyncio.run(components.cache.lookup(blob_id))
    assert cached is not None and cached.is_relative_to(components.cache.directory)

    assert client.get(f"/api/assets/{asset_id}/content").content == b"%PDF-1.4 " + CONTENT
    assert store.downloads == [blob_id]  # served from the cache the second time

    assert client.get(f"/api/assets/{asset_id}/thumbnail").status_code == 404
    switch_off = components.remote
    switch_off.store = None
    asyncio.run(components.cache.remove((blob_id,)))
    unavailable = client.get(f"/api/assets/{asset_id}/download")
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "storage_unavailable"
