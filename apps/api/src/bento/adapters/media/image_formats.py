"""The image formats Bento decodes with Pillow (SEC-02, `orchestration/execution/android-security-review.md`).

Uploads come from the share sheet of any app, so their MIME type and name are attacker-chosen. Every `Image.open`
passes `formats=IMAGE_FORMATS`: Pillow then never runs the parsers of formats Bento does not show (PSD, EPS, ICNS,
FLI, ...), which is where most of its memory-safety advisories live. MPO is how Pillow reports multi-picture JPEGs
(phone cameras); AVIF is built in since Pillow 11.2, HEIF needs the optional `pillow-heif` plugin; DNG opens as TIFF.
`open_formats` drops formats whose plugin is not installed.
"""

from __future__ import annotations

IMAGE_FORMATS: tuple[str, ...] = ("JPEG", "MPO", "PNG", "WEBP", "GIF", "TIFF", "HEIF", "AVIF")


def open_formats() -> tuple[str, ...]:
    """`IMAGE_FORMATS` whose Pillow plugin is registered (Pillow raises on an unknown name in `formats=`)."""
    from PIL import Image

    Image.init()
    return tuple(name for name in IMAGE_FORMATS if name in Image.OPEN)
