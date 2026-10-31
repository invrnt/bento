from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.sync.support import SyncClock, Trio, make_trio


@pytest.fixture
def trio(tmp_path: Path) -> Trio:
    return make_trio(tmp_path, SyncClock())
