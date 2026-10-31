from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bento.application.activity import (
    ActivityInputs,
    ActivitySnapshot,
    FailedBackupSource,
    FailedInboxItem,
    FailedUpload,
    NewDevice,
    build_activity,
)
from bento.domain.activity import TransferStats
from bento.domain.backup import BackupPolicy
from bento.domain.sync import SyncState, SyncStatus
from bento.domain.vault import DEVICE_REMOVED_REASON, VaultState, VaultStatus

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _activity(snapshot: ActivitySnapshot = ActivitySnapshot(), **kwargs):  # type: ignore[no-untyped-def]
    policy = kwargs.pop("policy", BackupPolicy())
    return build_activity(ActivityInputs(snapshot=snapshot, policy=policy, now=NOW, **kwargs))


def test_idle_library_is_up_to_date() -> None:
    activity = _activity(sync=SyncStatus(state=SyncState.IDLE), vault=VaultStatus(state=VaultState.READY, recovery_kit_saved=True))
    assert activity.summary.value == "up_to_date"
    assert activity.uploads == TransferStats() and activity.attention == ()


def test_uploads_report_progress_and_eta_from_recent_throughput() -> None:
    snapshot = ActivitySnapshot(
        uploads_running=1,
        uploads_queued=11,
        upload_bytes_total=1000,
        upload_bytes_done=400,
        backup_pending_files=3,
        backup_pending_bytes=200,
        recent_uploaded_bytes=600,
        recent_window_seconds=60,
    )
    activity = _activity(snapshot)
    assert activity.summary.value == "uploading"
    assert activity.uploads == TransferStats(active=1, queued=14, bytes_total=1200, bytes_done=400, eta_seconds=80)


def test_pause_only_stops_folder_backup() -> None:
    paused = BackupPolicy(paused=True)
    assert _activity(ActivitySnapshot(backup_pending_files=5), policy=paused).summary.value == "paused"
    assert _activity(ActivitySnapshot(uploads_queued=1), policy=paused).summary.value == "uploading"
    on_battery = BackupPolicy(pause_on_battery=True, on_battery=True)
    assert _activity(ActivitySnapshot(), policy=on_battery).summary.value == "paused"


def test_offline_downloads_and_sync_states() -> None:
    assert _activity(ActivitySnapshot(uploads_queued=2), sync=SyncStatus(state=SyncState.OFFLINE)).summary.value == "offline"
    downloads = TransferStats(active=1, bytes_total=10, bytes_done=5)
    assert _activity(downloads=downloads).summary.value == "downloading"
    assert _activity(sync=SyncStatus(state=SyncState.BOOTSTRAPPING)).summary.value == "syncing"


def test_attention_items_use_i18n_keys_and_actionable_params() -> None:
    snapshot = ActivitySnapshot(
        flood_wait_until=NOW + timedelta(minutes=4),
        failed_uploads=(FailedUpload(job_id="job_1", asset_id="asset_1", error="boom"),),
        failed_backups=(FailedBackupSource(job_id="job_2", source_id="bsrc_1", label="Fotos", failed_files=3),),
        failed_inbox=(FailedInboxItem(message_id=42, error_code="unsupported"),),
    )
    activity = _activity(
        snapshot,
        sync=SyncStatus(state=SyncState.ERROR, error_code="sync_integrity"),
        vault=VaultStatus(state=VaultState.READY, recovery_kit_saved=False),
    )

    assert activity.summary.value == "attention"
    items = {item.id: item for item in activity.attention}
    assert set(items) == {
        "flood_wait",
        "sync_error",
        "upload_failed:job_1",
        "backup_failed:bsrc_1",
        "recovery_kit",
        "inbox_failed:42",
    }
    for item in activity.attention:
        assert item.title_key == f"activity.attention.{item.kind.value}"
    assert items["flood_wait"].params == {"retry_after_seconds": 240, "retry_after_minutes": 4}
    assert items["upload_failed:job_1"].params == {"job_id": "job_1", "asset_id": "asset_1"}
    assert items["upload_failed:job_1"].action.value == "retry"
    assert items["backup_failed:bsrc_1"].params == {"job_id": "job_2", "source_id": "bsrc_1", "label": "Fotos", "count": 3}
    assert items["recovery_kit"].action.value == "save_recovery_kit"
    assert items["sync_error"].params == {"code": "sync_integrity"} and items["sync_error"].action.value == "retry"
    assert items["inbox_failed:42"].params == {"message_id": 42, "code": "unsupported"}


