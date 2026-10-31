from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bento.adapters.backup.scanner import LocalFolderScanner, is_ignored_name
from bento.adapters.backup.suggestions import OsBackupSuggestions
from bento.application.backup import ScanDebouncer, ScannedFile, needs_upload, validate_source_path
from bento.domain.backup import BackupFile, BackupFileState, BackupSource, BackupSuggestionKind
from bento.domain.errors import BackupSourceInvalidError

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _source(path: Path, source_id: str = "bsrc_1") -> BackupSource:
    return BackupSource(id=source_id, path=str(path), label=path.name, enabled=True, created_at=NOW, updated_at=NOW)


def _reason(raw: str, data_dir: Path, existing: tuple[BackupSource, ...] = ()) -> str:
    scanner = LocalFolderScanner()
    with pytest.raises(BackupSourceInvalidError) as error:
        validate_source_path(scanner.inspect(raw), data_dir=data_dir, existing=existing)
    return error.value.details["reason"]


def test_hostile_backup_source_paths_are_rejected(tmp_path: Path) -> None:
    data_dir = tmp_path / "bento-data"
    (data_dir / "uploads").mkdir(parents=True)
    photos = tmp_path / "Fotos"
    (photos / "2024").mkdir(parents=True)
    a_file = tmp_path / "file.txt"
    a_file.write_text("x")
    root_link = tmp_path / "root-link"
    root_link.symlink_to(Path(tmp_path.anchor))

    assert _reason(str(tmp_path / "missing"), data_dir) == "not_found"
    assert _reason(str(a_file), data_dir) == "not_directory"
    assert _reason(tmp_path.anchor, data_dir) == "filesystem_root"
    assert _reason(str(root_link), data_dir) == "filesystem_root"
    assert _reason(str(data_dir), data_dir) == "inside_data_dir"
    assert _reason(str(data_dir / "uploads"), data_dir) == "inside_data_dir"
    assert _reason(str(photos / "2024" / ".." / ".." / "bento-data" / "uploads"), data_dir) == "inside_data_dir"
    assert _reason(str(photos), data_dir, (_source(photos),)) == "duplicate"
    assert _reason(str(photos / "2024"), data_dir, (_source(photos),)) == "overlap"
    assert _reason(str(tmp_path), data_dir, (_source(photos),)) == "overlap"
    with pytest.raises(ValueError, match="absolute"):
        LocalFolderScanner().inspect("relative/path")

    accepted = validate_source_path(LocalFolderScanner().inspect(str(photos / "2024" / "..")), data_dir=data_dir, existing=())
    assert accepted == photos.resolve()


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX permissions as non-root")
def test_unreadable_directories_are_rejected(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        assert _reason(str(locked), tmp_path / "data") == "not_readable"
    finally:
        locked.chmod(0o755)


def test_home_expansion_resolves_to_an_absolute_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.expanduser reads USERPROFILE on Windows
    (tmp_path / "Imágenes").mkdir()
    info = LocalFolderScanner().inspect("~/Imágenes")
    assert info.exists and info.is_dir and info.path == (tmp_path / "Imágenes").resolve()


@pytest.mark.parametrize(
    ("name", "ignored"),
    [
        (".DS_Store", True),
        (".git", True),
        ("Thumbs.db", True),
        ("desktop.ini", True),
        ("~$informe.docx", True),
        ("video.mp4.part", True),
        ("descarga.crdownload", True),
        ("notas.txt~", True),
        (".~lock.hoja.ods#", True),
        ("cache.tmp", True),
        ("$RECYCLE.BIN", True),
        ("foto.jpg", False),
        ("informe final.pdf", False),
        ("tmp", False),
    ],
)
def test_hidden_system_and_temporary_names(name: str, ignored: bool) -> None:
    assert is_ignored_name(name) is ignored


def test_needs_upload_by_size_mtime_and_failed_retry() -> None:
    done = BackupFile("s", "a.txt", 10, 100, BackupFileState.DONE, NOW, sha256="0" * 64, asset_id="asset_1")
    failed = BackupFile("s", "a.txt", 10, 100, BackupFileState.FAILED, NOW)
    assert needs_upload(None, ScannedFile("a.txt", 10, 100), retry_failed=False)
    assert not needs_upload(done, ScannedFile("a.txt", 10, 100), retry_failed=True)
    assert needs_upload(done, ScannedFile("a.txt", 11, 100), retry_failed=False)
    assert needs_upload(done, ScannedFile("a.txt", 10, 101), retry_failed=False)
    assert not needs_upload(failed, ScannedFile("a.txt", 10, 100), retry_failed=False)
    assert needs_upload(failed, ScannedFile("a.txt", 10, 100), retry_failed=True)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_debouncer_waits_two_seconds_after_the_last_event() -> None:
    clock = FakeClock()
    debouncer = ScanDebouncer(delay=2.0, max_delay=30.0, max_paths=3, clock=clock)
    debouncer.add("s1", "/data/a.jpg")
    clock.now += 1.5
    debouncer.add("s1", "/data/b.jpg")
    debouncer.add("s1", "/data/a.jpg")
    clock.now += 1.9
    assert debouncer.due() == []
    clock.now += 0.2
    assert debouncer.due() == [("s1", ("/data/a.jpg", "/data/b.jpg"))]
    assert debouncer.due() == []


def test_debouncer_flushes_busy_sources_and_overflows_to_a_full_scan() -> None:
    clock = FakeClock()
    debouncer = ScanDebouncer(delay=2.0, max_delay=10.0, max_paths=3, clock=clock)
    for index in range(12):
        debouncer.add("busy", f"/data/{index}.jpg")
        clock.now += 1.0
    assert debouncer.due() == [("busy", None)]
    debouncer.add("gone", "/x")
    debouncer.discard("gone")
    clock.now += 5
    assert debouncer.due() == []


def test_scanner_skips_hidden_temp_symlinks_and_excluded_dirs(tmp_path: Path) -> None:
    root = tmp_path / "Documentos"
    (root / "sub").mkdir(parents=True)
    (root / ".hidden").mkdir()
    (root / "bento").mkdir()
    (root / "a.txt").write_text("a")
    (root / "sub" / "b.pdf").write_text("b")
    (root / ".hidden" / "c.txt").write_text("c")
    (root / "bento" / "db.sqlite3").write_text("d")
    (root / "~$lock.docx").write_text("e")
    (root / "link.txt").symlink_to(root / "a.txt")
    (root / "linked-dir").symlink_to(root / "sub", target_is_directory=True)
    scanner = LocalFolderScanner()

    files = {item.relative_path for item in scanner.scan(root, exclude=(root / "bento",))}

    assert files == {"a.txt", "sub/b.pdf"}
    assert {item.relative_path for item in scanner.scan(root, start="sub")} == {"sub/b.pdf"}
    assert scanner.stat(root, "link.txt") is None
    assert scanner.stat(root, "linked-dir/b.pdf") is None
    assert scanner.stat(root, "../outside") is None
    assert scanner.stat(root, "sub/b.pdf").size_bytes == 1
    assert scanner.relative(root, str(root / "sub" / "b.pdf")) == "sub/b.pdf"
    assert scanner.relative(root, str(root / ".hidden" / "c.txt")) is None
    assert scanner.relative(root, str(tmp_path / "elsewhere.txt")) is None
    assert scanner.is_directory(root, "sub") and not scanner.is_directory(root, "linked-dir")


def test_suggestions_use_existing_xdg_folders_and_skip_missing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    for name in ("Imágenes", "Documentos", "Downloads"):
        (home / name).mkdir(parents=True)
    (home / ".config").mkdir()
    (home / ".config" / "user-dirs.dirs").write_text(
        'XDG_PICTURES_DIR="$HOME/Imágenes"\nXDG_DOCUMENTS_DIR="$HOME/Documentos"\nXDG_DESKTOP_DIR="$HOME/"\n# comment\n',
        encoding="utf-8",
    )

    linux = OsBackupSuggestions(home=home, platform="linux", environ={})
    items = {item.kind: item for item in linux.suggestions()}

    assert set(items) == {BackupSuggestionKind.PICTURES, BackupSuggestionKind.DOCUMENTS, BackupSuggestionKind.DOWNLOADS}
    assert items[BackupSuggestionKind.PICTURES].label == "Imágenes"
    assert items[BackupSuggestionKind.PICTURES].path == str((home / "Imágenes").resolve())

    (home / "Pictures").mkdir()
    mac = {item.kind for item in OsBackupSuggestions(home=home, platform="darwin", environ={}).suggestions()}
    assert mac == {BackupSuggestionKind.PICTURES, BackupSuggestionKind.DOWNLOADS}

    profile = tmp_path / "Users" / "ana"
    (profile / "Desktop").mkdir(parents=True)
    onedrive = tmp_path / "OneDrive"
    (onedrive / "Documents").mkdir(parents=True)
    windows = OsBackupSuggestions(
        home=profile, platform="win32", environ={"USERPROFILE": str(profile), "OneDrive": str(onedrive)}
    ).suggestions()
    assert {(item.kind, item.path) for item in windows} == {
        (BackupSuggestionKind.DESKTOP, str((profile / "Desktop").resolve())),
        (BackupSuggestionKind.DOCUMENTS, str((onedrive / "Documents").resolve())),
    }
