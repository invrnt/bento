from __future__ import annotations

import segno
from pydantic import BaseModel

# Share of the symbol's side the centre logo may cover. With error correction H
# (~30% of codewords recoverable) this square is ~2-3% of the area. Measured with
# zxing-cpp and OpenCV on Telegram login and join links (blur, scaling, rotation,
# perspective, low contrast): 0.18 decodes like a plain code; 0.22 already fails
# some long links, because the mark's dark box reads as wrong modules.
LOGO_SIDE_RATIO = 0.18

RECOVERY_QR_PREFIX = "bento-recovery:"


class QrMatrix(BaseModel):
    """QR modules as rows of "0"/"1" so the renderer can draw it without HTML injection.

    `logo_modules` is the side, in modules, of the centred square the renderer
    clears to draw the Bento mark; 0 means a plain code with no logo.
    """

    size: int
    rows: list[str]
    logo_modules: int = 0


def qr_matrix(data: str, *, logo: bool = True) -> QrMatrix:
    """Encode `data` for on-screen scanning.

    Codes with the logo use error correction H so the hidden centre is recovered.
    Plain codes (logo=False, e.g. the printed recovery kit) keep level M as the
    minimum (segno still boosts it when that fits the same symbol size).
    """
    code = segno.make(data, error="h" if logo else "m", micro=False)
    rows = ["".join("1" if module else "0" for module in row) for row in code.matrix_iter(border=0)]
    size = len(rows)
    return QrMatrix(size=size, rows=rows, logo_modules=logo_side(size) if logo else 0)


def logo_side(size: int) -> int:
    """Largest odd side (so it centres on a module) within LOGO_SIDE_RATIO of the symbol."""
    side = int(size * LOGO_SIDE_RATIO)
    return side if side % 2 == 1 else side - 1


def recovery_qr_matrix(recovery_code: str) -> QrMatrix:
    """The recovery kit's QR (`bento-recovery:<code>`). No logo: it is printed, and paper wears."""
    return qr_matrix(f"{RECOVERY_QR_PREFIX}{recovery_code}", logo=False)
