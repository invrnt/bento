from __future__ import annotations

from pathlib import Path

import pytest

from bento.adapters.models import filesystem_store
from bento.adapters.models.filesystem_store import FilesystemModelStore
from tests.fakes.model_host import synthetic_blob
from tests.unit.models.model_fakes import files_under, tiny_spec

BLOB = synthetic_blob(256 * 1024, seed=7)


def install(store: FilesystemModelStore, data: bytes = BLOB) -> Path:
    spec = tiny_spec(BLOB)
    final = store.path_for(spec, spec.weights)
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(data)
    return final


def test_layout_is_model_revision_file_under_data_dir_models(tmp_path: Path) -> None:
    store = FilesystemModelStore(tmp_path / "models")
    spec = tiny_spec(BLOB)

    final = store.path_for(spec, spec.weights)
    part = store.part_path_for(spec, spec.weights)

    assert final == tmp_path / "models" / spec.model_id / spec.revision / "tiny-model.gguf"
    assert part == final.with_name("tiny-model.gguf.part")


def test_verify_hashes_once_then_trusts_the_size_and_mtime_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FilesystemModelStore(tmp_path / "models")
    spec = tiny_spec(BLOB)
    install(store)
    hashes: list[Path] = []
    real = filesystem_store.sha256_file

    def counting(path: Path) -> str:
        hashes.append(path)
        return real(path)

    monkeypatch.setattr(filesystem_store, "sha256_file", counting)

    assert store.verify(spec) is True
    assert store.verify(spec) is True
    assert len(hashes) == 1
    assert store.installed()[0].model_id == spec.model_id
    assert store.installed()[0].size_bytes == len(BLOB)


def test_verify_rejects_a_wrong_or_changed_file(tmp_path: Path) -> None:
    store = FilesystemModelStore(tmp_path / "models")
    spec = tiny_spec(BLOB)
    final = install(store, bytes(len(BLOB)))

    assert store.verify(spec) is False

    final.write_bytes(BLOB[:-1])
    assert store.verify(spec) is False
    assert store.installed() == ()


def test_verify_without_a_file_is_false(tmp_path: Path) -> None:
    store = FilesystemModelStore(tmp_path / "models")

    assert store.verify(tiny_spec(BLOB)) is False
    assert store.installed() == ()


def test_remove_frees_every_byte_and_leaves_no_directories(tmp_path: Path) -> None:
    root = tmp_path / "models"
    store = FilesystemModelStore(root)
    spec = tiny_spec(BLOB)
    install(store)
    assert store.verify(spec)
    store.write_license(spec, "Apache License\n", "notice\n")
    part = store.part_path_for(spec, spec.weights)
    part.write_bytes(b"x" * 1000)
    expected = sum(path.stat().st_size for path in files_under(root))

    freed = store.remove(spec)

    assert freed == expected
    assert files_under(root) == []
    assert not (root / spec.model_id).exists()
    assert store.remove(spec) == 0


def test_discard_partial_keeps_the_final_file(tmp_path: Path) -> None:
    store = FilesystemModelStore(tmp_path / "models")
    spec = tiny_spec(BLOB)
    final = install(store)
    part = store.part_path_for(spec, spec.weights)
    part.write_bytes(b"x" * 10)
    part.with_name(part.name + ".meta").write_text("{}")

    assert store.discard_partial(spec, spec.weights) == 10
    assert final.exists()
    assert not part.exists()
    assert store.partial_bytes(spec, spec.weights) == 0


def test_write_license_ships_the_text_next_to_the_file(tmp_path: Path) -> None:
    store = FilesystemModelStore(tmp_path / "models")
    spec = tiny_spec(BLOB)

    store.write_license(spec, "Apache License\n", None)

    directory = store.revision_dir(spec)
    assert (directory / "LICENSE").read_text() == "Apache License\n"
    assert not (directory / "NOTICE").exists()


def test_free_bytes_probes_the_nearest_existing_directory(tmp_path: Path) -> None:
    store = FilesystemModelStore(tmp_path / "not" / "yet" / "models")

    assert store.free_bytes() > 0
