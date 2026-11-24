"""Cooperative deadlines for bounded worker runs (Android background work, `engine.run_worker_until`).

The worker sets a deadline around each job; long-running handlers call `check_safe_boundary()` at points where
stopping loses no durable progress (between upload parts, between backup files). Past the deadline it raises
`WorkBudgetExceeded`, and the worker returns the job to the queue without consuming an attempt. The deadline is
a context variable, so it follows the job into tasks and `asyncio.to_thread` calls.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_deadline: ContextVar[tuple[float, Callable[[], float]] | None] = ContextVar("bento_work_deadline", default=None)


class WorkBudgetExceeded(Exception):
    """The run's deadline passed at a safe boundary; the current job must be requeued, not failed."""


@contextmanager
def work_deadline(deadline: float | None, *, clock: Callable[[], float] = time.monotonic) -> Iterator[None]:
    """Run the block under `deadline` (a `clock()` value); None means unbounded."""
    token = _deadline.set(None if deadline is None else (deadline, clock))
    try:
        yield
    finally:
        _deadline.reset(token)


def deadline_passed() -> bool:
    current = _deadline.get()
    return current is not None and current[1]() >= current[0]


def check_safe_boundary() -> None:
    if deadline_passed():
        raise WorkBudgetExceeded()
