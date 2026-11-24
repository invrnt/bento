"""Terminal QR rendering from the API's matrix (`{"size": N, "rows": ["1010…"]}`) with Unicode half blocks.

Two module rows share one text row. With ANSI colors the code is drawn black on white on any terminal
theme; without colors (pipes, `NO_COLOR`) light modules are blocks, which scans on the usual dark
terminal background (same convention as `qrencode -t UTF8`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

QUIET_ZONE = 2
_UPPER = "▀"
_LOWER = "▄"
_FULL = "█"
_ANSI_BLACK_ON_WHITE_RESET = "\x1b[0m"


def matrix_rows(qr: Mapping[str, Any] | None) -> list[str]:
    if not qr:
        return []
    rows = qr.get("rows")
    if not isinstance(rows, list) or not all(isinstance(row, str) for row in rows):
        return []
    return [row for row in rows]


def _padded(rows: Sequence[str], quiet: int) -> list[list[bool]]:
    width = max((len(row) for row in rows), default=0) + 2 * quiet
    blank = [False] * width
    grid = [list(blank) for _ in range(quiet)]
    for row in rows:
        grid.append([False] * quiet + [char == "1" for char in row.ljust(width - 2 * quiet, "0")] + [False] * quiet)
    grid.extend(list(blank) for _ in range(quiet))
    if len(grid) % 2:
        grid.append(list(blank))
    return grid


def render_qr(qr: Mapping[str, Any] | None, *, ansi: bool, quiet: int = QUIET_ZONE) -> str:
    rows = matrix_rows(qr)
    if not rows:
        return ""
    grid = _padded(rows, quiet)
    lines: list[str] = []
    for top_row, bottom_row in zip(grid[0::2], grid[1::2], strict=True):
        if ansi:
            lines.append(_ansi_line(top_row, bottom_row))
        else:
            lines.append("".join(_plain_char(not top, not bottom) for top, bottom in zip(top_row, bottom_row, strict=True)))
    return "\n".join(lines)


def _plain_char(top: bool, bottom: bool) -> str:
    """`top`/`bottom` are True where a block is drawn."""
    if top and bottom:
        return _FULL
    if top:
        return _UPPER
    if bottom:
        return _LOWER
    return " "


def _ansi_line(top_row: Sequence[bool], bottom_row: Sequence[bool]) -> str:
    # Upper half block: foreground paints the top module, background the bottom one.
    parts: list[str] = []
    for top, bottom in zip(top_row, bottom_row, strict=True):
        foreground = "30" if top else "97"
        background = "40" if bottom else "107"
        parts.append(f"\x1b[{foreground};{background}m{_UPPER}")
    return "".join(parts) + _ANSI_BLACK_ON_WHITE_RESET
