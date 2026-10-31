"""Hardened launch helpers for external tools such as ffmpeg and ffprobe.

Children receive an allowlisted environment, so per-launch secrets and unrelated configuration are
never inherited. Executables resolve to absolute paths from absolute `PATH` entries only: relative
entries and the current directory are skipped because Windows would otherwise run a binary planted
in the working directory before the real one.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

_ALLOWED_ENVIRONMENT = frozenset({"PATH", "HOME", "LANG", "TMPDIR", "TEMP", "TMP"})
_WINDOWS_ALLOWED_ENVIRONMENT = frozenset({"SYSTEMROOT", "WINDIR"})


def child_environment(environ: Mapping[str, str] | None = None, *, windows: bool | None = None) -> dict[str, str]:
    """The allowlisted subset of `environ` (default `os.environ`) for a child process."""
    source = os.environ if environ is None else environ
    on_windows = sys.platform == "win32" if windows is None else windows
    allowed: dict[str, str] = {}
    for key, value in source.items():
        name = key.upper() if on_windows else key
        if (
            name in _ALLOWED_ENVIRONMENT
            or name.startswith("LC_")
            or (on_windows and name in _WINDOWS_ALLOWED_ENVIRONMENT)
        ):
            allowed[key] = value
    return allowed


def resolve_executable(
    name: str,
    *,
    environ: Mapping[str, str] | None = None,
    windows: bool | None = None,
) -> str | None:
    """Absolute path of `name` found in an absolute `PATH` directory other than the current one."""
    if not name or os.path.basename(name) != name:
        raise ValueError("Executable names must not contain a directory")
    source = os.environ if environ is None else environ
    on_windows = sys.platform == "win32" if windows is None else windows
    candidates = (name,) if not on_windows or name.lower().endswith(".exe") else (f"{name}.exe",)
    current = _current_directory()
    seen: set[str] = set()
    for entry in source.get("PATH", "").split(os.pathsep):
        directory = entry.strip().strip('"') if on_windows else entry
        if not directory or not os.path.isabs(directory):
            continue
        normalized = os.path.normcase(os.path.realpath(directory))
        if normalized in seen or normalized == current:
            continue
        seen.add(normalized)
        for candidate in candidates:
            path = os.path.join(directory, candidate)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return os.path.abspath(path)
    return None


def _current_directory() -> str | None:
    try:
        return os.path.normcase(os.path.realpath(os.getcwd()))
    except OSError:
        return None
