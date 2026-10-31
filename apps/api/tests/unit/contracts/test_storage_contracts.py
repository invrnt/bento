from __future__ import annotations

import pytest

from bento.domain.errors import ValidationFailedError
from bento.domain.storage import BlobKind, BlobPart, BlobRef, StorageBackend
from bento.domain.telegram import RemotePart


def test_blob_parts_must_be_contiguous_and_ordered() -> None:
    def ref(*indexes: int) -> BlobRef:
        return BlobRef(
            id="blob_1",
            asset_id=None,
            backend=StorageBackend.TELEGRAM,
            kind=BlobKind.ORIGINAL,
            object_key="vault/blob_1",
            size_bytes=10,
            parts=tuple(BlobPart(index=index, channel_id="-1001", message_id=str(index + 1), size_bytes=5) for index in indexes),
        )

    assert len(ref(0, 1).parts) == 2
    assert ref().parts == ()
    for indexes in ((1,), (0, 2), (1, 0)):
        with pytest.raises(ValidationFailedError):
            ref(*indexes)
    with pytest.raises(ValidationFailedError):
        BlobPart(index=-1, channel_id="1", message_id="1", size_bytes=0)


def test_blob_part_converts_to_and_from_remote_parts() -> None:
    remote = RemotePart(channel_id=-1001000000001, message_id=42, size_bytes=512)

    part = BlobPart.from_remote(3, remote)

    assert part == BlobPart(index=3, channel_id="-1001000000001", message_id="42", size_bytes=512)
    assert part.remote() == remote


def test_fake_backend_is_a_configurable_storage_backend() -> None:
    assert StorageBackend("fake") == StorageBackend.FAKE
