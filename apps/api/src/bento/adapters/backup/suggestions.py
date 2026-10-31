"""Well-known user folders (Pictures, Documents, Desktop, Downloads) that exist on this OS account."""

from __future__ import annotations

import os
import re
import shlex
import sys
from collections.abc import Mapping
from pathlib import Path

from bento.domain.backup import BackupSuggestion, BackupSuggestionKind

_DEFAULT_NAMES = {
    BackupSuggestionKind.PICTURES: "Pictures",
    BackupSuggestionKind.DOCUMENTS: "Documents",
    BackupSuggestionKind.DESKTOP: "Desktop",
    BackupSuggestionKind.DOWNLOADS: "Downloads",
}
_XDG_KEYS = {
    BackupSuggestionKind.PICTURES: "XDG_PICTURES_DIR",
    BackupSuggestionKind.DOCUMENTS: "XDG_DOCUMENTS_DIR",
    BackupSuggestionKind.DESKTOP: "XDG_DESKTOP_DIR",
    BackupSuggestionKind.DOWNLOADS: "XDG_DOWNLOAD_DIR",
}
_XDG_LINE = re.compile(r"^\s*(XDG_[A-Z]+_DIR)\s*=\s*(.+?)\s*$")


class OsBackupSuggestions:
    def __init__(
        self,
        *,
        home: Path | None = None,
        platform: str = sys.platform,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._environ = dict(os.environ if environ is None else environ)
        self._platform = platform
        self._home = home or Path(os.path.expanduser("~"))

    def suggestions(self) -> tuple[BackupSuggestion, ...]:
        items: list[BackupSuggestion] = []
        seen: set[Path] = set()
        for kind, candidates in self._candidates().items():
            for candidate in candidates:
                try:
                    resolved = candidate.resolve(strict=True)
                except OSError:
                    continue
                if not resolved.is_dir() or resolved == self._home.resolve() or resolved in seen:
                    continue
                seen.add(resolved)
                items.append(BackupSuggestion(path=str(resolved), label=resolved.name, kind=kind))
                break
        return tuple(items)

    def _candidates(self) -> dict[BackupSuggestionKind, list[Path]]:
        if self._platform == "win32":
            profile = Path(self._environ.get("USERPROFILE") or self._home)
            onedrive = self._environ.get("OneDrive") or self._environ.get("ONEDRIVE")
            result: dict[BackupSuggestionKind, list[Path]] = {}
            for kind, name in _DEFAULT_NAMES.items():
                paths = [profile / name]
                if onedrive and kind != BackupSuggestionKind.DOWNLOADS:
                    paths.append(Path(onedrive) / name)
                result[kind] = paths
            return result
        if self._platform == "darwin":
            return {kind: [self._home / name] for kind, name in _DEFAULT_NAMES.items()}
        xdg = self._xdg_user_dirs()
        return {
            kind: [path for path in (xdg.get(_XDG_KEYS[kind]), self._home / name) if path is not None]
            for kind, name in _DEFAULT_NAMES.items()
        }

    def _xdg_user_dirs(self) -> dict[str, Path]:
        config_home = Path(self._environ.get("XDG_CONFIG_HOME") or self._home / ".config")
        try:
            content = (config_home / "user-dirs.dirs").read_text(encoding="utf-8")
        except OSError:
            return {}
        result: dict[str, Path] = {}
        for line in content.splitlines():
            match = _XDG_LINE.match(line)
            if match is None or line.lstrip().startswith("#"):
                continue
            try:
                value = " ".join(shlex.split(match.group(2)))
            except ValueError:
                continue
            value = value.replace("${HOME}", str(self._home)).replace("$HOME", str(self._home))
            path = Path(value)
            if path.is_absolute():
                result[match.group(1)] = path
        return result