def test_short_flood_waits_and_sync_waits() -> None:
    short = _activity(ActivitySnapshot(flood_wait_until=NOW + timedelta(seconds=30)))
    assert short.attention == ()
    waiting = _activity(sync=SyncStatus(state=SyncState.WAITING, waiting_until=NOW + timedelta(minutes=10)))
    assert [item.params["retry_after_seconds"] for item in waiting.attention] == [600]
    assert waiting.summary.value == "attention"


def test_telegram_client_flood_waits_join_the_single_flood_wait_item() -> None:
    long_wait = _activity(ActivitySnapshot(telegram_flood_wait_until=NOW + timedelta(seconds=150)))
    [item] = long_wait.attention
    assert item.id == "flood_wait" and item.kind.value == "flood_wait"
    assert item.params == {"retry_after_seconds": 150, "retry_after_minutes": 3}
    assert long_wait.summary.value == "attention"

    assert _activity(ActivitySnapshot(telegram_flood_wait_until=NOW + timedelta(seconds=60))).attention == ()
    assert _activity(ActivitySnapshot(telegram_flood_wait_until=NOW - timedelta(minutes=5))).attention == ()

    everywhere = _activity(
        ActivitySnapshot(
            flood_wait_until=NOW + timedelta(minutes=4),
            telegram_flood_wait_until=NOW + timedelta(minutes=9),
        ),
        sync=SyncStatus(state=SyncState.WAITING, waiting_until=NOW + timedelta(minutes=2)),
    )
    [deduped] = [item for item in everywhere.attention if item.kind.value == "flood_wait"]
    assert deduped.params == {"retry_after_seconds": 540, "retry_after_minutes": 9}


def test_recovery_kit_reminder_only_for_ready_vaults() -> None:
    assert _activity(vault=VaultStatus(state=VaultState.LOCKED)).attention == ()
    assert _activity(vault=VaultStatus(state=VaultState.LOCAL_ONLY)).attention == ()
    reminder = _activity(vault=VaultStatus(state=VaultState.READY))
    assert [item.kind.value for item in reminder.attention] == ["recovery_kit"]
    assert reminder.summary.value == "attention"


def test_devices_first_seen_through_sync_ask_for_a_review() -> None:
    snapshot = ActivitySnapshot(new_devices=(NewDevice(device_id="dev_x", name="Tablet", first_seen_at=NOW, introduced_by="dev_a"),))
    activity = _activity(snapshot, vault=VaultStatus(state=VaultState.READY, recovery_kit_saved=True))
    [item] = activity.attention
    assert (item.id, item.kind.value, item.action.value) == ("new_device:dev_x", "new_device", "open_devices")
    assert item.title_key == "activity.attention.new_device"
    assert item.params == {"device_id": "dev_x", "name": "Tablet", "first_seen_at": NOW.isoformat()}
    assert activity.summary.value == "attention"


def test_a_removed_device_and_a_stale_kit_are_attention_items() -> None:
    removed = _activity(vault=VaultStatus(state=VaultState.LOCKED, reason=DEVICE_REMOVED_REASON))
    [item] = removed.attention
    assert (item.id, item.title_key, item.action.value) == ("device_removed", "activity.attention.device_removed", "open_settings")

    stale = _activity(vault=VaultStatus(state=VaultState.READY, recovery_kit_saved=False, recovery_kit_stale=True))
    [kit] = stale.attention
    assert kit.kind.value == "recovery_kit" and kit.params == {"reason": "stale"}
    unsaved = _activity(vault=VaultStatus(state=VaultState.READY, recovery_kit_saved=False))
    assert unsaved.attention[0].params == {}
