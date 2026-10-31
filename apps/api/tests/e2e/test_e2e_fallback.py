"""Journey 22: the relay is unreachable, so the new device asks for access through the Sync channel."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.e2e.harness import World, free_port, wait_until
from tests.e2e.journey_support import (
    unique_bytes,
    wait_for_named_asset,
    wait_for_pairing,
    wait_for_remote_upload,
    wait_for_vault_ready,
)

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    # Nothing listens on this port: the configured relay is unavailable.
    world = World(tmp_path_factory.mktemp("e2e-fallback"), relay_url=f"ws://127.0.0.1:{free_port()}")
    try:
        yield world
    finally:
        world.stop()


def test_22_relay_unavailable_pairs_through_the_sync_channel(world: World) -> None:
    a = world.device("a")
    a.sign_in_with_qr()
    a.post("/vault")
    content = unique_bytes("respaldo-fallback")
    document = a.upload("fallback.txt", content, "text/plain")
    wait_for_remote_upload(a, document["id"])

    unavailable = a.request("POST", "/pairing/host", expect=(409, 502, 503))
    assert unavailable.json()["error"]["code"] == "pairing_relay_unavailable"

    b = world.device("b")
    b.sign_in_with_qr()
    assert b.get("/vault")["state"] == "locked"
    asked = b.post("/pairing/request")
    assert asked["role"] == "guest" and asked["transport"] == "telegram" and asked["code"] is None

    request = wait_until(lambda: a.get("/pairing/requests")["items"], timeout=30, message="pair_request on A")[0]
    assert request["platform"] in {"linux", "macos", "windows", "other"} and request["device_name"]
    reviewed = a.post(f"/pairing/requests/{request['id']}/review")
    assert reviewed["role"] == "host" and reviewed["transport"] == "telegram"
    assert reviewed["sas"] and len(reviewed["sas"]) == 4
    guest_view = wait_for_pairing(b, asked["id"], {"awaiting_approval"})
    assert guest_view["sas"] == reviewed["sas"]

    a.post(f"/pairing/requests/{request['id']}/approve")
    wait_for_pairing(a, reviewed["id"], {"completed"}, timeout=40)
    wait_for_pairing(b, asked["id"], {"completed"}, timeout=40)
    wait_for_vault_ready(b)
    assert wait_for_named_asset(b, "fallback.txt", timeout=40) == document["id"]
    assert b.request("GET", f"/assets/{document['id']}/download").content == content
    assert len(a.get("/devices")["items"]) == 2
    assert not a.get("/pairing/requests")["items"]


def test_22_rejected_request_leaves_the_device_locked(world: World, tmp_path: Path) -> None:
    a = world.devices["a"]
    c = world.device("c")
    c.sign_in_with_qr()
    asked = c.post("/pairing/request")
    request = wait_until(lambda: a.get("/pairing/requests")["items"], timeout=30, message="pair_request on A")[0]
    a.post(f"/pairing/requests/{request['id']}/reject")
    wait_for_pairing(c, asked["id"], {"rejected"}, timeout=30)
    assert c.get("/vault")["state"] == "locked"
