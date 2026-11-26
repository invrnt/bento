from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "real_model: runs a real llama-server and GGUF model from local paths (opt-in, skipped by default)",
    )
