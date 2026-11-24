"""Local tree walking for `bento upload`: filters, hidden/junk policy, symlinks, and hashing."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import stat
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

CHUNK_SIZE = 1024 * 1024
JUNK_NAMES = frozenset(
    {
        ".DS_Store",
        "Thumbs.db",
        "ehthumbs.db",
        "desktop.ini",
        "Desktop.ini",
        "Icon\r",
        ".Spotlight-V100",
        ".Trashes",
        ".fseventsd",
        ".TemporaryItems",
        "$RECYCLE.BIN",
        "System Volume Information",
        ".localized",
    }
)


@dataclass(frozen=True, slots=True)
class WalkOptions:
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    hidden: bool = False
    follow_symlinks: bool = False
    flatten: bool = False


@dataclass(frozen=True, slots=True)
class LocalFile:
    path: Path
    relative_dir: tuple[str, ...]
    size: int

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True, slots=True)
class SkippedEntry:
    path: Path
    reason: str  # hidden | junk | symlink | excluded | not_included | special | unreadable


@dataclass(slots=True)
class WalkResult:
    files: list[LocalFile] = field(default_factory=list)
    skipped: list[SkippedEntry] = field(default_factory=list)
    missing: list[Path] = field(default_factory=list)


def is_junk(name: str) -> bool:
    return name in JUNK_NAMES or name.startswith("._")


def is_hidden(name: str) -> bool:
    return name.startswith(".")


def _matches(patterns: Sequence[str], name: str, relative: str) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) or fnmatch.fnmatchcase(relative, pattern) for pattern in patterns)


def collect(inputs: Sequence[str], options: WalkOptions) -> WalkResult:
    """Expand files and directories into upload candidates.

    A directory argument uploads the directory itself (`Viaje` → `<to>/Viaje/…`); with a trailing
    separator (`Viaje/`) it uploads only its contents. `--flatten` puts every file directly in `<to>`.
    Command-line arguments are followed even when they are symlinks; links found while walking are
    skipped unless `follow_symlinks`.
    """
    result = WalkResult()
    for raw in inputs:
        contents_only = raw.endswith(("/", os.sep)) and len(raw) > 1
        path = Path(raw).expanduser()
        try:
            info = path.stat()
        except OSError:
            result.missing.append(path)
            continue
        if stat.S_ISDIR(info.st_mode):
            resolved = path.resolve()
            base: tuple[str, ...] = () if contents_only or options.flatten else (resolved.name,)
            _walk_directory(resolved, base, options, result, visited={(info.st_dev, info.st_ino)})
        elif stat.S_ISREG(info.st_mode):
            result.files.append(LocalFile(path=path.resolve(), relative_dir=(), size=info.st_size))
        else:
            result.skipped.append(SkippedEntry(path=path, reason="special"))
    return result


def _walk_directory(
    directory: Path,
    relative: tuple[str, ...],
    options: WalkOptions,
    result: WalkResult,
    *,
    visited: set[tuple[int, int]],
) -> None:
    try:
        entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
    except OSError:
        result.skipped.append(SkippedEntry(path=directory, reason="unreadable"))
        return
    for entry in entries:
        name = entry.name
        entry_path = Path(entry.path)
        relative_text = "/".join((*relative, name))
        if not options.hidden and is_junk(name):
            result.skipped.append(SkippedEntry(path=entry_path, reason="junk"))
            continue
        if not options.hidden and is_hidden(name):
            result.skipped.append(SkippedEntry(path=entry_path, reason="hidden"))
            continue
        if options.exclude and _matches(options.exclude, name, relative_text):
            result.skipped.append(SkippedEntry(path=entry_path, reason="excluded"))
            continue
        try:
            is_link = entry.is_symlink()
            if is_link and not options.follow_symlinks:
                result.skipped.append(SkippedEntry(path=entry_path, reason="symlink"))
                continue
            info = entry.stat(follow_symlinks=True)
        except OSError:
            result.skipped.append(SkippedEntry(path=entry_path, reason="unreadable"))
            continue
        if stat.S_ISDIR(info.st_mode):
            key = (info.st_dev, info.st_ino)
            if key in visited:
                result.skipped.append(SkippedEntry(path=entry_path, reason="symlink"))
                continue
            child_relative = relative if options.flatten else (*relative, name)
            _walk_directory(entry_path, child_relative, options, result, visited=visited | {key})
        elif stat.S_ISREG(info.st_mode):
            if options.include and not _matches(options.include, name, relative_text):
                result.skipped.append(SkippedEntry(path=entry_path, reason="not_included"))
                continue
            result.files.append(LocalFile(path=entry_path, relative_dir=relative, size=info.st_size))
        else:
            result.skipped.append(SkippedEntry(path=entry_path, reason="special"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
)
_UNSAFE_CHARS = set('<>:"/\\|?*') | {chr(code) for code in range(32)}


def safe_local_name(name: str, fallback: str = "archivo") -> str:
    """A file name that cannot escape the target directory on any OS."""
    cleaned = "".join("_" if char in _UNSAFE_CHARS else char for char in name).strip().rstrip(".")
    if cleaned in {"", ".", ".."}:
        cleaned = fallback
    if cleaned.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        cleaned = "_" + cleaned
    return cleaned[:255]
