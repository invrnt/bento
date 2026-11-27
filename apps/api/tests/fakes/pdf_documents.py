"""Tiny, valid PDFs written by hand for the text layer tests (no PDF library needed to make them).

Each page shows its lines in Helvetica (a standard font, WinAnsi encoding, so Latin-1 text such as «panadería»
round-trips). A page given as `None` has no text at all, like a scan.
"""

from __future__ import annotations

from collections.abc import Sequence


def pdf_with_pages(pages: Sequence[Sequence[str] | None]) -> bytes:
    objects: list[bytes] = []
    page_ids: list[int] = []
    # 1: catalog, 2: pages, 3: font; then a (content, page) pair per page.
    font_id = 3
    next_id = 4
    page_objects: list[tuple[int, bytes]] = []
    for lines in pages:
        content_id, page_id = next_id, next_id + 1
        next_id += 2
        stream = _content(lines or ())
        page_objects.append((content_id, b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"))
        page_objects.append(
            (
                page_id,
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 %d 0 R >> >> "
                b"/Contents %d 0 R >>" % (font_id, content_id),
            )
        )
        page_ids.append(page_id)
    kids = b" ".join(b"%d 0 R" % page_id for page_id in page_ids)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % len(page_ids),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    by_id = {index + 1: body for index, body in enumerate(objects)}
    by_id.update(dict(page_objects))

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for object_id in sorted(by_id):
        offsets[object_id] = len(out)
        out += b"%d 0 obj\n" % object_id + by_id[object_id] + b"\nendobj\n"
    xref = len(out)
    count = max(by_id) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % count
    for object_id in range(1, count):
        out += b"%010d 00000 n \n" % offsets[object_id]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (count, xref)
    return bytes(out)


def _content(lines: Sequence[str]) -> bytes:
    if not lines:
        return b"q Q"
    parts = [b"BT /F1 12 Tf 14 TL 72 740 Td"]
    for line in lines:
        escaped = line.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
        parts.append(b"(" + escaped + b") Tj T*")
    parts.append(b"ET")
    return b"\n".join(parts)
