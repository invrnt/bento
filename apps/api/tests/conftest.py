"""Shared test setup.

API tests talk to the app the way the Bento web client does: a loopback `Host` and the
`X-Bento-Client: web` header that the headless request guard requires on unsafe methods. Tests about
the guard itself pass their own `base_url` and `headers`.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from starlette.testclient import TestClient

WEB_CLIENT_BASE_URL = "http://127.0.0.1"
WEB_CLIENT_HEADERS = {"X-Bento-Client": "web"}


@pytest.fixture(autouse=True)
def _web_client_defaults(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original = TestClient.__init__

    def init(self: TestClient, app: Any, base_url: str = WEB_CLIENT_BASE_URL, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("headers", dict(WEB_CLIENT_HEADERS))
        original(self, app, base_url, *args, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", init)
    yield
