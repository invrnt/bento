"""Viewer-facing summary of the EXIF tags stored with an asset (`Asset.metadata.exif`).

The stored map uses Pillow tag names (IFD0 + Exif sub-IFD + GPS IFD). Older rows keep rationals as strings
("0.01"), newer ones as floats; both parse. Anything malformed is left out rather than guessed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class ExifSummary:
    camera_make: str | None = None
    camera_model: str | None = None
    lens_model: str | None = None
    exposure_time_s: float | None = None
    exposure_display: str | None = None
    """"1/250" for sub-second exposures, "2" (seconds) otherwise."""
    f_number: float | None = None
    iso: int | None = None
    focal_length_mm: float | None = None
    latitude: float | None = None
    longitude: float | None = None

    @property
    def empty(self) -> bool:
        return all(getattr(self, name) is None for name in self.__slots__)  # type: ignore[attr-defined]


def summarize_exif(exif: Mapping[str, object] | None) -> ExifSummary | None:
    if not exif:
        return None
    exposure = _number(exif.get("ExposureTime"))
    if exposure is not None and exposure <= 0:
        exposure = None
    latitude = _coordinate(exif.get("GPSLatitude"), exif.get("GPSLatitudeRef"), negative="S", limit=90)
    longitude = _coordinate(exif.get("GPSLongitude"), exif.get("GPSLongitudeRef"), negative="W", limit=180)
    if latitude is None or longitude is None:
        latitude = longitude = None
    iso = _number(exif.get("ISOSpeedRatings", exif.get("PhotographicSensitivity")))
    summary = ExifSummary(
        camera_make=_text(exif.get("Make")),
        camera_model=_text(exif.get("Model")),
        lens_model=_text(exif.get("LensModel")),
        exposure_time_s=exposure,
        exposure_display=_exposure_display(exposure) if exposure is not None else None,
        f_number=_positive(exif.get("FNumber")),
        iso=int(iso) if iso is not None and iso > 0 else None,
        focal_length_mm=_positive(exif.get("FocalLength")),
        latitude=latitude,
        longitude=longitude,
    )
    return None if summary.empty else summary


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = "".join(char for char in value if char.isprintable()).strip().strip("\x00").strip()
    return cleaned[:120] or None


def _number(value: object) -> float | None:
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(Fraction(value.strip())) if "/" in value else float(value.strip())
        except (ValueError, ZeroDivisionError):
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _positive(value: object) -> float | None:
    number = _number(value)
    return round(number, 2) if number is not None and number > 0 else None


def _exposure_display(seconds: float) -> str:
    if seconds >= 1:
        return f"{seconds:g}"
    return f"1/{round(1 / seconds)}"


def _coordinate(value: object, ref: object, *, negative: str, limit: float) -> float | None:
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        return None
    parts = [_number(part) for part in value]
    if any(part is None or part < 0 for part in parts):
        return None
    degrees = sum(part / (60**index) for index, part in enumerate(parts))  # type: ignore[operator]
    if isinstance(ref, str) and ref.strip().upper() == negative:
        degrees = -degrees
    if abs(degrees) > limit:
        return None
    return round(degrees, 6)
