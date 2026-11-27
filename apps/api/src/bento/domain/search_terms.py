"""Lexical matching rules of search: which query words count, and how a word matches a name or a text.

Pure: standard library only. Used by FTS, file-name, metadata, folder, album and OCR matching
(`product/search.md` §Lexical matching).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

MIN_PREFIX_CHARS = 4
"""A query word matches the start of a longer word only from this length on («fact» → «factura», not «car» →
«carbonara»)."""
PREFIX_CREDIT = 0.5
"""A prefix match counts half a word: «bill» → «billete» is weaker evidence than «bill» → «bill»."""

# Spanish and English function words. They are dropped from scoring, except inside a quoted phrase or when the
# whole query is made of them.
STOP_WORDS = frozenset(
    {
        # es
        "a", "al", "algo", "como", "con", "contra", "cual", "cuando", "de", "del", "desde", "donde", "durante",
        "e", "el", "ella", "en", "entre", "era", "es", "esa", "ese", "eso", "esta", "este", "esto", "fue", "ha",
        "hay", "la", "las", "le", "les", "lo", "los", "mas", "me", "mi", "mis", "muy", "no", "nos", "o", "os",
        "para", "pero", "por", "que", "se", "sin", "sobre", "su", "sus", "te", "tu", "tus", "u", "un", "una",
        "unas", "uno", "unos", "y", "ya", "yo",
        # en
        "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into", "is", "it", "its", "my", "of",
        "on", "or", "our", "the", "their", "this", "that", "to", "was", "were", "with", "your",
    }
)

_PHRASE_RE = re.compile(r'"([^"]+)"')
_QUERY_WORD_RE = re.compile(r"[\w@.\-]+", flags=re.UNICODE)
_WORD_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)
_SEPARATORS = "._-@"


def fold(text: str) -> str:
    """Case- and accent-insensitive form («Reunión» → «reunion»), like FTS5's `unicode61` tokenizer."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def words(text: str) -> tuple[str, ...]:
    """The folded words of a name or a text: letters and digits, split on everything else (`-`, `_`, `.`)."""
    return tuple(_WORD_RE.findall(fold(text)))


@dataclass(frozen=True, slots=True)
class LexicalQuery:
    """What a query asks of names and texts.

    `terms` are single folded words; `fragments` are typed name pieces with separators («recibo-abril»,
    «IMG_2210», «notas.txt»), matched as substrings of the folded name; `phrases` are the quoted parts, matched
    word for word in order, stop words included. `needles` are the lowercased, unfolded forms, for SQL
    prefilters and highlighting.
    """

    terms: tuple[str, ...] = ()
    fragments: tuple[str, ...] = ()
    phrases: tuple[tuple[str, ...], ...] = ()
    needles: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.terms or self.fragments or self.phrases)

    @property
    def parts(self) -> int:
        return len(self.terms) + len(self.fragments) + len(self.phrases)

    @property
    def fts_words(self) -> tuple[tuple[str, ...], ...]:
        """FTS5 phrases to AND together: one per term, the words of each fragment and each quoted phrase."""
        return (
            *((term,) for term in self.terms),
            *(tuple(words(fragment)) for fragment in self.fragments if words(fragment)),
            *self.phrases,
        )


def lexical_query(raw: str) -> LexicalQuery:
    phrases = tuple(phrase for phrase in (words(match) for match in _PHRASE_RE.findall(raw)) if phrase)
    rest = _PHRASE_RE.sub(" ", raw)
    typed = [token.strip(_SEPARATORS).lower() for token in _QUERY_WORD_RE.findall(rest)]
    typed = [token for token in typed if token]
    fragments: list[str] = []
    singles: list[str] = []
    for token in typed:
        parts = words(token)
        if len(parts) > 1:
            fragments.append(fold(token))
        elif parts:
            singles.append(parts[0])
    content = [term for term in singles if term not in STOP_WORDS]
    if not content and not fragments and not phrases:
        content = singles  # a query made only of stop words («the who») still searches for them
    terms = tuple(dict.fromkeys(content))
    needles = tuple(
        dict.fromkeys(
            [
                *(token for token in typed if fold(token) in terms or fold(token) in fragments),
                *(" ".join(phrase) for phrase in phrases),
            ]
        )
    )
    return LexicalQuery(terms=terms, fragments=tuple(dict.fromkeys(fragments)), phrases=phrases, needles=needles)


def _variants(word: str) -> set[str]:
    """The word and its singular for a plain Spanish/English plural («facturas» → «factura», «bills» → «bill»)."""
    out = {word}
    if len(word) > 3 and word.endswith("s"):
        out.add(word[:-1])
        if len(word) > 4 and word.endswith("es"):
            out.add(word[:-2])
    return out


def term_credit(term: str, text_words: Iterable[str]) -> float:
    """1 for a whole-word match (plural-insensitive), `PREFIX_CREDIT` for a prefix of at least
    `MIN_PREFIX_CHARS` characters, else 0."""
    wanted = _variants(term)
    best = 0.0
    for word in text_words:
        if wanted & _variants(word):
            return 1.0
        if len(term) >= MIN_PREFIX_CHARS and word.startswith(term):
            best = PREFIX_CREDIT
    return best


def _phrase_in(phrase: tuple[str, ...], text_words: tuple[str, ...]) -> bool:
    size = len(phrase)
    return any(text_words[index : index + size] == phrase for index in range(len(text_words) - size + 1))


def match_score(query: LexicalQuery, text: str) -> float:
    """The share of the query found in `text`, in [0, 1]: each term, fragment and phrase counts once."""
    if query.is_empty or not text:
        return 0.0
    text_words = words(text)
    folded = fold(text)
    found = sum(term_credit(term, text_words) for term in query.terms)
    found += sum(1.0 for fragment in query.fragments if fragment in folded)
    found += sum(1.0 for phrase in query.phrases if _phrase_in(phrase, text_words))
    return found / query.parts


def sql_needles(query: LexicalQuery) -> tuple[str, ...]:
    """Substrings for a SQL `LIKE` prefilter of `match_score`: a superset of what can match (typed and folded
    forms, singulars, fragments and the words of each phrase)."""
    out: list[str] = [*query.needles, *query.fragments]
    for term in query.terms:
        out.extend(sorted(_variants(term)))
    for phrase in query.phrases:
        out.extend(phrase)
    return tuple(dict.fromkeys(needle for needle in out if needle))
