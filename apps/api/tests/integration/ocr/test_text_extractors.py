"""Text extraction adapters on real files: plain text decoding and the PDF text layer (pypdfium2)."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import pytest

from bento.adapters.text import CompositeTextExtractor, PlainTextExtractor, Pypdfium2TextLayerExtractor
from bento.adapters.text.plain import decode_text
from bento.domain.errors import ValidationFailedError
from bento.domain.indexing import ExtractedText
from tests.fakes.pdf_documents import pdf_with_pages


def extract(extractor: object, path: Path, mime: str, **kwargs: object) -> ExtractedText:
    return asyncio.run(extractor.extract(path, mime, **kwargs))  # type: ignore[attr-defined]


def write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


# Plain text -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        pytest.param("Factura de la luz: 45,20 € — añadido".encode(), "Factura de la luz: 45,20 € — añadido", id="utf-8"),
        pytest.param(b"\xef\xbb\xbfcon BOM \xc3\xb1", "con BOM ñ", id="utf-8-bom"),
        pytest.param("\ufeffUTF-16 «niño»".encode("utf-16-le"), "UTF-16 «niño»", id="utf-16-le-bom"),
        pytest.param("\ufeffbig endian ü".encode("utf-16-be"), "big endian ü", id="utf-16-be-bom"),
        pytest.param("Año pequeño, canción".encode("latin-1"), "Año pequeño, canción", id="latin-1"),
        pytest.param("Precio: 10 € “oferta”".encode("cp1252"), "Precio: 10 € “oferta”", id="cp1252"),
        pytest.param(b"linea 1\r\nlinea 2\rlinea 3\x00\n", "linea 1\nlinea 2\nlinea 3\n", id="newlines-and-nul"),
    ],
)
def test_plain_text_encodings(tmp_path: Path, data: bytes, expected: str) -> None:
    assert decode_text(data) == expected
    result = extract(PlainTextExtractor(), write(tmp_path, "nota.txt", data), "text/plain; charset=utf-8")
    assert result.pages[0].text == expected
    assert result.pages_read == 1 and not result.truncated


def test_binary_or_garbage_content_yields_no_text(tmp_path: Path) -> None:
    garbage = os.urandom(32 * 1024)
    png_like = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" * 200

    assert decode_text(garbage) is None and decode_text(png_like) is None
    result = extract(PlainTextExtractor(), write(tmp_path, "falso.txt", garbage), "text/plain")
    assert result.empty and result.pages == ()


def test_markdown_and_csv_are_plain_text(tmp_path: Path) -> None:
    extractor = PlainTextExtractor()
    md = extract(extractor, write(tmp_path, "notas.md", b"# Receta\n\n- pasta\n"), "text/markdown")
    csv = extract(extractor, write(tmp_path, "gastos.csv", b"concepto;importe\nluz;45,20\n"), "text/csv")

    assert md.pages[0].text == "# Receta\n\n- pasta\n"
    assert "luz;45,20" in csv.text
    assert not extractor.supports("text/html") and not extractor.supports("application/pdf")


def test_oversize_files_are_read_up_to_the_cap_without_a_broken_character(tmp_path: Path) -> None:
    # "ñ" is two bytes in UTF-8: a cap of 7 bytes cuts the fourth one in half.
    path = write(tmp_path, "grande.txt", "ññññññññ".encode())

    result = extract(PlainTextExtractor(max_bytes=7), path, "text/plain")

    assert result.text == "ñññ" and result.truncated


def test_the_character_cap_applies_after_decoding(tmp_path: Path) -> None:
    result = extract(PlainTextExtractor(max_chars=5), write(tmp_path, "largo.txt", b"abcdefghij"), "text/plain")

    assert result.text == "abcde" and result.truncated


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_symlinks_and_non_regular_files_are_refused(tmp_path: Path) -> None:
    secret = write(tmp_path, "secret.txt", b"no")
    link = tmp_path / "enlace.txt"
    link.symlink_to(secret)

    with pytest.raises(ValidationFailedError):
        extract(PlainTextExtractor(), link, "text/plain")
    with pytest.raises(ValidationFailedError):
        extract(PlainTextExtractor(), tmp_path, "text/plain")  # a directory


def test_an_empty_text_file_has_no_text(tmp_path: Path) -> None:
    assert extract(PlainTextExtractor(), write(tmp_path, "vacio.txt", b""), "text/plain").empty


# PDF text layer --------------------------------------------------------------------------------------------------

needs_pdfium = pytest.mark.skipif(importlib.util.find_spec("pypdfium2") is None, reason="pypdfium2 not installed")


@needs_pdfium
@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_a_symlinked_pdf_is_refused(tmp_path: Path) -> None:
    target = write(tmp_path, "real.pdf", pdf_with_pages([["texto"]]))
    link = tmp_path / "enlace.pdf"
    link.symlink_to(target)

    with pytest.raises(ValidationFailedError):
        extract(Pypdfium2TextLayerExtractor(), link, "application/pdf")


@needs_pdfium
def test_pdf_text_layer_is_read_per_page_without_rendering(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "factura.pdf",
        pdf_with_pages([["Factura de la luz", "Total 45,20 EUR (enero)"], None, ["Panadería: página tres"]]),
    )

    result = extract(Pypdfium2TextLayerExtractor(), path, "application/pdf")

    assert result.pages_read == 3 and not result.truncated
    assert [page.page_number for page in result.pages] == [1, 3]  # the blank page is counted, not kept
    assert result.pages[0].text == "Factura de la luz\nTotal 45,20 EUR (enero)"
    assert result.pages[1].text == "Panadería: página tres"
    assert not list(tmp_path.glob("*.png"))


@needs_pdfium
def test_a_scanned_pdf_has_an_empty_text_layer(tmp_path: Path) -> None:
    path = write(tmp_path, "escaneo.pdf", pdf_with_pages([None, None]))

    result = extract(Pypdfium2TextLayerExtractor(), path, "application/pdf")

    assert result.empty and result.pages_read == 2


@needs_pdfium
def test_pdf_page_and_character_caps(tmp_path: Path) -> None:
    path = write(tmp_path, "largo.pdf", pdf_with_pages([[f"Página número {n}"] for n in range(1, 6)]))

    by_pages = extract(Pypdfium2TextLayerExtractor(max_pages=2), path, "application/pdf")
    assert [page.page_number for page in by_pages.pages] == [1, 2] and by_pages.truncated

    by_chars = extract(Pypdfium2TextLayerExtractor(max_chars=20), path, "application/pdf")
    assert sum(len(page.text) for page in by_chars.pages) == 20 and by_chars.truncated
    assert by_chars.pages_read < 5  # stopped reading once the cap was reached


@needs_pdfium
@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"%PDF-1.4\nthis is not really a pdf", id="garbage-after-header"),
        pytest.param(b"", id="empty-file"),
        pytest.param(os.urandom(4096), id="random-bytes"),
    ],
)
def test_malformed_pdfs_fail_cleanly(tmp_path: Path, data: bytes) -> None:
    path = write(tmp_path, "roto.pdf", data)

    with pytest.raises(ValidationFailedError) as caught:
        extract(Pypdfium2TextLayerExtractor(), path, "application/pdf")
    assert str(tmp_path) not in str(caught.value)  # no paths in job errors


@needs_pdfium
def test_checkpoints_run_between_pages(tmp_path: Path) -> None:
    path = write(tmp_path, "tres.pdf", pdf_with_pages([["uno"], ["dos"], ["tres"]]))
    calls: list[int] = []

    def checkpoint() -> None:
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("deadline")

    with pytest.raises(RuntimeError, match="deadline"):
        extract(Pypdfium2TextLayerExtractor(), path, "application/pdf", checkpoint=checkpoint)
    assert len(calls) == 2


@needs_pdfium
def test_the_composite_routes_by_mime_type(tmp_path: Path) -> None:
    extractor = CompositeTextExtractor([PlainTextExtractor(), Pypdfium2TextLayerExtractor()])
    pdf = write(tmp_path, "a.pdf", pdf_with_pages([["contrato de arrendamiento"]]))
    txt = write(tmp_path, "a.txt", b"lista de la compra")

    assert extract(extractor, pdf, "application/pdf").text == "contrato de arrendamiento"
    assert extract(extractor, txt, "text/plain").text == "lista de la compra"
    assert not extractor.supports("image/jpeg")
    with pytest.raises(ValidationFailedError):
        extract(extractor, txt, "image/jpeg")
