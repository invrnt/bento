"""Multi-process primitives for the fake cloud: an exclusive lock file and atomic file replacement."""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

T = TypeVar("T")
_RETRY_ATTEMPTS = 50
_RETRY_DELAY_SECONDS = 0.02


class FileLock:
    """Exclusive inter-process lock, re-entrant within a thread."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._local = threading.local()

    @contextmanager
    def hold(self) -> Iterator[None]:
        depth = getattr(self._local, "depth", 0)
        if depth:
            self._local.depth = depth + 1
            try:
                yield
            finally:
                self._local.depth = depth
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _lock(fd)
            self._local.depth = 1
            try:
                yield
            finally:
                self._local.depth = 0
                _unlock(fd)
        finally:
            os.close(fd)


def _lock(fd: int) -> None:
    if sys.platform == "win32":
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.01)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _with_retries(operation: Callable[[], T]) -> T:
    # Windows refuses to replace or open a file another process is replacing; retry briefly.
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            return operation()
        except PermissionError:
            if attempt == _RETRY_ATTEMPTS - 1:
                raise
            time.sleep(_RETRY_DELAY_SECONDS)
    raise AssertionError("unreachable")


def temp_path(directory: Path, suffix: str = ".tmp") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f".{uuid.uuid4().hex}{suffix}"


def replace(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    _with_retries(lambda: os.replace(source, target))


def read_json(path: Path) -> dict[str, Any] | None:
    def load() -> dict[str, Any] | None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            return None
        return payload if isinstance(payload, dict) else None

    return _with_retries(load)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    staged = temp_path(path.parent)
    try:
        with staged.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def write_bytes(path: Path, data: bytes) -> None:
    staged = temp_path(path.parent)
    try:
        staged.write_bytes(data)
        replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def copy_file(source: Path, target: Path) -> None:
    staged = temp_path(target.parent)
    try:
        _with_retries(lambda: shutil.copyfile(source, staged))
        replace(staged, target)
    finally:
        staged.unlink(missing_ok=True)


def stat_signature(path: Path) -> tuple[int, int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_mtime_ns, stat.st_size, stat.st_ino
