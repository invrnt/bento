"""Which processes follow the persisted smart search status at run time instead of the provider they started with
(bug 1 of the 2026-11-26 real-model exit check). The wiring over SQLite is in
`tests/integration/embeddings/test_live_smart_search_wiring.py`."""

from __future__ import annotations

import pytest

from bento.application.ingestion import LiveIndexingPolicy
from bento.domain.settings_registry import embeddings_provider_choices
from bento.domain.smart_search import follows_smart_search_status


@pytest.mark.parametrize(
    ("provider", "locked", "platform", "follows"),
    [
        ("disabled", False, "auto", True),
        ("managed", False, "auto", True),
        ("managed", True, "auto", True),
        ("disabled", True, "auto", False),  # the environment pins it off
        ("custom", False, "auto", False),
        ("mock", False, "auto", False),
        ("disabled", False, "android", False),  # D6: no managed smart search on Android
    ],
)
def test_who_follows_the_status(provider: str, locked: bool, platform: str, follows: bool) -> None:
    offered = embeddings_provider_choices(platform)
    assert follows_smart_search_status(provider, locked=locked, offered=offered) is follows


def test_the_upload_policy_follows_the_live_provider() -> None:
    provider = ["disabled"]
    policy = LiveIndexingPolicy(ocr_provider=lambda: "disabled", embeddings_provider=lambda: provider[0])

    assert policy.current().embeddings is False
    provider[0] = "managed"
    assert policy.current().embeddings is True
    assert policy.current().ocr is False
