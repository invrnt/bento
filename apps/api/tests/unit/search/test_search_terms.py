from __future__ import annotations

from bento.domain.search_terms import (
    MIN_PREFIX_CHARS,
    PREFIX_CREDIT,
    fold,
    lexical_query,
    match_score,
    sql_needles,
    term_credit,
    words,
)


def test_stop_words_are_dropped_from_scoring() -> None:
    query = lexical_query("facturas de la luz")
    assert query.terms == ("facturas", "luz")
    assert lexical_query("the electricity bill of March").terms == ("electricity", "bill", "march")


def test_a_query_made_only_of_stop_words_still_searches_for_them() -> None:
    assert lexical_query("de la").terms == ("de", "la")


def test_a_quoted_phrase_keeps_its_stop_words_and_their_order() -> None:
    query = lexical_query('"viaje a la playa" agosto')
    assert query.phrases == (("viaje", "a", "la", "playa"),)
    assert query.terms == ("agosto",)
    assert match_score(query, "Notas: viaje a la playa en agosto") == 1.0
    assert match_score(query, "La playa: viaje en agosto") == 0.5  # the phrase is not there in order


def test_stop_words_do_not_match_inside_names() -> None:
    query = lexical_query("facturas de luz")
    assert match_score(query, "ideas-regalos-navidad.txt") == 0.0
    assert match_score(query, "endesa-recibo-abril.png") == 0.0
    assert match_score(query, "factura-luz-enero-2026.pdf") == 1.0  # «facturas» → «factura» (plural)


def test_prefixes_need_four_characters_and_count_half() -> None:
    assert MIN_PREFIX_CHARS == 4
    assert term_credit("car", words("receta-pasta-carbonara.pdf")) == 0.0
    assert term_credit("car", words("car-insurance.pdf")) == 1.0
    assert term_credit("carb", words("receta-pasta-carbonara.pdf")) == PREFIX_CREDIT
    assert term_credit("bill", words("billete-tren.pdf")) == PREFIX_CREDIT
    assert term_credit("bill", words("water-bill.pdf")) == 1.0
    assert term_credit("bills", words("water-bill.pdf")) == 1.0


def test_matching_ignores_case_and_accents() -> None:
    assert fold("Reunión AÑO") == "reunion ano"
    assert match_score(lexical_query("reunión"), "notas-reunion-presupuesto.pdf") == 1.0
    assert match_score(lexical_query("REUNION"), "Reunión de equipo") == 1.0


def test_typed_name_fragments_match_as_substrings() -> None:
    query = lexical_query("recibo-abril")
    assert query.fragments == ("recibo-abril",) and query.terms == ()
    assert match_score(query, "endesa-recibo-abril.png") == 1.0
    assert match_score(lexical_query("IMG_2210"), "IMG_2210.jpg") == 1.0
    assert match_score(lexical_query("endesa-recibo-abril.png"), "endesa-recibo-abril.png") == 1.0


def test_sql_needles_cover_every_possible_match() -> None:
    query = lexical_query('Facturas de "la luz" recibo-abril')
    needles = sql_needles(query)
    assert "facturas" in needles and "factura" in needles  # the singular, for «factura-luz.pdf»
    assert "recibo-abril" in needles and "luz" in needles
    assert "de" not in needles


def test_fts_words_and_one_phrase_per_part() -> None:
    query = lexical_query('contraseña del wifi "de la playa" IMG_2210')
    assert query.fts_words == (("contrasena",), ("wifi",), ("img", "2210"), ("de", "la", "playa"))
