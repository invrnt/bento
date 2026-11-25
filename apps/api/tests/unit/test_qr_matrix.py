import pytest
import segno

from bento.interfaces.http.qr import logo_side, qr_matrix, recovery_qr_matrix

TELEGRAM_LOGIN = "tg://login?token=AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA"


def test_qr_matrix_is_square_binary_rows() -> None:
    matrix = qr_matrix("bento://join?v=1&c=K7Q2-MXR9-T4WA")

    assert matrix.size == len(matrix.rows)
    assert all(len(row) == matrix.size and set(row) <= {"0", "1"} for row in matrix.rows)
    assert matrix.rows[0].startswith("1111111")


def test_logo_codes_use_error_correction_h_and_a_small_centred_square() -> None:
    matrix = qr_matrix(TELEGRAM_LOGIN)
    expected = segno.make(TELEGRAM_LOGIN, error="h", micro=False)

    assert matrix.size == expected.symbol_size(border=0)[0]
    assert matrix.logo_modules % 2 == 1
    assert matrix.logo_modules >= 5
    # The cleared square stays far below what level H recovers (~30% of codewords).
    assert matrix.logo_modules**2 / matrix.size**2 < 0.04
    # It never reaches the finder patterns (7 modules + separator in each corner).
    assert (matrix.size - matrix.logo_modules) // 2 >= 8


def test_recovery_kit_qr_has_no_logo() -> None:
    matrix = recovery_qr_matrix("ABCD-EFGH-IJKL-MNOP")

    assert matrix.logo_modules == 0
    assert matrix == qr_matrix("bento-recovery:ABCD-EFGH-IJKL-MNOP", logo=False)


@pytest.mark.parametrize(("size", "side"), [(21, 3), (25, 3), (29, 5), (33, 5), (41, 7), (45, 7), (57, 9)])
def test_logo_side_is_odd_and_proportional(size: int, side: int) -> None:
    assert logo_side(size) == side
