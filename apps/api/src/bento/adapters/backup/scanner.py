"""Filesystem scanning for folder backup: hidden/system/temp files skipped, symlinks never followed."""

from __future__ import annotations

import os
import stat as stat_module
import sys
from collections.abc import Iterator
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from bento.application.backup import PathInfo, ScannedFile

IGNORED_NAMES = frozenset(
    {
        "desktop.ini",
        "thumbs.db",
        "ehthumbs.db",
        "$recycle.bin",
        "system volume information",
        "lost+found",
        "icon\r",
    }
)
IGNORED_PATTERNS = (
    "~$*",
    "*.tmp",
    "*.temp",
    "*.part",
    "*.partial",
    "*.crdownload",
    "*.download",
    "*.swp",
    "*.swx",
    "*~",
    ".~lock.*#",
)
_WINDOWS_SKIP_ATTRIBUTES = 0x2 | 0x4  # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM


def is_ignored_name(name: str) -> bool:
    lowered = name.lower()
    if not name or name.startswith(".") or lowered in IGNORED_NAMES:
        return True
    return any(fnmatch(lowered, pattern) for pattern in IGNORED_PATTERNS)


class LocalFolderScanner:
    def inspect(self, raw_path: str) -> PathInfo:
        expanded = Path(os.path.expanduser(raw_path.strip()))
        if not expanded.is_absolute():
            raise ValueError("Backup folders must be absolute paths")
        try:
            resolved = expanded.resolve(strict=True)
        except (FileNotFoundError, NotADirectoryError):
            return PathInfo(path=expanded, exists=False, is_dir=False, readable=False, is_root=False)
        except (OSError, RuntimeError) as exc:
            raise ValueError("Invalid path") from exc
        is_dir = resolved.is_dir()
        readable = is_dir and os.access(resolved, os.R_OK | os.X_OK)
        if readable:
            try:
                with os.scandir(resolved) as entries:
                    next(entries, None)
            except OSError:
                readable = False
        return PathInfo(
            path=resolved,
            exists=True,
            is_dir=is_dir,
            readable=readable,
            is_root=resolved == Path(resolved.anchor),
        )

    def scan(self, root: Path, *, start: str | None = None, exclude: tuple[Path, ...] = ()) -> Iterator[ScannedFile]:
        base = root if start is None else _join(root, start)
        if base is None:
            return
        excluded = tuple(Path(item) for item in exclude)
        stack = [base]
        while stack:
            directory = stack.pop()
            try:
                with os.scandir(directory) as entries:
                    items = sorted(entries, key=lambda entry: entry.name)
            except OSError:
                continue
            for entry in items:
                if is_ignored_name(entry.name):
                    continue
                try:
                    if entry.is_symlink():
                        continue
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if _hidden_by_attributes(info):
                    continue
                path = Path(entry.path)
                if stat_module.S_ISDIR(info.st_mode):
                    if not any(path == item or path.is_relative_to(item) for item in excluded):
                        stack.append(path)
                elif stat_module.S_ISREG(info.st_mode):
                    yield ScannedFile(
                        relative_path=path.relative_to(root).as_posix(),
                        size_bytes=info.st_size,
                        mtime_ns=info.st_mtime_ns,
                    )

    def stat(self, root: Path, relative_path: str) -> ScannedFile | None:
        path = _join(root, relative_path)
        if path is None or any(is_ignored_name(part) for part in PurePosixPath(relative_path).parts):
            return None
        if _has_symlink_component(root, path):
            return None
        try:
            info = path.lstat()
        except OSError:
            return None
        if not stat_module.S_ISREG(info.st_mode) or _hidden_by_attributes(info):
            return None
        return ScannedFile(relative_path=PurePosixPath(relative_path).as_posix(), size_bytes=info.st_size, mtime_ns=info.st_mtime_ns)

    def is_directory(self, root: Path, relative_path: str) -> bool:
        path = _join(root, relative_path)
        if path is None or _has_symlink_component(root, path):
            return False
        try:
            return stat_module.S_ISDIR(path.lstat().st_mode)
        except OSError:
            return False

    def relative(self, root: Path, absolute_path: str) -> str | None:
        path = Path(os.path.abspath(absolute_path))
        if not path.is_relative_to(root) or path == root:
            return None
        relative = path.relative_to(root)
        if any(is_ignored_name(part) for part in relative.parts):
            return None
        return relative.as_posix()


def _join(root: Path, relative_path: str) -> Path | None:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts) or not relative.parts:
        return None
    return root.joinpath(*relative.parts)


def _has_symlink_component(root: Path, path: Path) -> bool:
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def _hidden_by_attributes(info: os.stat_result) -> bool:
    if sys.platform != "win32":
        return False
    return bool(getattr(info, "st_file_attributes", 0) & _WINDOWS_SKIP_ATTRIBUTES)
