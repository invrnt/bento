from __future__ import annotations

import asyncio
import hashlib

from bento.adapters.media.metadata import LocalUploadMetadataExtractor
from bento.application.ingestion.metadata import sanitize_filename


def test_sanitize_filename_removes_paths_controls_and_reserved_names() -> None:
    assert sanitize_filename("../camera/photo.jpg") == "photo.jpg"
    assert sanitize_filename("bad\x00name.pdf") == "badname.pdf"
    assert sanitize_filename("CON.txt") == "_CON.txt"
    assert sanitize_filename("...") == "upload"


def test_extract_upload_metadata_sniffs_pdf_and_computes_sha(tmp_path) -> None:
    async def scenario() -> None:
        content = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"
        source = tmp_path / "upload.tmp"
        source.write_bytes(content)

        metadata = await LocalUploadMetadataExtractor().extract(
            source,
            original_filename="../scan.bin",
            declared_mime_type="application/octet-stream",
        )

        assert metadata.filename == "scan.bin"
        assert metadata.mime_type == "application/pdf"
        assert metadata.size_bytes == len(content)
        assert metadata.sha256 == hashlib.sha256(content).hexdigest()
        assert metadata.exif is None

    asyncio.run(scenario())


def test_extract_upload_metadata_reads_camera_date_from_exif_sub_ifd(tmp_path) -> None:
    from datetime import UTC, datetime

    from PIL import ExifTags, Image

    async def scenario() -> None:
        exif = Image.Exif()
        exif[ExifTags.Base.DateTime] = "2024:05:01 10:00:00"
        exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = "2019:03:14 15:09:26"
        exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.ExposureTime] = 0.01
        source = tmp_path / "photo.jpg"
        Image.new("RGB", (8, 8), "red").save(source, exif=exif)

        metadata = await LocalUploadMetadataExtractor().extract(
            source, original_filename="photo.jpg", declared_mime_type="image/jpeg"
        )

        assert metadata.taken_at == datetime(2019, 3, 14, 15, 9, 26, tzinfo=UTC)
        assert metadata.exif is not None
        assert metadata.exif["DateTimeOriginal"] == "2019:03:14 15:09:26"
        assert "ExposureTime" in metadata.exif
        assert "ExifOffset" not in metadata.exif

    asyncio.run(scenario())


def test_extract_upload_metadata_reads_gps_ifd_and_rationals_as_numbers(tmp_path) -> None:
    from fractions import Fraction

    from PIL import ExifTags, Image
    from PIL.TiffImagePlugin import IFDRational

    from bento.domain.exif import summarize_exif

    async def scenario() -> None:
        exif = Image.Exif()
        exif[ExifTags.Base.Make] = "Canon"
        exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.FNumber] = IFDRational(Fraction(28, 10))
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
        gps[ExifTags.GPS.GPSLatitudeRef] = "S"
        gps[ExifTags.GPS.GPSLatitude] = (IFDRational(33), IFDRational(52), IFDRational(0))
        gps[ExifTags.GPS.GPSLongitudeRef] = "E"
        gps[ExifTags.GPS.GPSLongitude] = (IFDRational(151), IFDRational(12), IFDRational(36))
        source = tmp_path / "gps.jpg"
        Image.new("RGB", (8, 8), "blue").save(source, exif=exif)

        metadata = await LocalUploadMetadataExtractor().extract(
            source, original_filename="gps.jpg", declared_mime_type="image/jpeg"
        )
        assert metadata.exif is not None
        assert metadata.exif["FNumber"] == 2.8
        assert "GPSInfo" not in metadata.exif
        summary = summarize_exif(metadata.exif)
        assert summary is not None
        assert summary.camera_make == "Canon"
        assert summary.latitude == -33.866667
        assert summary.longitude == 151.21

    asyncio.run(scenario())
