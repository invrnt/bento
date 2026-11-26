from __future__ import annotations

import pytest

from bento.domain.smart_search import (
    MAX_CHUNKS_PER_ASSET,
    TextChunk,
    batched,
    chunk_pages,
    chunk_text,
    estimate_tokens,
)


def texts(chunks: tuple[TextChunk, ...]) -> list[str]:
    return [c.text for c in chunks]


def test_empty_and_blank_inputs_give_no_chunks() -> None:
    assert chunk_text("") == ()
    assert chunk_text("  \n\t \n") == ()
    assert chunk_pages([]) == ()
    assert chunk_pages(["", "  "]) == ()
    assert estimate_tokens("") == 0


@pytest.mark.parametrize(
    ("text", "tokens"),
    [("Hola mundo", 4), ("hello", 2), ("42,10 €", 7), ("東京タワー", 5), ("👍", 3), ("👍🏽", 6), ("niño", 2), ("nin\u0303o", 3)],
)
def test_token_estimate_golden(text: str, tokens: int) -> None:
    assert estimate_tokens(text) == tokens


def test_spanish_golden_split_on_sentences() -> None:
    text = "Factura de luz. Importe total: 42,10 €. Vence el 3 de marzo.\nGracias por su pago."
    assert texts(chunk_text(text, max_tokens=10)) == [
        "Factura de luz.",
        "Importe total:",
        "42,10 €.",
        "Vence el 3 de marzo.",
        "Gracias por su pago.",
    ]
    assert texts(chunk_text(text, max_tokens=512)) == [
        "Factura de luz. Importe total: 42,10 €. Vence el 3 de marzo. Gracias por su pago."
    ]


def test_english_golden_split_on_words_when_a_sentence_is_too_long() -> None:
    text = "one two three four five six seven eight nine ten eleven twelve"
    assert texts(chunk_text(text, max_tokens=5)) == [
        "one two three",
        "four five six",
        "seven eight",
        "nine ten eleven",
        "twelve",
    ]


def test_cjk_without_spaces_is_cut_by_characters() -> None:
    chunks = chunk_text("東京タワーは東京都港区にある電波塔です。高さは333メートルです。", max_tokens=10)
    assert texts(chunks) == ["東京タワーは東京都港", "区にある電波塔です。", "高さは333メートル", "です。"]
    assert all(c.estimated_tokens <= 10 for c in chunks)


def test_emoji_are_never_split_mid_sequence_into_overbudget_chunks() -> None:
    text = "Cumpleaños en la playa 🎂🏖️👨‍👩‍👧 " * 8
    chunks = chunk_text(text, max_tokens=32)
    assert len(chunks) < 16 and all(c.estimated_tokens <= 32 for c in chunks)
    assert "".join(texts(chunks)).replace(" ", "") == text.replace(" ", "")


def test_long_unbroken_token_is_hard_split() -> None:
    assert texts(chunk_text("a" * 100, max_tokens=8)) == ["a" * 24] * 4 + ["a" * 4]


def test_pages_keep_order_and_numbers_and_never_span_pages() -> None:
    chunks = chunk_pages(["página uno corta", "", "page three"], max_tokens=50)
    assert [(c.chunk_no, c.page, c.text) for c in chunks] == [(0, 1, "página uno corta"), (1, 3, "page three")]
    assert chunk_text("solo")[0].page is None


def test_cap_keeps_first_pages_first() -> None:
    chunks = chunk_pages([f"página {i} " + "palabra " * 600 for i in range(1, 40)])
    assert len(chunks) == MAX_CHUNKS_PER_ASSET
    assert chunks[0].text.startswith("página 1 ")
    assert [c.chunk_no for c in chunks] == list(range(MAX_CHUNKS_PER_ASSET))
    assert all(c.estimated_tokens <= 512 for c in chunks)


def test_huge_input_is_bounded() -> None:
    chunks = chunk_text("palabra " * 2_000_000)
    assert len(chunks) == MAX_CHUNKS_PER_ASSET


def test_invalid_budgets() -> None:
    with pytest.raises(ValueError):
        chunk_text("x", max_tokens=0)
    with pytest.raises(ValueError):
        chunk_text("x", max_chunks=0)


def test_batches_of_eight() -> None:
    items = [str(i) for i in range(19)]
    assert [len(b) for b in batched(items)] == [8, 8, 3]
    assert batched([]) == ()
    with pytest.raises(ValueError):
        batched(items, 0)
