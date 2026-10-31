"""Edited Sync messages, snapshot digests, op size caps, and clock skew, between devices on the fake cloud.

Every device shares one Telegram account, so a removed device whose session is still alive can edit any Sync
channel post (even replace its document). Bento never edits Sync messages: an edited one is invalid.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from bento.adapters.backup.activity import SQLiteActivitySource
from bento.adapters.fake_telegram import FakeTelegramCloud
from bento.adapters.fake_telegram.cloud import DocumentUpload
from bento.application.activity import ActivityInputs, build_activity
from bento.application.drive import CreateFolderCommand
from bento.application.sync import AssetIndexRecorder, SyncPolicy
from bento.application.sync.asset_index import MAX_INDEX_TEXT_BYTES
from bento.application.sync.keys import build_keys_message
from bento.application.sync.status import SyncStatusService
from bento.domain.activity import AttentionKind
from bento.domain.backup import BackupPolicy
from bento.domain.security import SealPurpose, VaultKeyring
from bento.domain.sync import SyncEntity, SyncMessageKind
from bento.domain.telegram import TelegramMediaKind
from bento.domain.vault import VaultHeader
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import OCRBlockModel
from tests.integration.sync.support import (
    CRYPTO,
    CountingCrypto,
    SyncClock,
    SyncDevice,
    Trio,
    create_vault,
    folder_names,
    join_vault,
    list_sync,
    make_cloud_device,
    make_trio,
    raw_op,
    sealed_batch,
    state_int,
    state_json,
)


def cloud_of(tmp_path: Path) -> FakeTelegramCloud:
    return FakeTelegramCloud(tmp_path / "cloud")


def replace_document(cloud: FakeTelegramCloud, device: SyncDevice, message_id: int, payload: bytes, suffix: str) -> None:
    """What a removed device with a live session can do: edit a Sync post and swap its document."""
    assert device.vault.layout is not None
    cloud.edit_message(
        device.vault.layout.sync_channel_id,
        message_id,
        document=DocumentUpload(payload, f"swapped{suffix}", "application/octet-stream", TelegramMediaKind.DOCUMENT),
    )


def hlc_now(device: SyncDevice, counter: int = 1) -> str:
    return f"{device.clock.now_ms():016d}-{counter:06d}-{device.device_id}"


def count_downloads(device: SyncDevice) -> list[int]:
    """Message ids whose document `device` downloads from now on."""
    downloads: list[int] = []
    original = device.runtime.transport.download_sync_document

    async def counting(layout: Any, message_id: int, **kwargs: Any) -> bytes:
        downloads.append(message_id)
        return await original(layout, message_id, **kwargs)

    device.runtime.transport.download_sync_document = counting  # type: ignore[method-assign]
    return downloads


def status_service(device: SyncDevice) -> SyncStatusService:
    return SyncStatusService(enabled=True, state=device.adapters.state, outbox=device.adapters.outbox, clock=device.clock)


def test_an_edited_batch_is_skipped_counted_and_passed_over(trio: Trio, tmp_path: Path) -> None:
    laptop, desktop, phone = trio
    cloud = cloud_of(tmp_path)

    async def scenario() -> None:
        assert phone.vault.keyring is not None
        folder = await laptop.drive.create_folder(CreateFolderCommand(name="Original"))
        await laptop.push()
        batch_id = [ref for ref in await list_sync(laptop) if ref.kind == SyncMessageKind.BATCH][-1].message_id
        skipped_before = await state_int(desktop, "skipped_messages")

        # The phone still holds the current keys: its replacement opens and parses like a genuine batch.
        evil = sealed_batch(
            phone.device_id,
            phone.vault.keyring,
            raw_op(SyncEntity.FOLDER, folder.id, hlc_now(phone, 5), {"name": "Reescrita"}, device=phone.device_id),
            raw_op(SyncEntity.FOLDER, "folder_planted", hlc_now(phone, 6), {"name": "Plantada"}, device=phone.device_id),
        )
        replace_document(cloud, phone, batch_id, evil, ".bsync")
        [edited] = [ref for ref in await list_sync(desktop) if ref.message_id == batch_id]
        assert edited.edited

        later = await laptop.drive.create_folder(CreateFolderCommand(name="Después"))
        await laptop.push()
        downloads = count_downloads(desktop)
        await desktop.pull()

        assert batch_id not in downloads, "passed over from the listing, never downloaded"
        names = folder_names(desktop)
        assert folder.id not in names and "folder_planted" not in names, "nothing of the edited batch applies"
        assert names[later.id] == "Después"
        assert await state_int(desktop, "skipped_messages") == skipped_before + 1
        assert (await state_json(desktop, "last_skipped"))["reason"] == "edited"
        assert int(await desktop.adapters.state.get_value("last_applied_message_id") or 0) > batch_id

    asyncio.run(scenario())


def test_a_batch_edited_after_it_was_listed_is_refused_at_download(trio: Trio, tmp_path: Path) -> None:
    laptop, desktop, phone = trio
    cloud = cloud_of(tmp_path)

    async def scenario() -> None:
        assert phone.vault.keyring is not None
        folder = await laptop.drive.create_folder(CreateFolderCommand(name="Carrera"))
        await laptop.push()
        transport = desktop.runtime.transport
        listing = transport.list_sync_messages

        async def stale_listing(layout: Any, **kwargs: Any) -> Any:
            refs = await listing(layout, **kwargs)
            for ref in refs:
                if ref.kind == SyncMessageKind.BATCH and not ref.edited:
                    # The edit lands between the listing and the download.
                    replace_document(cloud, phone, ref.message_id, b"BENV" + b"\x00" * 64, ".bsync")
            return refs

        transport.list_sync_messages = stale_listing  # type: ignore[method-assign]
        await desktop.pull()

        assert folder.id not in folder_names(desktop)
        assert (await state_json(desktop, "last_skipped"))["reason"] == "edited"

    asyncio.run(scenario())


def test_an_edited_keys_message_neither_rekeys_nor_removes_a_device(trio: Trio, tmp_path: Path) -> None:
    laptop, desktop, phone = trio
    cloud = cloud_of(tmp_path)

    async def scenario() -> None:
        assert desktop.vault.keyring is not None and desktop.vault.layout is not None
        layout = desktop.vault.layout
        await laptop.device_service.remove(phone.device_id)
        keys_id = [ref for ref in await list_sync(laptop) if ref.kind == SyncMessageKind.KEYS][-1].message_id
        # The removed phone swaps the rotation for one "from itself" that leaves the desktop out.
        forged = VaultKeyring(vault_id=layout.vault_id, current_epoch=2, keys={**desktop.vault.keyring.keys, 2: b"\x07" * 32})
        replace_document(
            cloud,
            phone,
            keys_id,
            build_keys_message(CRYPTO, phone.vault.identity, forged, {phone.device_id: phone.vault.identity.public_key}),
            ".bkeys",
        )

        await desktop.pull()

        assert await desktop.adapters.state.get_value("device_removed") is None
        assert desktop.vault.keyring is not None and desktop.vault.keyring.current_epoch == 1
        assert desktop.vault.keyring_updates == []
        skipped = await state_json(desktop, "last_skipped")
        assert skipped["message_id"] == keys_id and skipped["kind"] == "keys" and skipped["reason"] == "edited"

    asyncio.run(scenario())


def test_an_edited_pinned_header_is_invalid_and_new_devices_replay_the_channel(tmp_path: Path) -> None:
    clock = SyncClock()
    laptop, desktop, _ = make_trio(tmp_path, clock)
    tablet = make_cloud_device(tmp_path, tmp_path / "cloud", "tablet", clock)
    cloud = cloud_of(tmp_path)

    async def scenario() -> None:
        folder = await laptop.drive.create_folder(CreateFolderCommand(name="Antes del snapshot"))
        await laptop.sync()
        context = await laptop.context()
        await laptop.engine.pull(context)
        assert await laptop.engine.maybe_snapshot(context, force=True)
        assert laptop.vault.layout is not None
        layout = laptop.vault.layout
        pinned = cloud.chat(layout.sync_channel_id).pinned_message_id
        assert pinned is not None
        text = await laptop.runtime.transport.read_header_text(layout)
        assert text is not None
        snapshot = VaultHeader.from_json(text).snapshot
        assert snapshot is not None

        # Even an edit that keeps the exact text makes the header invalid: Bento never edits it.
        cloud.edit_message(layout.sync_channel_id, pinned, text=text)

        assert await laptop.runtime.transport.read_header_text(layout) is None
        assert await laptop.vault.read_header() is None
        await desktop.pull()
        assert (await state_json(desktop, "last_skipped"))["reason"] == "edited"
        assert (await state_json(desktop, "last_skipped"))["kind"] == "header"

        downloads = count_downloads(tablet)
        await join_vault(tablet, laptop)
        await tablet.sync()
        assert folder_names(tablet)[folder.id] == "Antes del snapshot", "replayed from the start of the channel"
        assert snapshot.message_id not in downloads

    asyncio.run(scenario())


def _snapshot_trio(tmp_path: Path) -> tuple[SyncDevice, SyncDevice, SyncDevice, SyncDevice]:
    clock = SyncClock()
    laptop, desktop, phone = make_trio(tmp_path, clock)
    tablet = make_cloud_device(tmp_path, tmp_path / "cloud", "tablet", clock)
    return laptop, desktop, phone, tablet


async def _snapshot(laptop: SyncDevice) -> VaultHeader:
    await laptop.drive.create_folder(CreateFolderCommand(name="En el snapshot"))
    await laptop.sync()
    context = await laptop.context()
    await laptop.engine.pull(context)
    assert await laptop.engine.maybe_snapshot(context, force=True)
    header = await laptop.vault.read_header()
    assert header is not None and header.snapshot is not None and header.snapshot.sha256 is not None
    return header


def test_an_edited_snapshot_is_skipped_and_the_device_replays_the_channel(tmp_path: Path) -> None:
    laptop, _, phone, tablet = _snapshot_trio(tmp_path)
    cloud = cloud_of(tmp_path)

    async def scenario() -> None:
        header = await _snapshot(laptop)
        assert header.snapshot is not None
        replace_document(cloud, phone, header.snapshot.message_id, b"BENV" + b"\x00" * 128, ".bsnap")

        await join_vault(tablet, laptop)
        await tablet.sync()

        assert "En el snapshot" in folder_names(tablet).values()
        skipped = await state_json(tablet, "last_skipped")
        assert skipped["message_id"] == header.snapshot.message_id and skipped["kind"] == "snapshot"
        assert skipped["reason"] == "edited"
        assert await state_int(tablet, "skipped_messages") == 1, "the replay does not count the snapshot again"

    asyncio.run(scenario())


def test_a_snapshot_swapped_without_an_edit_mark_fails_its_digest_and_falls_back(tmp_path: Path) -> None:
    laptop, _, phone, tablet = _snapshot_trio(tmp_path)

    async def scenario() -> None:
        assert phone.vault.keyring is not None
        header = await _snapshot(laptop)
        assert header.snapshot is not None and laptop.vault.layout is not None
        # Telegram itself can serve other bytes for a message without flagging an edit.
        planted = CRYPTO.seal_json(
            phone.vault.keyring,
            SealPurpose.SNAPSHOT,
            {"bento": "sync-snapshot", "v": 1},
            aad=laptop.vault.layout.vault_id.encode(),
        )
        documents = tmp_path / "cloud" / "chats" / str(laptop.vault.layout.sync_channel_id) / "docs"
        (documents / f"{header.snapshot.message_id}.bin").write_bytes(planted)
        crypto = CountingCrypto()
        tablet.engine._crypto = crypto  # type: ignore[assignment]

        await join_vault(tablet, laptop)
        await tablet.sync()

        assert "En el snapshot" in folder_names(tablet).values()
        assert (await state_json(tablet, "last_skipped"))["reason"] == "snapshot_sha256"
        assert planted not in crypto.opened, "the digest is checked before decrypting"

    asyncio.run(scenario())


def test_a_snapshot_pointer_without_a_digest_is_not_trusted(tmp_path: Path) -> None:
    laptop, _, _, tablet = _snapshot_trio(tmp_path)

    async def scenario() -> None:
        header = await _snapshot(laptop)
        assert header.snapshot is not None
        legacy = replace(header.snapshot, sha256=None)
        await laptop.vault.update_header(lambda current: replace(current, snapshot=legacy))
        reread = await laptop.vault.read_header()
        assert reread is not None and reread.snapshot == legacy

        await join_vault(tablet, laptop)
        await tablet.sync()

        assert "En el snapshot" in folder_names(tablet).values()
        assert (await state_json(tablet, "last_skipped"))["reason"] == "snapshot_sha256_missing"

    asyncio.run(scenario())


def test_a_huge_ocr_result_is_cut_to_the_sync_cap_and_reaches_peers(tmp_path: Path) -> None:
    clock = SyncClock()
    cloud = tmp_path / "cloud"
    laptop, desktop = (make_cloud_device(tmp_path, cloud, name, clock) for name in ("laptop", "desktop"))

    async def scenario() -> None:
        await create_vault(laptop)
        await join_vault(desktop, laptop)
        await laptop.sync()
        await desktop.sync()
        await laptop.add_asset("asset_tome", filename="tomo.pdf")
        recorder = AssetIndexRecorder(outbox=laptop.adapters.outbox, hlc=laptop.adapters.hlc, state=laptop.adapters.state)
        page = "palabra " * 40_000  # 320 KB per page, 20 pages: far beyond one op, and beyond the 16 MiB inflate limit
        pages = tuple((number, f"página {number} {page}") for number in range(1, 21))
        await recorder.record_ocr("asset_tome", ocr_text="\n".join(text for _, text in pages) * 4, pdf_pages=pages)
        skipped_before = await state_int(desktop, "skipped_messages")
        published = await laptop.push()
        await desktop.pull()

        assert published >= 1
        assert await state_int(desktop, "skipped_messages") == skipped_before, "peers never drop the op"
        with session_scope(desktop.factory) as session:
            texts = [row.text for row in session.scalars(select(OCRBlockModel).where(OCRBlockModel.asset_id == "asset_tome"))]
        assert texts and texts[0].startswith("página 1 ")
        total = sum(len(json.dumps(text, ensure_ascii=False).encode()) for text in texts)
        assert total <= MAX_INDEX_TEXT_BYTES

    asyncio.run(scenario())


def test_batches_are_split_to_fit_the_receivers_limits(tmp_path: Path) -> None:
    # Receivers (and this sender) inflate at most 6 KiB of batch JSON; planning alone would allow 512 KiB.
    policy = SyncPolicy(post_interval_seconds=0, max_batch_json_bytes=6 * 1024)
    clock = SyncClock()
    cloud = tmp_path / "cloud"
    laptop, desktop = (make_cloud_device(tmp_path, cloud, name, clock, policy=policy) for name in ("laptop", "desktop"))

    async def scenario() -> None:
        await create_vault(laptop)
        await join_vault(desktop, laptop)
        await laptop.sync()
        await desktop.sync()
        created = [await laptop.drive.create_folder(CreateFolderCommand(name=f"carpeta {index} " + "x" * 400)) for index in range(40)]
        skipped_before = await state_int(desktop, "skipped_messages")
        batches_before = len([ref for ref in await list_sync(laptop) if ref.kind == SyncMessageKind.BATCH])

        assert await laptop.push() >= 40
        await desktop.pull()

        batches = len([ref for ref in await list_sync(laptop) if ref.kind == SyncMessageKind.BATCH]) - batches_before
        assert batches >= 4
        assert {folder.id for folder in created} <= set(folder_names(desktop))
        assert await state_int(desktop, "skipped_messages") == skipped_before

    asyncio.run(scenario())


def test_a_fast_clock_is_reported_until_it_is_fixed(tmp_path: Path) -> None:
    # The device clock runs an hour ahead of the (real-time) fake cloud: peers drop every op it publishes.
    clock = SyncClock(current=datetime.now(UTC) + timedelta(hours=1))
    cloud = tmp_path / "cloud"
    laptop, desktop = (make_cloud_device(tmp_path, cloud, name, clock) for name in ("laptop", "desktop"))

    async def scenario() -> None:
        await create_vault(laptop)
        await join_vault(desktop, laptop)
        await laptop.drive.create_folder(CreateFolderCommand(name="Del futuro"))
        await laptop.push()

        skew = await state_json(laptop, "clock_skew")
        assert skew is not None and 55 * 60_000 < skew["skew_ms"] <= 61 * 60_000
        status = await status_service(laptop).status()
        assert status.error_code == "clock_skew" and status.clock_skew_ms == skew["skew_ms"]
        snapshot = await SQLiteActivitySource(laptop.factory).snapshot(now=clock.now())
        activity = build_activity(ActivityInputs(snapshot=snapshot, policy=BackupPolicy(), sync=status, now=clock.now()))
        [item] = [item for item in activity.attention if item.kind == AttentionKind.CLOCK_SKEW]
        assert item.id == "clock_skew" and item.title_key == "activity.attention.clock_skew"
        assert item.action.value == "none" and item.params["direction"] == "ahead" and item.params["skew_minutes"] == 60

        # A recent Telegram message proves the clock is no longer ahead once the person fixes it.
        clock.current = datetime.now(UTC)
        await desktop.drive.create_folder(CreateFolderCommand(name="Ahora"))
        await desktop.push()
        await laptop.pull()
        assert await state_json(laptop, "clock_skew") is None
        assert (await status_service(laptop).status()).error_code is None

    asyncio.run(scenario())


def test_a_slow_clock_is_reported_and_cleared_by_the_next_post(tmp_path: Path) -> None:
    clock = SyncClock(current=datetime.now(UTC) - timedelta(minutes=30))
    cloud = tmp_path / "cloud"
    laptop, desktop = (make_cloud_device(tmp_path, cloud, name, clock) for name in ("laptop", "desktop"))

    async def scenario() -> None:
        await create_vault(laptop)
        await join_vault(desktop, laptop)
        await laptop.drive.create_folder(CreateFolderCommand(name="Lenta"))
        await laptop.push()
        await desktop.pull()

        skew = await state_json(desktop, "clock_skew")
        assert skew is not None and skew["skew_ms"] < -25 * 60_000
        status = await status_service(desktop).status()
        assert status.error_code == "clock_skew" and status.clock_skew_ms is not None and status.clock_skew_ms < 0

        clock.current = datetime.now(UTC)
        await desktop.drive.create_folder(CreateFolderCommand(name="Corregida"))
        await desktop.push()
        assert await state_json(desktop, "clock_skew") is None

    asyncio.run(scenario())
