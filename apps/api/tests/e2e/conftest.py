"""Fixtures for the multi-process end-to-end journeys.

They take about two minutes, so the default run deselects them. Run them with any of
`uv run pytest -m e2e`, `uv run pytest tests/e2e` or `BENTO_E2E=1 uv run pytest`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.harness import World, relay_double

_FAILED_JOURNEYS: dict[str, str] = {}


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "e2e: multi-process journeys against the fake Telegram cloud")
    config.addinivalue_line("markers", "incremental: later tests in the class are skipped once one fails")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _e2e_requested(config):
        return
    selected = [item for item in items if item.get_closest_marker("e2e") is None]
    if len(selected) != len(items):
        config.hook.pytest_deselected(items=[item for item in items if item.get_closest_marker("e2e") is not None])
        items[:] = selected


def _e2e_requested(config: pytest.Config) -> bool:
    if "e2e" in (config.option.markexpr or "") or os.environ.get("BENTO_E2E") == "1":
        return True
    here = Path(__file__).resolve().parent
    for arg in config.args:
        target = (config.invocation_params.dir / arg.split("::", 1)[0]).resolve()
        if target == here or here in target.parents:
            return True
    return False


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Journeys of an `incremental` class build on each other: skip the rest once one fails."""
    if item.get_closest_marker("incremental") is None or item.cls is None:
        return
    failed = _FAILED_JOURNEYS.get(item.cls.__qualname__)
    if failed is not None:
        pytest.skip(f"depends on {failed}, which failed")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Any:
    report = yield
    if report.failed and call.when == "call":
        if item.get_closest_marker("incremental") is not None and item.cls is not None:
            _FAILED_JOURNEYS.setdefault(item.cls.__qualname__, item.name)
        world = getattr(item, "funcargs", {}).get("world")
        if isinstance(world, World):
            report.sections.append(("device logs", world.logs()))
    return report


@pytest.fixture(scope="module")
def relay_url() -> Iterator[str]:
    with relay_double() as url:
        yield url


@pytest.fixture(scope="module")
def world_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("e2e-world")
