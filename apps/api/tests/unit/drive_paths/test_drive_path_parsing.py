from __future__ import annotations

import unicodedata
from datetime import UTC, datetime, timedelta

import pytest

from bento.domain.drive_paths import (
    MAX_AMBIGUOUS_CANDIDATES,
    MAX_PATH_LENGTH,
    MAX_PATH_SEGMENTS,
    DriveIdRef,
    DriveNodeKind,
    DrivePath,
    PathAmbiguousError,
    PathCandidate,
    PathNotFoundError,
    format_drive_path,
    name_matches,
    parse_drive_path,
    parse_drive_ref,
)
from bento.domain.errors import ValidationFailedError

NFD_E = unicodedata.normalize("NFD", "é")


@pytest.mark.parametrize("text", ["", "/"])
def test_root(text: str) -> None:
    path = parse_drive_path(text)
    assert path == DrivePath() and path.is_root and not path.must_be_folder and path.canonical == "/"


def test_segments_leading_and_trailing_slash() -> None:
    assert parse_drive_path("/A/B/file.pdf") == DrivePath(("A", "B", "file.pdf"))
    assert parse_drive_path("A/B") == DrivePath(("A", "B"))
    folder = parse_drive_path("/A/B/")
    assert folder == DrivePath(("A", "B"), must_be_folder=True)
    assert folder.canonical == "/A/B"
    assert folder.prefix(1) == "/A"


def test_segments_are_nfc_normalized() -> None:
    path = parse_drive_path(f"/Caf{NFD_E}")
    assert path.segments == ("Café",)
    assert name_matches(f"Caf{NFD_E}", path.segments[0])
    assert name_matches("Café", path.segments[0])
    assert not name_matches("cafe", path.segments[0])
    assert not name_matches("café".upper(), path.segments[0])  # exact after NFC, not case-insensitive


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("//", "empty_segment"),
        ("/A//B", "empty_segment"),
        ("//A", "empty_segment"),
        ("/A//", "empty_segment"),
        ("/A/./B", "dot_segment"),
        ("/A/..", "dot_segment"),
        ("..", "dot_segment"),
        ("/" + "a" * MAX_PATH_LENGTH, "too_long"),
        ("/".join(["a"] * (MAX_PATH_SEGMENTS + 1)), "too_long"),
    ],
)
def test_invalid_paths(text: str, reason: str) -> None:
    with pytest.raises(ValidationFailedError) as caught:
        parse_drive_path(text)
    assert caught.value.code == "validation_failed"
    assert caught.value.details == {"reason": reason}


def test_limits_are_inclusive() -> None:
    assert len(parse_drive_path("/".join(["a"] * MAX_PATH_SEGMENTS)).segments) == MAX_PATH_SEGMENTS
    assert parse_drive_path("a" * MAX_PATH_LENGTH).segments == ("a" * MAX_PATH_LENGTH,)


def test_id_refs() -> None:
    assert parse_drive_ref("id:folder_1") == DriveIdRef("folder_1")
    assert parse_drive_ref("/id:folder_1") == DrivePath(("id:folder_1",))
    assert parse_drive_ref("/A") == DrivePath(("A",))
    with pytest.raises(ValidationFailedError):
        parse_drive_ref("id:")


def test_canonical_format_escapes_slashes_and_normalizes() -> None:
    assert format_drive_path([]) == "/"
    assert format_drive_path(["A", "a/b", f"Caf{NFD_E}"]) == "/A/a\\/b/Café"


def test_errors_carry_contract_details() -> None:
    missing = PathNotFoundError("/A/B", 1)
    assert missing.code == "path_not_found"
    assert missing.details == {"path": "/A/B", "missing_from": 1}

    base = datetime(2026, 1, 1, tzinfo=UTC)
    candidates = [
        PathCandidate(f"folder_{index:02d}", DriveNodeKind.FOLDER, "/A", base - timedelta(minutes=index))
        for index in range(MAX_AMBIGUOUS_CANDIDATES + 5)
    ]
    ambiguous = PathAmbiguousError("/A/x", candidates)
    assert ambiguous.code == "path_ambiguous"
    listed = ambiguous.details["candidates"]
    assert len(listed) == MAX_AMBIGUOUS_CANDIDATES
    assert listed[0]["id"] == f"folder_{MAX_AMBIGUOUS_CANDIDATES + 4:02d}"  # oldest first
    assert listed[0]["kind"] == "folder" and listed[0]["path"] == "/A" and listed[0]["created_at"].startswith("2025-12-31")
