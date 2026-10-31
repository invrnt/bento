from bento.interfaces.http.qr import qr_matrix


def test_qr_matrix_is_square_binary_rows() -> None:
    matrix = qr_matrix("bento://join?v=1&c=K7Q2-MXR9-T4WA")

    assert matrix.size == len(matrix.rows)
    assert all(len(row) == matrix.size and set(row) <= {"0", "1"} for row in matrix.rows)
    assert matrix.rows[0].startswith("1111111")
