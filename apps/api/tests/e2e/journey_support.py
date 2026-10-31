"""HTTP-level helpers shared by the end-to-end journeys."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from bento.adapters.fake_telegram import FakeTelegramCloud
from bento.domain.vault import VaultChannelRole, parse_channel_marker
from tests.e2e.harness import Device, DeviceError, World, wait_until

# Large enough for several Range slices, recognizable if it ever leaks to the cloud in plaintext.
DOCUMENT_BYTES = b"".join(f"factura e2e linea {index:05d} total 123.45 COP\n".encode() for index in range(200))

PHOTO_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00"
    b"\xff\xdb\x00C\x00"
    + (b"\x08" * 64)
    + b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    b"\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08"
    b"\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xbf\xff\xd9"
)

TERMINAL_PAIRING_STATES = {"completed", "rejected", "failed", "expired", "cancelled"}


def unique_bytes(label: str, size: int = 4096) -> bytes:
    seed = hashlib.sha256(label.encode()).digest()
    return (label.encode() + b"\n" + seed * (size // len(seed) + 1))[:size]


# Fake cloud inspection --------------------------------------------------------------------------


def cloud(world: World) -> FakeTelegramCloud:
    return FakeTelegramCloud(world.cloud_dir)


def vault_channels(world: World) -> dict[str, Any]:
    channels: dict[str, Any] = {}
    for chat in cloud(world).dialogs():
        marker = parse_channel_marker(chat.about)
        if marker is not None:
            channels[marker[0].value] = chat
    return channels


def channel_id(world: World, role: VaultChannelRole) -> int:
    return int(vault_channels(world)[role.value].id)


def files_channel_parts(world: World) -> dict[int, bytes]:
    """Message id → stored document bytes of every part in the Files channel."""
    chat_id = channel_id(world, VaultChannelRole.FILES)
    fake = cloud(world)
    _, messages = fake.read_chat(chat_id)
    parts: dict[int, bytes] = {}
    for message in messages:
        if message.media is None:
            continue
        path = fake.document_path(chat_id, message.id)
        if Path(path).is_file():
            parts[message.id] = Path(path).read_bytes()
    return parts


# Jobs and uploads -------------------------------------------------------------------------------


def asset_jobs(device: Device, asset_id: str, job_type: str) -> list[dict[str, Any]]:
    return [job for job in device.jobs(limit=100) if job["asset_id"] == asset_id and job["type"] == job_type]


def wait_for_remote_upload(device: Device, asset_id: str, *, timeout: float = 40.0) -> list[dict[str, Any]]:
    """Every `remote_upload` job of the asset (at least the original's) has succeeded."""

    def done() -> list[dict[str, Any]] | None:
        jobs = asset_jobs(device, asset_id, "remote_upload")
        failed = [job for job in jobs if job["status"] == "failed"]
        if failed:
            raise DeviceError(f"{device.name}: remote_upload failed for {asset_id}: {failed}")
        if jobs and all(job["status"] == "succeeded" for job in jobs):
            return jobs
        return None

    return wait_until(done, timeout=timeout, message=f"{device.name} remote_upload of {asset_id}")


def assert_ranged_content(device: Device, asset_id: str, content: bytes, *, start: int, end: int) -> None:
    response = device.request(
        "GET", f"/assets/{asset_id}/content", headers={"Range": f"bytes={start}-{end}"}, expect=206
    )
    assert response.content == content[start : end + 1]
    assert response.headers["content-range"] == f"bytes {start}-{end}/{len(content)}"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-disposition"].startswith("inline")


# Vault and pairing ------------------------------------------------------------------------------


def wait_for_vault_ready(device: Device, *, timeout: float = 40.0) -> dict[str, Any]:
    def ready() -> dict[str, Any] | None:
        status = device.get("/vault")
        return status if status["state"] == "ready" else None

    return wait_until(ready, timeout=timeout, message=f"{device.name} vault ready")


def wait_for_pairing(device: Device, pairing_id: str, states: set[str], *, timeout: float = 30.0) -> dict[str, Any]:
    def reached() -> dict[str, Any] | None:
        pairing = device.get(f"/pairing/{pairing_id}")
        if pairing["state"] in states:
            return pairing
        if pairing["state"] in TERMINAL_PAIRING_STATES:
            raise DeviceError(f"{device.name} pairing {pairing_id} ended as {pairing['state']}: {pairing['error']}")
        return None

    return wait_until(reached, timeout=timeout, message=f"{device.name} pairing in {sorted(states)}")


def pair_over_relay(host: Device, guest: Device) -> tuple[dict[str, Any], dict[str, Any]]:
    """Host shows a code; the guest types it; both see the same emojis; the host approves; both complete."""
    hosted = host.post("/pairing/host")
    assert hosted["role"] == "host" and hosted["transport"] == "relay" and hosted["state"] == "waiting", hosted
    assert hosted["code"] and hosted["link"].startswith("bento://join?v=1&c=") and hosted["qr"]["rows"]

    joined = guest.post("/pairing/join", {"code": hosted["code"]})
    assert joined["role"] == "guest" and joined["code"] is None

    host_view = wait_for_pairing(host, hosted["id"], {"awaiting_approval"})
    guest_view = wait_for_pairing(guest, joined["id"], {"awaiting_approval"})
    assert host_view["sas"] and len(host_view["sas"]) == 4
    assert host_view["sas"] == guest_view["sas"]
    assert host_view["peer"]["platform"] in {"linux", "macos", "windows", "other"}

    host.post(f"/pairing/{hosted['id']}/approve")
    done_host = wait_for_pairing(host, hosted["id"], {"completed"}, timeout=40)
    done_guest = wait_for_pairing(guest, joined["id"], {"completed"}, timeout=40)
    return done_host, done_guest


# Library convergence ----------------------------------------------------------------------------


def library_snapshot(device: Device) -> dict[str, Any]:
    """What the user sees: folders (name), assets (name, folder, favorite), albums, and the trash."""
    folders: dict[str, str] = {}
    assets: dict[str, tuple[str, str | None, bool]] = {}
    pending: list[str | None] = [None]
    while pending:
        folder_id = pending.pop()
        for item in device.drive_items(folder_id):
            if item["type"] == "folder":
                folders[item["folder"]["id"]] = item["folder"]["name"]
                pending.append(item["folder"]["id"])
            else:
                asset = item["asset"]
                assets[asset["id"]] = (asset["filename"], asset["folder_id"], asset["favorite"])
    for group in device.get("/photos/timeline")["groups"]:
        for asset in group["assets"]:
            assets[asset["id"]] = (asset["filename"], asset["folder_id"], asset["favorite"])
    albums = {
        album["id"]: (album["title"], tuple(sorted(album["asset_ids"])))
        for album in device.get("/photos/albums")["items"]
    }
    trash = {item["id"]: item["name"] for item in device.get("/trash")["items"]}
    return {"folders": folders, "assets": assets, "albums": albums, "trash": trash}


def wait_for_convergence(
    first: Device,
    second: Device,
    condition: Any = None,
    *,
    timeout: float = 40.0,
) -> dict[str, Any]:
    """Both devices show the same library (and `condition(snapshot)` holds); returns the snapshot."""
    shots: dict[str, Any] = {}

    def converged() -> dict[str, Any] | None:
        shots["first"], shots["second"] = library_snapshot(first), library_snapshot(second)
        if shots["first"] != shots["second"]:
            return None
        if condition is not None and not condition(shots["first"]):
            return None
        return shots["first"]

    return wait_until(
        converged,
        timeout=timeout,
        interval=0.5,
        message=lambda: f"{first.name}/{second.name} convergence: {shots.get('first')} vs {shots.get('second')}",
    )


def library_names(device: Device) -> list[str]:
    return [name for name, _, _ in library_snapshot(device)["assets"].values()]


def named_asset(device: Device, filename: str) -> str | None:
    for asset_id, (name, _, _) in library_snapshot(device)["assets"].items():
        if name == filename:
            return asset_id
    return None


def wait_for_named_asset(device: Device, filename: str, *, timeout: float = 30.0) -> str:
    return wait_until(lambda: named_asset(device, filename), timeout=timeout, message=f"{filename} on {device.name}")


def assert_absent_for(device: Device, filename: str, *, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        assert named_asset(device, filename) is None, f"{filename} unexpectedly reached {device.name}"
        time.sleep(0.5)


def write_settled(path: Path, content: bytes) -> None:
    """A file copied with its original timestamp (older than the backup settle window)."""
    path.write_bytes(content)
    past = time.time() - 60
    os.utime(path, (past, past))


def vault_header(world: World) -> dict[str, Any]:
    """The plaintext vault header pinned in the Sync channel."""
    sync_id = channel_id(world, VaultChannelRole.SYNC)
    chat, _ = cloud(world).read_chat(sync_id)
    assert chat.pinned_message_id is not None
    pinned = cloud(world).message(sync_id, chat.pinned_message_id)
    assert pinned is not None and pinned.text
    return dict(json.loads(pinned.text))
