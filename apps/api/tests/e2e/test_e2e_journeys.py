"""Critical journeys 20-29 (`orchestration/testing/critical-journeys.md`) across real processes.

One simulated Telegram account (fake cloud directory) and the relay double are shared by devices A, B and C,
each running the real API and worker entrypoints with its own data directory. The journeys build on each
other in file order (first run → pairing → convergence → backup → inbox → removal → recovery).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bento.adapters.fake_telegram.cloud import DocumentUpload
from bento.domain.vault import VaultChannelRole
from tests.e2e.harness import Device, World, sigterm_as_interrupt, wait_until
from tests.e2e.journey_support import (
    DOCUMENT_BYTES,
    PHOTO_BYTES,
    asset_jobs,
    assert_absent_for,
    assert_ranged_content,
    channel_id,
    cloud,
    files_channel_parts,
    library_names,
    library_snapshot,
    named_asset,
    pair_over_relay,
    unique_bytes,
    wait_for_convergence,
    wait_for_remote_upload,
    vault_channels,
    vault_header,
    wait_for_named_asset,
    wait_for_vault_ready,
    write_settled,
)

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def world(world_root: Path, relay_url: str) -> Iterator[World]:
    world = World(world_root, relay_url=relay_url)
    with sigterm_as_interrupt():
        try:
            yield world
        finally:
            world.stop()


@pytest.fixture(scope="module")
def story() -> SimpleNamespace:
    """Ids and secrets carried from one journey to the next."""
    return SimpleNamespace()


@pytest.mark.incremental
class TestTelegramFirstJourneys:
    def test_20_first_run_qr_vault_upload_and_streaming(self, world: World, story: SimpleNamespace) -> None:
        a = world.device("a")
        assert a.get("/account")["step"] == "signed_out"
        assert a.get("/vault")["state"] == "signed_out"

        account = a.sign_in_with_qr()
        assert account["account"]["display_name"] == "Ana Demo"
        assert a.get("/vault")["state"] == "no_vault"

        created = a.post("/vault")
        assert created["vault"]["state"] == "ready"
        assert created["vault"]["devices_count"] == 1
        assert len(created["recovery_code"].split("-")) >= 6
        assert created["recovery_qr"]["rows"]
        story.vault_id = created["vault"]["vault_id"]
        story.recovery_code = created["recovery_code"]
        assert any(item["kind"] == "recovery_kit" for item in a.get("/activity")["attention"])
        wrong_group = "ZZZZ" if not created["recovery_code"].endswith("ZZZZ") else "YYYY"
        mismatch = a.request("POST", "/vault/recovery-code/confirm", json={"last_group": wrong_group}, expect=400)
        assert mismatch.json()["error"]["code"] == "recovery_group_mismatch"
        saved = a.post("/vault/recovery-code/confirm", {"last_group": created["recovery_code"].split("-")[-1]})
        assert saved["recovery_kit_saved"] is True
        assert not any(item["kind"] == "recovery_kit" for item in a.get("/activity")["attention"])

        channels = vault_channels(world)
        assert sorted(channels) == ["files", "inbox", "sync"]
        assert all(chat.muted for chat in channels.values())
        assert set(cloud(world).folders()["Bento"]) == {chat.id for chat in channels.values()}

        document = a.upload("factura-e2e.txt", DOCUMENT_BYTES, "text/plain")
        photo = a.upload("playa-e2e.jpg", PHOTO_BYTES, "image/jpeg", mode="photos")
        story.document_id, story.photo_id = document["id"], photo["id"]

        wait_for_remote_upload(a, document["id"])
        wait_for_remote_upload(a, photo["id"])
        parts = files_channel_parts(world)
        assert len(parts) >= 2
        for part in parts.values():
            assert DOCUMENT_BYTES[:64] not in part and PHOTO_BYTES[16:80] not in part

        assert a.request("GET", f"/assets/{document['id']}/download").content == DOCUMENT_BYTES
        assert_ranged_content(a, document["id"], DOCUMENT_BYTES, start=100, end=1099)
        assert_ranged_content(a, photo["id"], PHOTO_BYTES, start=0, end=31)

    def test_21_second_device_joins_by_code_over_the_relay(self, world: World, story: SimpleNamespace) -> None:
        a = world.devices["a"]
        # Manual login: B's own QR is never auto-approved, so only the host's approval can sign it in.
        b = world.device("b", manual_login=True)
        assert b.get("/account")["step"] == "signed_out"
        assert b.get("/vault")["state"] == "signed_out"

        pair_over_relay(a, b)

        assert b.get("/account")["step"] == "authorized"
        status = wait_for_vault_ready(b)
        assert status["vault_id"] == story.vault_id
        wait_until(
            lambda: {story.document_id, story.photo_id} <= set(b.drive_assets()) | timeline_ids(b),
            timeout=40,
            message="A's library on B",
        )
        assert b.request("GET", f"/assets/{story.document_id}/download").content == DOCUMENT_BYTES
        assert_ranged_content(b, story.document_id, DOCUMENT_BYTES, start=2000, end=2999)

        devices = a.get("/devices")["items"]
        assert len([item for item in devices if item["removed_at"] is None]) == 2
        story.device_b_id = next(item["id"] for item in devices if not item["current"])

        b.restart()  # the Telegram session and the keyring survive a restart
        assert b.get("/account")["step"] == "authorized"
        assert wait_for_vault_ready(b)["vault_id"] == story.vault_id
        assert b.request("GET", f"/assets/{story.photo_id}/download").content == PHOTO_BYTES

    def test_23_concurrent_edits_delete_restore_and_purge_converge(self, world: World, story: SimpleNamespace) -> None:
        a, b = world.devices["a"], world.devices["b"]
        folder = a.post("/drive/folders", {"name": "Facturas"})
        wait_until(lambda: folder["id"] in b.drive_folders(), timeout=30, message="A's folder on B")

        # Interleaved edits on both devices without waiting for sync in between.
        a.post(f"/drive/items/{story.document_id}/move", {"folder_id": folder["id"]})
        b.patch(f"/drive/items/{story.document_id}", {"name": "factura-renombrada.txt"})
        b.post(f"/photos/{story.photo_id}/favorite", {"favorite": True})
        album = a.post("/photos/albums", {"title": "Vacaciones"})
        a.post(f"/photos/albums/{album['id']}/items", {"asset_id": story.photo_id})
        a.patch(f"/drive/folders/{folder['id']}", {"name": "Facturas 2026"})
        b.patch(f"/drive/folders/{folder['id']}", {"name": "Facturas Hogar"})
        story.folder_id, story.album_id = folder["id"], album["id"]

        snapshot = wait_for_convergence(a, b)
        assert snapshot["folders"][folder["id"]] in {"Facturas 2026", "Facturas Hogar"}
        assert snapshot["assets"][story.document_id] == ("factura-renombrada.txt", folder["id"], False)
        assert snapshot["assets"][story.photo_id][2] is True
        assert snapshot["albums"][album["id"]] == ("Vacaciones", (story.photo_id,))
        assert b.request("GET", f"/photos/albums/{album['id']}").json()["asset_ids"] == [story.photo_id]
        b.delete(f"/photos/albums/{album['id']}/items/{story.photo_id}")
        wait_for_convergence(a, b, lambda shot: shot["albums"][album["id"]] == ("Vacaciones", ()))

        a.delete(f"/assets/{story.document_id}")
        snapshot = wait_for_convergence(a, b, lambda shot: story.document_id in shot["trash"])
        assert story.document_id not in snapshot["assets"]

        assert b.post("/trash/restore", {"ids": [story.document_id]})["restored"] == 1
        snapshot = wait_for_convergence(a, b, lambda shot: story.document_id in shot["assets"])
        assert snapshot["assets"][story.document_id][1] == folder["id"] and not snapshot["trash"]

        before = set(files_channel_parts(world))
        doomed = b.upload("borrar-e2e.txt", unique_bytes("borrar"), "text/plain")
        wait_for_remote_upload(b, doomed["id"])
        doomed_parts = set(files_channel_parts(world)) - before
        assert doomed_parts
        wait_until(lambda: doomed["id"] in a.drive_assets(), timeout=30, message="B's upload on A")
        b.delete(f"/assets/{doomed['id']}")
        wait_for_convergence(a, b, lambda shot: doomed["id"] in shot["trash"])
        purged = a.post("/trash/purge", {"ids": [doomed["id"]]})
        assert purged["purged"] == 1, purged
        wait_until(
            lambda: not (doomed_parts & set(files_channel_parts(world))),
            timeout=30,
            message="purged parts deleted from the Files channel",
        )
        snapshot = wait_for_convergence(a, b, lambda shot: doomed["id"] not in shot["trash"])
        assert doomed["id"] not in snapshot["assets"]
        assert a.asset(doomed["id"]) is None and b.asset(doomed["id"]) is None

    def test_26_folder_backup_reaches_the_other_device_and_pause_stops_it(
        self, world: World, story: SimpleNamespace
    ) -> None:
        a, b = world.devices["a"], world.devices["b"]
        source_dir = world.root / "a-pictures"
        source_dir.mkdir()
        write_settled(source_dir / "existente.txt", unique_bytes("existente"))

        source = a.post("/backup/sources", {"path": str(source_dir), "label": "Fotos de A"})
        assert source["enabled"] and source["label"] == "Fotos de A"
        existing = wait_for_named_asset(a, "existente.txt")
        wait_for_remote_upload(a, existing)

        write_settled(source_dir / "nueva.txt", unique_bytes("nueva"))
        added = wait_for_named_asset(a, "nueva.txt")
        wait_for_named_asset(b, "nueva.txt")
        assert b.request("GET", f"/assets/{added}/download").content == unique_bytes("nueva")

        policy = a.patch("/backup/policy", {"paused": True})
        assert policy["paused"] and policy["effective_paused"]
        write_settled(source_dir / "en-pausa.txt", unique_bytes("en-pausa"))
        a.post(f"/backup/sources/{source['id']}/scan")
        assert_absent_for(a, "en-pausa.txt", seconds=5)

        (source_dir / "existente.txt").unlink()
        on_battery = a.patch("/backup/policy", {"paused": False}) and a.post("/backup/power", {"on_battery": True})
        assert on_battery["pause_on_battery"] and on_battery["on_battery"] and on_battery["effective_paused"]
        assert not a.post("/backup/power", {"on_battery": False})["effective_paused"]
        wait_for_named_asset(a, "en-pausa.txt")
        assert existing in library_snapshot(a)["assets"], "source deletions never delete from Bento"
        story.backup_asset_id = added

    def test_27_inbox_document_is_imported_and_acknowledged(self, world: World, story: SimpleNamespace) -> None:
        a, b = world.devices["a"], world.devices["b"]
        inbox = channel_id(world, VaultChannelRole.INBOX)
        content = unique_bytes("recibo-bandeja")
        message = cloud(world).post_message(
            inbox, document=DocumentUpload(content, "recibo-bandeja.txt", "text/plain")
        )

        imported = wait_for_named_asset(a, "recibo-bandeja.txt", timeout=40)
        wait_until(
            lambda: "✅" in (cloud(world).message(inbox, message.id) or message).reactions,
            timeout=20,
            message="✅ reaction on the Inbox message",
        )
        wait_for_named_asset(b, "recibo-bandeja.txt")
        assert a.request("GET", f"/assets/{imported}/download").content == content
        assert len([name for name in library_names(a) if name == "recibo-bandeja.txt"]) == 1

    def test_28_share_to_a_chat_and_import_from_saved_messages(self, world: World, story: SimpleNamespace) -> None:
        a, b = world.devices["a"], world.devices["b"]
        chats = a.get("/telegram/chats")["items"]
        assert chats[0]["kind"] == "saved" and not any(chat["title"].startswith("Bento") for chat in chats)
        carlos = next(chat for chat in chats if chat["title"] == "Carlos Ruiz")
        before = cloud(world).last_message_id(carlos["id"])
        assert a.post(f"/assets/{story.backup_asset_id}/share/telegram", {"chat_id": carlos["id"]}) == {"sent": True}
        shared = cloud(world).last_message_id(carlos["id"])
        assert shared > before
        assert Path(cloud(world).document_path(carlos["id"], shared)).read_bytes() == unique_bytes("nueva")

        saved = chats[0]["id"]
        media = a.get("/telegram/import/media", params={"chat_id": saved, "kind": "all"})["items"]
        assert media
        names = {item["filename"] for item in media}
        for _ in range(2):  # importing twice adds nothing the second time
            queued = a.post("/telegram/import", {"chat_id": saved, "all": True})
            assert queued["job_id"]
            wait_until(lambda: names <= set(library_names(a)), timeout=30, message="Saved Messages media on A")
        wait_until(
            lambda: all(
                job["status"] == "succeeded" for job in a.jobs(limit=100) if job["type"] == "telegram_import"
            ),
            timeout=30,
            message="imports finished",
        )
        imported = [name for name in library_names(a) if name in names]
        assert sorted(imported) == sorted(names), imported
        wait_until(lambda: names <= set(library_names(b)), timeout=30, message="imported media on B")

    def test_25_removing_a_device_rotates_keys_and_forces_a_new_kit(self, world: World, story: SimpleNamespace) -> None:
        a, b = world.devices["a"], world.devices["b"]
        epoch_before = vault_header(world)["current_epoch"]

        removal = a.delete(f"/devices/{story.device_b_id}")
        assert removal["device"]["id"] == story.device_b_id and removal["device"]["removed_at"]
        assert removal["telegram_session_closed"] is True
        assert removal["recovery_code"] and removal["recovery_code"] != story.recovery_code
        assert a.post("/vault/recovery-code/verify", {"recovery_code": story.recovery_code}) == {"valid": False}
        assert a.post("/vault/recovery-code/verify", {"recovery_code": removal["recovery_code"]}) == {"valid": True}
        story.recovery_code = removal["recovery_code"]
        assert story.device_b_id not in {item["id"] for item in a.get("/devices")["items"]}
        wait_until(lambda: vault_header(world)["current_epoch"] > epoch_before, timeout=20, message="key rotation")

        wait_until(lambda: b.get("/account")["step"] == "signed_out", timeout=30, message="B signed out")
        secret = a.upload("despues-de-quitar-b.txt", unique_bytes("despues"), "text/plain")
        wait_for_remote_upload(a, secret["id"])
        assert_absent_for(b, "despues-de-quitar-b.txt", seconds=5)
        assert b.get("/sync/status")["state"] in {"paused", "error", "offline", "disabled"}
        story.after_removal_id = secret["id"]

        # Signing in to Telegram again does not give the removed device the new keys: it pulls the new
        # batches but cannot open them. (It still reports `ready`/`idle`; reported as a UX gap.)
        pulled_before = b.get("/sync/status")["last_pull_at"]
        b.sign_in_with_qr()
        wait_until(
            lambda: (status := b.get("/sync/status"))["state"] == "idle" and status["last_pull_at"] != pulled_before,
            timeout=30,
            message="B pulls again after signing in",
        )
        assert named_asset(b, "despues-de-quitar-b.txt") is None
        assert b.asset(secret["id"]) is None

    def test_24_fresh_device_restores_the_library_with_the_recovery_code(
        self, world: World, story: SimpleNamespace
    ) -> None:
        a = world.devices["a"]
        c = world.device("c")
        c.sign_in_with_qr()
        assert c.get("/vault")["state"] == "locked"
        bogus = "AAAA-BBBB-CCCC-DDDD-EEEE-FFFF-GGGG-HHHH-JJJJ"
        wrong = c.request("POST", "/vault/unlock", json={"recovery_code": bogus}, expect=400)
        assert wrong.json()["error"]["code"] == "recovery_code_invalid"
        assert "AAAA" not in wrong.text

        unlocked = c.post("/vault/unlock", {"recovery_code": story.recovery_code})
        assert unlocked["state"] in {"ready", "bootstrapping"} and unlocked["vault_id"] == story.vault_id
        wait_for_vault_ready(c)
        snapshot = wait_for_convergence(a, c, lambda shot: story.after_removal_id in shot["assets"], timeout=60)
        assert story.document_id in snapshot["assets"] and story.album_id in snapshot["albums"]
        assert c.request("GET", f"/assets/{story.document_id}/download").content == DOCUMENT_BYTES
        devices = a.get("/devices")["items"]
        assert len(devices) == 2 and sum(not item["current"] for item in devices) == 1  # A and C; B stays removed

    def test_29_flood_wait_and_offline_show_a_calm_status_and_resume(
        self, world: World, story: SimpleNamespace
    ) -> None:
        a, c = world.devices["a"], world.devices["c"]
        fake = cloud(world)

        fake.inject_fault("flood_wait", seconds=6)
        queued = a.upload("durante-espera.txt", unique_bytes("espera"), "text/plain")
        a.patch(f"/drive/items/{story.photo_id}", {"name": "playa-en-espera.jpg"})
        a.sync_now()
        waiting = wait_until(lambda: sync_state(a, "waiting"), timeout=15, message="A sync waiting")
        assert waiting["waiting_until"] and waiting["error"]["code"] == "telegram_flood_wait"
        activity = a.get("/activity")
        assert activity["summary"] != "offline"
        assert not [item for item in activity["attention"] if item["kind"] in {"sync_error", "upload_failed"}]
        assert all(job["status"] != "failed" for job in asset_jobs(a, queued["id"], "remote_upload"))

        wait_for_remote_upload(a, queued["id"], timeout=40)
        wait_for_convergence(
            a,
            c,
            lambda shot: queued["id"] in shot["assets"] and shot["assets"][story.photo_id][0] == "playa-en-espera.jpg",
        )

        fake.inject_fault("network", seconds=5)
        a.patch(f"/drive/items/{story.document_id}", {"name": "factura-sin-red.txt"})
        a.sync_now()
        wait_until(lambda: sync_state(a, "offline"), timeout=15, message="A sync offline")
        assert a.get("/activity")["summary"] == "offline"
        wait_for_convergence(
            a, c, lambda shot: shot["assets"][story.document_id][0] == "factura-sin-red.txt", timeout=40
        )
        wait_until(lambda: sync_state(a, "idle"), timeout=15, message="A sync idle again")

    def test_26b_new_backup_source_is_watched_without_a_worker_restart(self, world: World) -> None:
        a = world.devices["a"]
        source_dir = world.root / "a-documents"
        source_dir.mkdir()
        a.post("/backup/sources", {"path": str(source_dir), "label": "Documentos de A"})
        time.sleep(1.5)  # the initial scan of the (empty) folder has run
        write_settled(source_dir / "recien-llegado.txt", unique_bytes("recien-llegado"))
        wait_for_named_asset(a, "recien-llegado.txt", timeout=8)


def timeline_ids(device: Device) -> set[str]:
    groups = device.get("/photos/timeline")["groups"]
    return {asset["id"] for group in groups for asset in group["assets"]}


def sync_state(device: Device, state: str) -> dict[str, Any] | None:
    status = device.get("/sync/status")
    return status if status["state"] == state else None
