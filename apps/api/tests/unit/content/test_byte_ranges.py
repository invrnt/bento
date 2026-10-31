from __future__ import annotations

import pytest

from bento.interfaces.http.routes_content import RangeNotSatisfiableError, inline_disposition, parse_byte_range


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("bytes=0-0", (0, 0)),
        ("bytes=0-99", (0, 99)),
        ("bytes=10-", (10, 99)),
        ("bytes=90-500", (90, 99)),
        ("bytes=99-99", (99, 99)),
        ("bytes=-10", (90, 99)),
        ("bytes=-500", (0, 99)),
        (" bytes = 5 - 6 ", (5, 6)),
        ("items=0-5", None),
        ("bytes=0-1,4-5", None),
    ],
)
def test_parse_byte_range(header: str | None, expected: tuple[int, int] | None) -> None:
    assert parse_byte_range(header, 100) == expected


@pytest.mark.parametrize(
    "header",
    ["bytes=100-", "bytes=150-200", "bytes=5-2", "bytes=-0", "bytes=abc", "bytes=-", "bytes=1-x", "bytes=--5"],
)
def test_unsatisfiable_or_malformed_byte_ranges(header: str) -> None:
    with pytest.raises(RangeNotSatisfiableError):
        parse_byte_range(header, 100)


def test_empty_files_cannot_satisfy_any_range() -> None:
    with pytest.raises(RangeNotSatisfiableError):
        parse_byte_range("bytes=0-", 0)
    with pytest.raises(RangeNotSatisfiableError):
        parse_byte_range("bytes=-1", 0)


def test_inline_disposition_escapes_quotes_and_keeps_utf8_name() -> None:
    header = inline_disposition('fac"tura; año.pdf')
    assert header.startswith('inline; filename="fac_tura_ a_o.pdf"')
    assert "filename*=UTF-8''fac%22tura%3B%20a%C3%B1o.pdf" in header
