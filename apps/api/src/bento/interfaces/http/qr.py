from __future__ import annotations

import segno
from pydantic import BaseModel


class QrMatrix(BaseModel):
    """QR modules as rows of "0"/"1" so the renderer can draw it without HTML injection."""

    size: int
    rows: list[str]


def qr_matrix(data: str) -> QrMatrix:
    code = segno.make(data, error="m", micro=False)
    rows = ["".join("1" if module else "0" for module in row) for row in code.matrix_iter(border=0)]
    return QrMatrix(size=len(rows), rows=rows)
