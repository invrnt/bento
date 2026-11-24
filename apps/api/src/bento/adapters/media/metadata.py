from __future__ import annotations

import asyncio
import hashlib
import math
import mimetypes
import numbers
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bento.application.ingestion.metadata import ExtractedUploadMetadata, sanitize_filename


class LocalUploadMetadataExtractor:
    async def extract(
        self,
        source_path: Path,
        *,
        original_filename: str,
        declared_mime_type: str | None,
    ) -> ExtractedUploadMetadata:
        filename = sanitize_filename(original_filename)
        size_bytes, sha256, header = await asyncio.to_thread(_file_size_sha256_header, source_path)
        mime_type = _detect_mime_type(filename, declared_mime_type, header)
        taken_at: datetime | None = None
        exif: dict[str, Any] | None = None
        if mime_type.startswith("image/"):
            taken_at, exif = await asyncio.to_thread(_extract_image_exif, source_path)
        return ExtractedUploadMetadata(
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=sha256,
            taken_at=taken_at,
            exif=exif,
        )


def _file_size_sha256_header(path: Path) -> tuple[int, str, bytes]:
    digest = hashlib.sha256()
    size = 0
    header = b""
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            if not header:
                header = chunk[:512]
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest(), header


def _detect_mime_type(filename: str, declared_mime_type: str | None, header: bytes) -> str:
    sniffed = _sniff_mime_type(header)
    if sniffed is not None:
        return sniffed
    guessed, _ = mimetypes.guess_type(filename)
    if guessed:
        return guessed
    if declared_mime_type and declared_mime_type.strip() and declared_mime_type != "application/octet-stream":
        return declared_mime_type
    return "application/octet-stream"


def _sniff_mime_type(header: bytes) -> str | None:
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        major = header[8:12]
        if major in {b"avif", b"avis"}:
            return "image/avif"
        return "video/mp4"
    return None


def _extract_image_exif(source_path: Path) -> tuple[datetime | None, dict[str, Any] | None]:
    try:
        from PIL import ExifTags, Image
    except ImportError:
        return None, None

    try:
        with Image.open(source_path) as image:
            raw_exif = image.getexif()
            if not raw_exif:
                return None, None
            mapped: dict[str, Any] = {}
            # Camera fields (DateTimeOriginal, exposure, lens) live in the Exif sub-IFD, not in IFD0.
            entries = [
                (ExifTags.TAGS.get(key, str(key)), value)
                for key, value in (*raw_exif.items(), *raw_exif.get_ifd(ExifTags.IFD.Exif).items())
                if key not in (ExifTags.Base.ExifOffset, ExifTags.Base.GPSInfo)
            ]
            entries.extend(
                (ExifTags.GPSTAGS.get(key, f"GPS{key}"), value)
                for key, value in raw_exif.get_ifd(ExifTags.IFD.GPSInfo).items()
            )
            for tag_name, value in entries:
                serializable = _json_safe_exif_value(value)
                if serializable is not None:
                    mapped[tag_name] = serializable
            taken_at = _parse_taken_at(mapped)
            return taken_at, mapped or None
    except Exception:
        return None, None


def _json_safe_exif_value(value: object) -> Any | None:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, numbers.Rational):  # Pillow's IFDRational (exposure, f-number, GPS degrees)
        if not value.denominator:
            return None
        return float(value)
    if isinstance(value, bytes):
        return value[:64].hex()
    if isinstance(value, tuple):
        items = [_json_safe_exif_value(item) for item in value[:32]]
        return [item for item in items if item is not None]
    return str(value)


def _parse_taken_at(exif: dict[str, Any]) -> datetime | None:
    for key in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
        value = exif.get(key)
        if isinstance(value, str):
            try:
                return datetime.strptime(value, "%Y:%m:%d %H:%M:%S").replace(tzinfo=UTC)
            except ValueError:
                continue
    return None
