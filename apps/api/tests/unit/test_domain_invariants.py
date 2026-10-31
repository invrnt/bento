from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bento.domain.assets import Asset, AssetKind, AssetMetadata, AssetMode, ProcessingState
from bento.domain.drive import Folder
from bento.domain.errors import InvalidFolderMoveError, ValidationFailedError
from bento.domain.jobs import Job, JobStatus, JobType


NOW = datetime(2026, 1, 1, tzinfo=UTC)
SHA = "a" * 64


def test_folder_move_rejects_self_or_descendant_parent() -> None:
    folder = Folder(id="folder-1", name="Root", parent_id=None, created_at=NOW, updated_at=NOW)

    with pytest.raises(InvalidFolderMoveError) as self_move:
        folder.move_to("folder-1", set(), NOW)
    with pytest.raises(InvalidFolderMoveError) as descendant_move:
        folder.move_to("child-1", {"child-1", "grandchild-1"}, NOW)

    assert self_move.value.code == "invalid_folder_move"
    assert descendant_move.value.code == "invalid_folder_move"


def test_logical_delete_sets_deleted_at_without_changing_identity() -> None:
    asset = _asset()

    deleted = asset.mark_deleted(NOW)

    assert deleted.id == asset.id
    assert deleted.is_deleted is True
    assert deleted.deleted_at == NOW


def test_processing_state_transition_rejects_out_of_order_jump() -> None:
    asset = _asset()

    with pytest.raises(ValidationFailedError) as exc:
        asset.transition_to(ProcessingState.INDEXED, NOW)

    assert exc.value.code == "validation_failed"
    assert exc.value.details == {"from": "created", "to": "indexed"}


def test_processing_state_transition_allows_progressive_pipeline() -> None:
    asset = _asset()

    stored = asset.transition_to(ProcessingState.BLOB_STORED, NOW)
    pending = stored.transition_to(ProcessingState.THUMBNAIL_PENDING, NOW)

    assert pending.processing_state == ProcessingState.THUMBNAIL_PENDING


def test_only_files_from_this_device_may_feed_ai_indexing() -> None:
    from dataclasses import replace

    from bento.domain.assets import AssetOrigin

    asset = _asset()
    assert asset.origin == AssetOrigin.DEVICE and asset.ai_indexing_allowed
    for origin in (AssetOrigin.TELEGRAM_INBOX, AssetOrigin.TELEGRAM_IMPORT):
        assert origin.from_telegram and not replace(asset, origin=origin).ai_indexing_allowed
    assert not AssetOrigin.DEVICE.from_telegram
    assert not replace(asset, origin=None).ai_indexing_allowed  # arrived from another device


def test_finish_processing_reaches_a_terminal_state() -> None:
    stored = _asset().transition_to(ProcessingState.BLOB_STORED, NOW)
    pending = stored.transition_to(ProcessingState.THUMBNAIL_PENDING, NOW)
    ready = pending.transition_to(ProcessingState.THUMBNAIL_READY, NOW)

    assert stored.finish_processing(NOW).processing_state == ProcessingState.INDEXED
    assert pending.finish_processing(NOW).processing_state == ProcessingState.INDEXED
    assert ready.finish_processing(NOW).processing_state == ProcessingState.INDEXED
    assert pending.finish_processing(NOW, failed=True).processing_state == ProcessingState.FAILED_PARTIAL
    partial = pending.transition_to(ProcessingState.FAILED_PARTIAL, NOW)
    assert partial.finish_processing(NOW) == partial
    indexed = ready.transition_to(ProcessingState.INDEXED, NOW)
    assert indexed.finish_processing(NOW, failed=True) == indexed
    assert _asset().finish_processing(NOW) == _asset()  # nothing stored yet: stays `created`


def test_job_retry_eligibility_requires_failed_with_attempts_remaining() -> None:
    failed = Job(
        id="job-1",
        type=JobType.OCR,
        status=JobStatus.FAILED,
        priority=3,
        payload={},
        attempts=1,
        max_attempts=3,
        created_at=NOW,
        updated_at=NOW,
    )
    exhausted = Job(
        id="job-2",
        type=JobType.OCR,
        status=JobStatus.FAILED,
        priority=3,
        payload={},
        attempts=3,
        max_attempts=3,
        created_at=NOW,
        updated_at=NOW,
    )

    assert failed.can_retry is True
    assert failed.retry(NOW).status == JobStatus.QUEUED
    assert exhausted.can_retry is False


def _asset() -> Asset:
    return Asset(
        id="asset-1",
        kind=AssetKind.IMAGE,
        mode=AssetMode.PHOTOS,
        folder_id=None,
        filename="photo.jpg",
        metadata=AssetMetadata(
            original_filename="photo.jpg",
            mime_type="image/jpeg",
            size_bytes=100,
            sha256=SHA,
        ),
        processing_state=ProcessingState.CREATED,
        favorite=False,
        created_at=NOW,
        updated_at=NOW,
    )
