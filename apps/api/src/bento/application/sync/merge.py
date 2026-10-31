"""Deterministic merge rules that need more than per-field last-writer-wins."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def find_folder_cycle(start: str, parent_of: Callable[[str], str | None], *, limit: int = 100_000) -> tuple[str, ...] | None:
    """Folders on the parent loop reachable from `start`, or None when the chain ends at the root."""
    path: list[str] = []
    position: dict[str, int] = {}
    current: str | None = start
    while current is not None and len(path) <= limit:
        if current in position:
            return tuple(path[position[current] :])
        position[current] = len(path)
        path.append(current)
        current = parent_of(current)
    return None


def cycle_breaker(cycle: tuple[str, ...], parent_clocks: Mapping[str, str]) -> str:
    """The folder that moves to the root: the one whose `parent_id` was written last (HLC, then id).

    Every device sees the same parent values and clocks on the loop once the same ops are applied, so they
    all pick the same folder regardless of the order in which they received the moves.
    """
    return max(cycle, key=lambda folder_id: (parent_clocks.get(folder_id, ""), folder_id))
