from __future__ import annotations

from bento.domain.exif import summarize_exif


def test_summary_parses_camera_exposure_and_gps() -> None:
    summary = summarize_exif(
        {
            "Make": "Google\x00",
            "Model": "Pixel 8",
            "LensModel": "Pixel 8 back camera",
            "ExposureTime": 0.004,
            "FNumber": "1.68",
            "ISOSpeedRatings": 64,
            "FocalLength": 6.9,
            "GPSLatitude": [4.0, 36.0, 35.4],
            "GPSLatitudeRef": "N",
            "GPSLongitude": [74.0, 4.0, 15.0],
            "GPSLongitudeRef": "W",
        }
    )
    assert summary is not None
    assert (summary.camera_make, summary.camera_model, summary.lens_model) == ("Google", "Pixel 8", "Pixel 8 back camera")
    assert summary.exposure_display == "1/250"
    assert summary.f_number == 1.68
    assert summary.iso == 64
    assert summary.focal_length_mm == 6.9
    assert summary.latitude == 4.609833
    assert summary.longitude == -74.070833


def test_summary_accepts_legacy_string_rationals_and_long_exposures() -> None:
    summary = summarize_exif({"ExposureTime": "2.0", "FNumber": "28/10"})
    assert summary is not None
    assert summary.exposure_display == "2"
    assert summary.f_number == 2.8


def test_summary_drops_malformed_values() -> None:
    assert summarize_exif(None) is None
    assert summarize_exif({"DateTime": "2024:01:01 00:00:00"}) is None
    summary = summarize_exif({"Model": "X", "GPSLatitude": [95.0, 0, 0], "GPSLongitude": [1.0], "ISOSpeedRatings": True})
    assert summary is not None
    assert (summary.latitude, summary.longitude, summary.iso) == (None, None, None)
