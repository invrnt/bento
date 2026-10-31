"""Fixtures for the multi-process end-to-end journeys (`-m e2e`)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.harness import World, relay_double

_FAILED_JOURNEYS: dict[str, str] = {}


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "e2e: multi-process journeys against the fake Telegram cloud")
    config.addinivalue_line("markers", "incremental: later tests in the class are skipped once one fails")


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
