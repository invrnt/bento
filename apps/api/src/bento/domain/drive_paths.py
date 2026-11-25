"""Drive paths: pure parsing, normalization, and canonical formatting (`api/cli-endpoints.md`).

Folder and asset names are not unique among siblings and are stored as typed, so names are compared
after NFC normalization of both sides. A name containing `/` is rendered as `\\/` (display only;
such items are addressed by `id:` references).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from bento.domain.errors import DomainError, ValidationFailedError

MAX_PATH_LENGTH = 4096
MAX_PATH_SEGMENTS = 64
MAX_AMBIGUOUS_CANDIDATES = 20
ID_REF_PREFIX = "id:"
ROOT_PATH = "/"


class DriveNodeKind(StrEnum):
    ROOT = "root"
    FOLDER = "folder"
    ASSET = "asset"


@dataclass(frozen=True, slots=True)
class DrivePath:
    segments: tuple[str, ...] = ()
    must_be_folder: bool = False

    @property
    def is_root(self) -> bool:
        return not self.segments

    @property
    def canonical(self) -> str:
        return format_drive_path(self.segments)

    def prefix(self, length: int) -> str:
        return format_drive_path(self.segments[:length])


@dataclass(frozen=True, slots=True)
class DriveIdRef:
    id: str


DriveRef = DrivePath | DriveIdRef


@dataclass(frozen=True, slots=True)
class PathCandidate:
    id: str
    kind: DriveNodeKind
    path: str
    created_at: datetime

    def as_details(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind.value, "path": self.path, "created_at": self.created_at.isoformat()}


class PathNotFoundError(DomainError):
    def __init__(self, path: str, missing_from: int) -> None:
        super().__init__("path_not_found", "Path not found", {"path": path, "missing_from": missing_from})


class PathAmbiguousError(DomainError):
    def __init__(self, path: str, candidates: Iterable[PathCandidate]) -> None:
        ordered = sorted(candidates, key=lambda item: (item.created_at, item.id))[:MAX_AMBIGUOUS_CANDIDATES]
        super().__init__(
            "path_ambiguous",
            "Path matches more than one item",
            {"path": path, "candidates": [candidate.as_details() for candidate in ordered]},
        )


def normalize_name(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def escape_segment(name: str) -> str:
    return normalize_name(name).replace("/", "\\/")


def format_drive_path(names: Iterable[str]) -> str:
    return ROOT_PATH + "/".join(escape_segment(name) for name in names)


def parse_drive_path(text: str) -> DrivePath:
    if len(text) > MAX_PATH_LENGTH:
        raise _invalid("too_long")
    body = text[1:] if text.startswith("/") else text
    if not body:
        return DrivePath()
    must_be_folder = body.endswith("/")
    if must_be_folder:
        body = body[:-1]
    raw_segments = body.split("/")
    if len(raw_segments) > MAX_PATH_SEGMENTS:
        raise _invalid("too_long")
    segments: list[str] = []
    for raw in raw_segments:
        if not raw:
            raise _invalid("empty_segment")
        if raw in {".", ".."}:
            raise _invalid("dot_segment")
        segments.append(normalize_name(raw))
    return DrivePath(segments=tuple(segments), must_be_folder=must_be_folder)


def parse_drive_ref(text: str) -> DriveRef:
    if text.startswith(ID_REF_PREFIX):
        item_id = text[len(ID_REF_PREFIX) :].strip()
        if not item_id:
            raise _invalid("empty_segment")
        if len(item_id) > MAX_PATH_LENGTH:
            raise _invalid("too_long")
        return DriveIdRef(id=item_id)
    return parse_drive_path(text)


def name_matches(stored_name: str, segment: str) -> bool:
    """`segment` is already NFC (from `parse_drive_path`)."""
    return normalize_name(stored_name) == segment


def sort_key(name: str, item_id: str) -> tuple[str, str]:
    return (normalize_name(name).casefold(), item_id)


def _invalid(reason: str) -> ValidationFailedError:
    return ValidationFailedError("Invalid drive path", {"reason": reason})
