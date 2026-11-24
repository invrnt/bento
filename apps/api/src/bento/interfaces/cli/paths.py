"""Bento path and `id:` reference handling on the client side.

The API is the authority on paths (`/drive/resolve`, `/drive/folders/ensure`); this module only parses
what the CLI needs locally: splitting a destination into parent and name, joining upload directories, and
rendering item paths from a parent path plus a name. Syntax rules mirror `api/cli-endpoints.md`.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from bento.interfaces.cli.errors import CliError

ID_PREFIX = "id:"
MAX_PATH_LENGTH = 4096
MAX_SEGMENTS = 64


@dataclass(frozen=True, slots=True)
class BentoRef:
    """A path (`segments`) or a direct id; `text` is what the API receives as `path=`."""

    text: str
    item_id: str | None
    segments: tuple[str, ...]
    must_be_folder: bool

    @property
    def is_root(self) -> bool:
        return self.item_id is None and not self.segments

    @property
    def name(self) -> str:
        return self.segments[-1] if self.segments else ""

    @property
    def parent(self) -> BentoRef:
        if self.item_id is not None:
            raise ValueError("an id: reference has no textual parent")
        return path_ref(self.segments[:-1])

    @property
    def canonical(self) -> str:
        if self.item_id is not None:
            return self.text
        return format_segments(self.segments)


def _invalid(text: str, reason: str) -> CliError:
    return CliError(
        "validation_failed", "Invalid Bento path", {"path": text, "reason": reason}, exit_code=2
    )


def parse_ref(text: str) -> BentoRef:
    raw = text.strip()
    if raw.startswith(ID_PREFIX):
        item_id = raw[len(ID_PREFIX) :].strip()
        if not item_id or "/" in item_id:
            raise _invalid(text, "invalid_id")
        return BentoRef(text=f"{ID_PREFIX}{item_id}", item_id=item_id, segments=(), must_be_folder=False)
    if len(raw) > MAX_PATH_LENGTH:
        raise _invalid(text, "too_long")
    must_be_folder = raw.endswith("/") and raw not in {"", "/"}
    body = raw[1:] if raw.startswith("/") else raw
    if body.endswith("/"):
        body = body[:-1]
    if not body:
        return BentoRef(text="/", item_id=None, segments=(), must_be_folder=False)
    segments = tuple(unicodedata.normalize("NFC", part) for part in body.split("/"))
    for segment in segments:
        if segment == "":
            raise _invalid(text, "empty_segment")
        if segment in {".", ".."}:
            raise _invalid(text, "dot_segment")
    if len(segments) > MAX_SEGMENTS:
        raise _invalid(text, "too_long")
    return BentoRef(
        text=format_segments(segments) + ("/" if must_be_folder else ""),
        item_id=None,
        segments=segments,
        must_be_folder=must_be_folder,
    )


def path_ref(segments: tuple[str, ...]) -> BentoRef:
    return BentoRef(text=format_segments(segments), item_id=None, segments=segments, must_be_folder=False)


def format_segments(segments: tuple[str, ...]) -> str:
    return "/" + "/".join(escape_name(segment) for segment in segments) if segments else "/"


def escape_name(name: str) -> str:
    """Display form of a name inside a path: a literal `/` is rendered as `\\/` (address it by `id:`)."""
    return name.replace("/", "\\/")


def join_path(parent: str, name: str) -> str:
    """Child path of a canonical parent path (as returned by the API) and a raw item name."""
    base = parent.rstrip("/") if parent != "/" else ""
    return f"{base}/{escape_name(name)}"


def join_segments(base: BentoRef, relative: tuple[str, ...]) -> BentoRef:
    """`base` (a path or an id: ref) plus relative directory names; used for upload destinations."""
    if not relative:
        return base
    if base.item_id is not None:
        # The API resolves `id:<folder>/A/B` only through ensure on the base path, so the
        # caller resolves the id to its canonical path first.
        raise ValueError("resolve id: references to a path before joining")
    clean = tuple(unicodedata.normalize("NFC", part) for part in relative)
    return path_ref(base.segments + clean)

