"""Thumbnails, previews, PDF pages, and metadata through the `MediaTools` bridge (ImageDecoder,
MediaMetadataRetriever, PdfRenderer, ExifInterface). Pillow (`LocalMediaGenerator`) is the fallback for images
the system cannot decode; there is no ffmpeg or pypdfium2 on Android."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bento.adapters.android.bridge import BridgeUnsupportedError, call_json
from bento.adapters.media.generator import LocalMediaGenerator
from bento.adapters.media.generator import _generated_file as generated_file
from bento.adapters.ocr.pdf import PDFPageRender
from bento.application.media.service import GeneratedMediaFile
from bento.domain.assets import Asset, AssetKind
from bento.domain.errors import UnsupportedMediaTypeError
from bento.domain.storage import BlobKind

JPEG_QUALITY = 85
# (label, max side, kind). Grids ask for 256 and 1024 (`?size=`); 512 is derived on demand by the API.
IMAGE_OUTPUTS = (("thumb-sm", 256, BlobKind.THUMBNAIL), ("thumb-lg", 1024, BlobKind.THUMBNAIL), ("preview", 1600, BlobKind.PREVIEW))
VIDEO_OUTPUTS = (("video-thumb-sm", 256, BlobKind.THUMBNAIL), ("video-thumb-lg", 1024, BlobKind.THUMBNAIL))
PDF_OUTPUTS = (("pdf-thumb", 512, BlobKind.THUMBNAIL), ("pdf-preview", 1600, BlobKind.PREVIEW))
VIDEO_FRAME_AT_MS = 1000
OCR_PAGE_MAX_SIDE = 2000
OCR_MAX_PAGES = 50


class BridgeMediaGenerator:
    """`MediaGeneratorPort` (`application/media/service.py`) on the `MediaTools` bridge."""

    def __init__(self, bridge: Any, cache_dir: Path | str, *, fallback: LocalMediaGenerator | None = None) -> None:
        self._bridge = bridge
        self._cache_dir = Path(cache_dir)
        self._fallback = fallback or LocalMediaGenerator(self._cache_dir)

    async def generate(self, asset: Asset, source_path: Path) -> tuple[GeneratedMediaFile, ...]:
        if asset.kind == AssetKind.IMAGE:
            try:
                return await asyncio.to_thread(self._images, asset, source_path)
            except BridgeUnsupportedError:
                return await self._pillow(asset, source_path)
        if asset.kind == AssetKind.VIDEO:
            return await asyncio.to_thread(self._video, asset, source_path)
        if asset.kind == AssetKind.PDF:
            return await asyncio.to_thread(self._pdf, asset, source_path)
        raise UnsupportedMediaTypeError(asset.metadata.mime_type)

    async def cleanup(self, generated_files: tuple[GeneratedMediaFile, ...]) -> None:
        await self._fallback.cleanup(generated_files)

    async def _pillow(self, asset: Asset, source_path: Path) -> tuple[GeneratedMediaFile, ...]:
        try:
            return await self._fallback.generate(asset, source_path)
        except RuntimeError:  # Pillow missing from this build
            raise UnsupportedMediaTypeError(asset.metadata.mime_type) from None

    def _images(self, asset: Asset, source_path: Path) -> tuple[GeneratedMediaFile, ...]:
        target = self._target_dir(asset.id)
        generated = []
        for label, max_side, kind in IMAGE_OUTPUTS:
            output = target / f"{label}.jpg"
            size = call_json(self._bridge, "thumbnail", str(source_path), str(output), max_side, JPEG_QUALITY, "jpeg")
            generated.append(_file(output, kind, f"{asset.id}-{label}.jpg", size))
        return tuple(generated)

    def _video(self, asset: Asset, source_path: Path) -> tuple[GeneratedMediaFile, ...]:
        target = self._target_dir(asset.id)
        generated = []
        for label, max_side, kind in VIDEO_OUTPUTS:
            output = target / f"{label}.jpg"
            size = call_json(self._bridge, "videoFrame", str(source_path), str(output), max_side, JPEG_QUALITY, VIDEO_FRAME_AT_MS)
            generated.append(_file(output, kind, f"{asset.id}-{label}.jpg", size))
        return tuple(generated)

    def _pdf(self, asset: Asset, source_path: Path) -> tuple[GeneratedMediaFile, ...]:
        target = self._target_dir(asset.id)
        generated = []
        for label, max_side, kind in PDF_OUTPUTS:
            output = target / f"{label}.jpg"
            size = call_json(self._bridge, "pdfPage", str(source_path), str(output), 0, max_side)
            generated.append(_file(output, kind, f"{asset.id}-{label}.jpg", size))
        return tuple(generated)

    def _target_dir(self, asset_id: str) -> Path:
        target = self._cache_dir / asset_id
        target.mkdir(parents=True, exist_ok=True)
        return target


class BridgePDFPageRenderer:
    """`PDFPageRendererPort` for OCR: every page (up to `max_pages`) rendered by `PdfRenderer`."""

    def __init__(self, bridge: Any, output_dir: Path | str, *, max_pages: int = OCR_MAX_PAGES) -> None:
        self._bridge = bridge
        self._output_dir = Path(output_dir)
        self._max_pages = max_pages

    async def render_pages(self, *, asset_id: str, source_path: Path) -> tuple[PDFPageRender, ...]:
        return await asyncio.to_thread(self._render, asset_id, source_path)

    def _render(self, asset_id: str, source_path: Path) -> tuple[PDFPageRender, ...]:
        target = self._output_dir / asset_id
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        renders: list[PDFPageRender] = []
        page_count = 1
        index = 0
        while index < min(page_count, self._max_pages):
            output = target / f"page-{index + 1:04d}.jpg"
            info = call_json(self._bridge, "pdfPage", str(source_path), str(output), index, OCR_PAGE_MAX_SIDE)
            page_count = _int(info.get("page_count") if isinstance(info, dict) else None) or 1
            renders.append(PDFPageRender(page_number=index + 1, image_path=output))
            index += 1
        return tuple(renders)


@dataclass(frozen=True, slots=True)
class MediaMetadata:
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    taken_at: str | None = None
    orientation: int | None = None
    exif: dict[str, object] | None = None


class BridgeMediaMetadataReader:
    """`metadata(source, mime)`: dimensions, duration, capture time, and EXIF summary of one file."""

    def __init__(self, bridge: Any) -> None:
        self._bridge = bridge

    async def read(self, source: str, mime_type: str) -> MediaMetadata:
        data = await asyncio.to_thread(call_json, self._bridge, "metadata", source, mime_type)
        if not isinstance(data, dict):
            return MediaMetadata()
        exif = data.get("exif")
        taken_at = data.get("taken_at")
        return MediaMetadata(
            width=_int(data.get("width")),
            height=_int(data.get("height")),
            duration_ms=_int(data.get("duration_ms")),
            taken_at=str(taken_at) if isinstance(taken_at, str) and taken_at else None,
            orientation=_int(data.get("orientation")),
            exif={key: value for key, value in exif.items() if value is not None} if isinstance(exif, dict) else None,
        )


def _file(path: Path, kind: BlobKind, filename: str, size: object) -> GeneratedMediaFile:
    dimensions = size if isinstance(size, dict) else {}
    if not path.is_file():
        raise BridgeUnsupportedError("bridge produced no output")
    return generated_file(
        path=path,
        kind=kind,
        filename=filename,
        mime_type="image/jpeg",
        width=_int(dimensions.get("width")),
        height=_int(dimensions.get("height")),
    )


def _int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)
