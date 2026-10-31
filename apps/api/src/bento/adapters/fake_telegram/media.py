"""Tiny valid media files generated at runtime with the stdlib (no binary fixtures)."""

from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
import zlib
from collections.abc import Sequence
from pathlib import Path

Rgb = tuple[int, int, int]

# ITU T.81 Annex K.3 luminance DC table; AC coefficients are always zero, so EOB is the only AC symbol.
_DC_BITS = (0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0)
_DC_VALUES = tuple(range(12))
_AC_BITS = (1,) + (0,) * 15
_AC_VALUES = (0x00,)


def png_bytes(width: int, height: int, colors: Sequence[Rgb]) -> bytes:
    """Horizontal stripes of `colors`."""
    rows = bytearray()
    for y in range(height):
        red, green, blue = colors[y * len(colors) // height]
        rows.append(0)
        rows.extend(bytes((red, green, blue)) * width)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b"")


def jpeg_bytes(width: int, height: int, colors: Sequence[Rgb]) -> bytes:
    """Baseline JPEG made of flat 8x8 blocks; diagonal bands of `colors`."""
    if width % 8 or height % 8:
        raise ValueError("JPEG placeholder dimensions must be multiples of 8")
    blocks_x, blocks_y = width // 8, height // 8
    writer = _BitWriter()
    dc_codes = _huffman_codes(_DC_BITS, _DC_VALUES)
    eob_code = _huffman_codes(_AC_BITS, _AC_VALUES)[0]
    predictors = [0, 0, 0]
    for block_y in range(blocks_y):
        for block_x in range(blocks_x):
            color = colors[(block_x + block_y) * len(colors) // (blocks_x + blocks_y)]
            for component, sample in enumerate(_ycbcr(color)):
                # With an all-ones quantization table the DC coefficient of a flat block is 8 * (sample - 128).
                dc = 8 * (sample - 128)
                diff = dc - predictors[component]
                predictors[component] = dc
                category = abs(diff).bit_length()
                writer.write(*dc_codes[category])
                if category:
                    writer.write(diff if diff > 0 else diff + (1 << category) - 1, category)
                writer.write(*eob_code)
    return b"".join(
        (
            b"\xff\xd8",
            _segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"),
            _segment(0xDB, b"\x00" + b"\x01" * 64),
            _segment(0xC0, struct.pack(">BHHB", 8, height, width, 3) + b"\x01\x11\x00\x02\x11\x00\x03\x11\x00"),
            _segment(0xC4, b"\x00" + bytes(_DC_BITS) + bytes(_DC_VALUES)),
            _segment(0xC4, b"\x10" + bytes(_AC_BITS) + bytes(_AC_VALUES)),
            _segment(0xDA, b"\x03\x01\x00\x02\x00\x03\x00\x00\x3f\x00"),
            writer.finish(),
            b"\xff\xd9",
        )
    )


def pdf_bytes(text: str) -> bytes:
    """One A4 page with a line of Helvetica text (ASCII only)."""
    escaped = text.encode("ascii", "replace").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    content = b"BT /F1 24 Tf 72 760 Td (" + escaped + b") Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(output)
    output += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    output += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    output += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(output)


def mp4_bytes() -> bytes:
    """A one-second test pattern via ffmpeg when installed; otherwise a minimal ISO-BMFF container."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is not None:
        with tempfile.TemporaryDirectory(prefix="bento-fake-mp4-") as directory:
            target = Path(directory) / "clip.mp4"
            command = [
                ffmpeg, "-v", "error", "-nostdin", "-f", "lavfi", "-i", "testsrc=duration=1:size=96x64:rate=8",
                "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-y", str(target),
            ]  # fmt: skip
            try:
                subprocess.run(command, check=True, capture_output=True, timeout=20)
                return target.read_bytes()
            except (OSError, subprocess.SubprocessError):
                pass
    ftyp = b"isom" + struct.pack(">I", 0x200) + b"isomiso2mp41"
    return _box(b"ftyp", ftyp) + _box(b"free", b"") + _box(b"mdat", b"")


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def _segment(marker: int, payload: bytes) -> bytes:
    return bytes((0xFF, marker)) + struct.pack(">H", len(payload) + 2) + payload


def _ycbcr(color: Rgb) -> tuple[int, int, int]:
    red, green, blue = color
    y = 0.299 * red + 0.587 * green + 0.114 * blue
    cb = -0.168736 * red - 0.331264 * green + 0.5 * blue + 128
    cr = 0.5 * red - 0.418688 * green - 0.081312 * blue + 128
    return tuple(max(0, min(255, round(value))) for value in (y, cb, cr))  # type: ignore[return-value]


def _huffman_codes(bits: Sequence[int], values: Sequence[int]) -> dict[int, tuple[int, int]]:
    """Canonical codes (T.81 Annex C): symbol -> (code, length)."""
    codes: dict[int, tuple[int, int]] = {}
    code = 0
    index = 0
    for length, count in enumerate(bits, start=1):
        for _ in range(count):
            codes[values[index]] = (code, length)
            code += 1
            index += 1
        code <<= 1
    return codes


class _BitWriter:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self._accumulator = 0
        self._count = 0

    def write(self, value: int, length: int) -> None:
        for shift in range(length - 1, -1, -1):
            self._accumulator = (self._accumulator << 1) | ((value >> shift) & 1)
            self._count += 1
            if self._count == 8:
                self._emit()

    def finish(self) -> bytes:
        if self._count:
            padding = 8 - self._count
            self._accumulator = (self._accumulator << padding) | ((1 << padding) - 1)
            self._emit()
        return bytes(self._buffer)

    def _emit(self) -> None:
        self._buffer.append(self._accumulator)
        if self._accumulator == 0xFF:
            self._buffer.append(0x00)
        self._accumulator = 0
        self._count = 0
