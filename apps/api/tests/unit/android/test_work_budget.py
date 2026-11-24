from __future__ import annotations

import asyncio

import pytest

from bento.application.work_budget import WorkBudgetExceeded, check_safe_boundary, deadline_passed, work_deadline


def test_boundaries_raise_only_past_the_deadline_and_follow_threads() -> None:
    now = [100.0]
    check_safe_boundary()  # unbounded outside a run
    with work_deadline(105.0, clock=lambda: now[0]):
        check_safe_boundary()
        now[0] = 105.0
        assert deadline_passed()
        with pytest.raises(WorkBudgetExceeded):
            check_safe_boundary()

        async def in_thread() -> bool:
            return await asyncio.to_thread(deadline_passed)

        assert asyncio.run(in_thread()) is True
    assert not deadline_passed()
    with work_deadline(None):
        check_safe_boundary()
