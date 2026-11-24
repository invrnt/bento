"""Bounded `IN (...)` helpers for batch repository queries."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from sqlalchemy import ColumnElement, or_
from sqlalchemy.orm import InstrumentedAttribute

# Well below SQLite's bound-parameter limit.
IN_CHUNK_SIZE = 500


def chunks(values: Sequence[str]) -> Iterator[list[str]]:
    """Distinct `values` (first occurrence order) in chunks of at most `IN_CHUNK_SIZE`."""
    unique = list(dict.fromkeys(values))
    for start in range(0, len(unique), IN_CHUNK_SIZE):
        yield unique[start : start + IN_CHUNK_SIZE]


def parent_conditions(
    column: InstrumentedAttribute[str | None], parent_ids: Sequence[str | None]
) -> Iterator[ColumnElement[bool]]:
    """WHERE clauses covering `parent_ids` in bounded chunks of ascending ids (so per-chunk `ORDER BY column`
    results concatenate in global order); `None` matches the Drive root and comes first."""
    ids = sorted({parent_id for parent_id in parent_ids if parent_id is not None})
    include_root = len(ids) < len(parent_ids)
    groups = list(chunks(ids)) or [[]]
    for index, group in enumerate(groups):
        clauses: list[ColumnElement[bool]] = [column.in_(group)] if group else []
        if include_root and index == 0:
            clauses.append(column.is_(None))
        if clauses:
            yield or_(*clauses)
