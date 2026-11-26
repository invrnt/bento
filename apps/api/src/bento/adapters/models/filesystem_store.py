"""`ModelStorePort` on the local filesystem.

Layout under `<data_dir>/models`:

    <model_id>/<revision>/<file>            verified model file (atomically renamed from `.part`)
    <model_id>/<revision>/<file>.part       download in progress (resumable)
    <model_id>/<revision>/<file>.part.meta  resume metadata written by the downloader (ETag)
    <model_id>/<revision>/<file>.verified   marker: size + mtime + sha256 of the last full verification
    <model_id>/<revision>/LICENSE           license text shipped next to the file (Apache-2.0 §4)
    <model_id>/<revision>/NOTICE            per-model notice (source pin, use-policy link), when known

`model_id`, `revision` and file names are validated by the domain (`ModelSpec`/`ModelFile`); paths are
checked again here so nothing outside the root is ever written or deleted.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from bento.domain.smart_search import ModelFile, ModelFileRole, ModelSpec
from bento.ports.models import InstalledModel

PART_SUFFIX = ".part"
META_SUFFIX = ".part.meta"
MARKER_SUFFIX = ".verified"
LICENSE_NAME = "LICENSE"
NOTICE_NAME = "NOTICE"
_HASH_BLOCK = 4 * 1024 * 1024


class FilesystemModelStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    # -- paths ---------------------------------------------------------------------------

    def revision_dir(self, spec: ModelSpec) -> Path:
        return self._inside(self._root / spec.model_id / spec.revision)

    def path_for(self, spec: ModelSpec, file: ModelFile) -> Path:
        return self._inside(self.revision_dir(spec) / file.name)

    def part_path_for(self, spec: ModelSpec, file: ModelFile) -> Path:
        final = self.path_for(spec, file)
        return final.with_name(final.name + PART_SUFFIX)

    def partial_bytes(self, spec: ModelSpec, file: ModelFile) -> int:
        return _size(self.part_path_for(spec, file))

    # -- state ---------------------------------------------------------------------------

    def installed(self) -> tuple[InstalledModel, ...]:
        """Weights files whose verification marker still matches the file on disk."""
        found: list[InstalledModel] = []
        if not self._root.is_dir():
            return ()
        for model_dir in sorted(p for p in self._root.iterdir() if p.is_dir() and not p.is_symlink()):
            for revision_dir in sorted(p for p in model_dir.iterdir() if p.is_dir() and not p.is_symlink()):
                for marker in sorted(revision_dir.glob(f"*{MARKER_SUFFIX}")):
                    data = _read_marker(marker)
                    if data is None or data.get("role") != ModelFileRole.WEIGHTS.value:
                        continue
                    final = marker.with_name(marker.name[: -len(MARKER_SUFFIX)])
                    if _marker_matches(final, data):
                        found.append(
                            InstalledModel(
                                model_id=model_dir.name,
                                revision=revision_dir.name,
                                path=final,
                                size_bytes=int(data["size_bytes"]),
                            )
                        )
        return tuple(found)

    def free_bytes(self) -> int:
        probe = self._root
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        try:
            return int(shutil.disk_usage(probe).free)
        except OSError:
            return 0

    def verify(self, spec: ModelSpec) -> bool:
        """The weights file is complete and matches its pinned sha256.

        A full re-hash happens only when the size or mtime differs from the last verification marker."""
        return self.verify_file(spec, spec.weights)

    def verify_file(self, spec: ModelSpec, file: ModelFile) -> bool:
        final = self.path_for(spec, file)
        marker = final.with_name(final.name + MARKER_SUFFIX)
        try:
            stat = final.stat()
        except OSError:
            return False
        if stat.st_size != file.size_bytes:
            _unlink(marker)
            return False
        data = _read_marker(marker)
        if data is not None and data.get("sha256") == file.sha256 and _marker_matches(final, data):
            return True
        if sha256_file(final) != file.sha256:
            _unlink(marker)
            return False
        _write_marker(marker, final, file)
        return True

    # -- writes --------------------------------------------------------------------------

    def ensure_dir(self, spec: ModelSpec) -> Path:
        directory = self.revision_dir(spec)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def discard_partial(self, spec: ModelSpec, file: ModelFile) -> int:
        """Delete the `.part` file and its resume metadata; return the bytes freed."""
        part = self.part_path_for(spec, file)
        freed = _size(part)
        _unlink(part)
        _unlink(part.with_name(part.name[: -len(PART_SUFFIX)] + META_SUFFIX))
        return freed

    def write_license(self, spec: ModelSpec, license_text: str, notice_text: str | None = None) -> None:
        directory = self.ensure_dir(spec)
        _write_text_atomic(directory / LICENSE_NAME, license_text)
        if notice_text:
            _write_text_atomic(directory / NOTICE_NAME, notice_text)

    def remove(self, spec: ModelSpec) -> int:
        """Delete everything stored for `spec`'s revision (final, partial, markers, license); return bytes freed.

        Files that cannot be deleted right now (Windows keeps a mapped file open) are skipped; the next
        `remove` deletes them."""
        directory = self.revision_dir(spec)
        if not directory.exists():
            return 0
        freed = 0
        for path in sorted(directory.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_symlink() or path.is_file():
                size = 0 if path.is_symlink() else _size(path)
                try:
                    path.unlink()
                    freed += size
                except FileNotFoundError:
                    continue
                except OSError:
                    continue
            elif path.is_dir():
                _rmdir(path)
        _rmdir(directory)
        _rmdir(directory.parent)
        return freed

    def _inside(self, path: Path) -> Path:
        root = self._root.resolve()
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError("Model path escapes the models directory")
        return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_HASH_BLOCK):
            digest.update(block)
    return digest.hexdigest()


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _rmdir(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


def _read_marker(marker: Path) -> dict[str, object] | None:
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _marker_matches(final: Path, data: dict[str, object]) -> bool:
    try:
        stat = final.stat()
    except OSError:
        return False
    return data.get("size_bytes") == stat.st_size and data.get("mtime_ns") == stat.st_mtime_ns


def _write_marker(marker: Path, final: Path, file: ModelFile) -> None:
    stat = final.stat()
    payload = {
        "name": file.name,
        "role": file.role.value,
        "sha256": file.sha256,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    _write_text_atomic(marker, json.dumps(payload, sort_keys=True))


def _write_text_atomic(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
