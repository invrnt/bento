"""CLI journeys against a real API (local storage) on a loopback thread.

When agent 31's CLI-support endpoints are not in this checkout yet, `cli_endpoints_shim` provides the same
contract; once they are merged the very same tests run against the real endpoints.
"""

from __future__ import annotations

from pathlib import Path

from tests.cli.conftest import LiveApi


def _tree(root: Path) -> None:
    (root / "Viaje" / "Dia1").mkdir(parents=True)
    (root / "Viaje" / "Dia2").mkdir(parents=True)
    (root / "Viaje" / "Dia1" / "playa.txt").write_text("arena y mar")
    (root / "Viaje" / "Dia1" / "copia.txt").write_text("mismo contenido")
    (root / "Viaje" / "Dia2" / "misma.txt").write_text("mismo contenido")
    (root / "Viaje" / "Dia2" / "notas.md").write_text("# notas del viaje")
    (root / "Viaje" / ".DS_Store").write_text("junk")
    (root / "Viaje" / ".oculto").write_text("hidden")


def test_mkdir_p_is_idempotent_and_reuses_folders(live_api: LiveApi) -> None:
    first = live_api.json("mkdir", "-p", "/Documentos/Facturas/2024")
    second = live_api.json("mkdir", "-p", "Documentos/Facturas/2024/")
    assert first["items"][0]["path"] == "/Documentos/Facturas/2024"
    assert first["items"][0]["created"] is True
    assert second["items"][0]["created"] is False
    assert second["items"][0]["id"] == first["items"][0]["id"]

    exists = live_api.cli("mkdir", "/Documentos", "--json")
    assert exists.code == 4 and exists.error["code"] == "path_exists"
    missing_parent = live_api.cli("mkdir", "/Nada/Mas", "--json")
    assert missing_parent.code == 3 and missing_parent.error["code"] == "path_not_found"
    plain = live_api.json("mkdir", "/Documentos/Contratos")
    assert plain["items"][0]["path"] == "/Documentos/Contratos"


def test_upload_tree_then_rerun_uploads_nothing(live_api: LiveApi, tmp_path: Path) -> None:
    source = tmp_path / "src"
    _tree(source)

    summary = live_api.json("upload", str(source / "Viaje"), "--to", "/Fotos")
    assert summary["uploaded"] == 3
    assert summary["duplicates"] == 1  # identical content inside the batch
    assert summary["failed"] == 0
    statuses = {Path(item["local_path"]).name: item for item in summary["items"]}
    assert statuses["playa.txt"]["path"] == "/Fotos/Viaje/Dia1/playa.txt"
    assert statuses[".DS_Store"]["reason"] == "junk"
    assert statuses[".oculto"]["reason"] == "hidden"

    listing = live_api.json("ls", "/Fotos/Viaje")
    assert [item["name"] for item in listing["items"]] == ["Dia1", "Dia2"]
    assert listing["items"][0]["path"] == "/Fotos/Viaje/Dia1"

    again = live_api.json("upload", str(source / "Viaje"), "--to", "/Fotos")
    assert again["uploaded"] == 0
    assert again["duplicates"] == 4
    assert {item["path"] for item in again["items"] if item["status"] == "duplicate"} >= {"/Fotos/Viaje/Dia1/playa.txt"}

    tree = live_api.json("tree", "/Fotos", "--depth", "5")
    assert tree["root"]["children"][0]["name"] == "Viaje"
    human = live_api.cli("tree", "/Fotos")
    assert "└── Viaje/" in human.stdout


def test_contents_only_flatten_and_dry_run(live_api: LiveApi, tmp_path: Path) -> None:
    source = tmp_path / "src"
    _tree(source)
    dry = live_api.json("upload", str(source / "Viaje") + "/", "--to", "/Plano", "--flatten", "--dry-run")
    assert dry["dry_run"] is True and dry["planned"] == 3 and dry["uploaded"] == 0
    assert live_api.cli("ls", "/Plano", "--json").code == 3  # dry run created nothing

    flat = live_api.json("upload", str(source / "Viaje") + "/", "--to", "/Plano", "--flatten", "--include", "*.txt")
    assert flat["uploaded"] == 2
    names = sorted(item["name"] for item in live_api.json("ls", "/Plano")["items"])
    assert names == ["copia.txt", "playa.txt"]


def test_organize_move_rename_remove_and_restore(live_api: LiveApi, tmp_path: Path) -> None:
    note = tmp_path / "factura.txt"
    note.write_text("factura de la luz")
    live_api.json("upload", str(note), "--to", "/Entrada")
    live_api.json("mkdir", "-p", "/Documentos/Facturas")

    moved = live_api.json("mv", "/Entrada/factura.txt", "/Documentos/Facturas")
    assert moved["items"][0]["path"] == "/Documentos/Facturas/factura.txt"
    renamed = live_api.json("mv", "/Documentos/Facturas/factura.txt", "/Documentos/Facturas/luz-2024.txt")
    assert renamed["items"][0]["path"] == "/Documentos/Facturas/luz-2024.txt"
    again = live_api.json("rename", "/Documentos/Facturas/luz-2024.txt", "luz-enero-2024.txt")
    assert again["path"] == "/Documentos/Facturas/luz-enero-2024.txt"

    stat = live_api.json("stat", "/Documentos/Facturas/luz-enero-2024.txt", "/Documentos")
    assert [item["kind"] for item in stat["items"]] == ["asset", "folder"]
    asset_id = stat["items"][0]["asset"]["id"]
    assert live_api.json("stat", f"id:{asset_id}")["items"][0]["path"] == "/Documentos/Facturas/luz-enero-2024.txt"

    folder_rm = live_api.cli("rm", "/Documentos/Facturas", "--json")
    assert folder_rm.code == 2  # folders need -r
    removed = live_api.json("rm", "/Documentos/Facturas/luz-enero-2024.txt")
    assert removed["items"][0]["status"] == "trashed"
    assert live_api.cli("stat", "/Documentos/Facturas/luz-enero-2024.txt", "--json").code == 3
    trash = live_api.json("trash")
    assert [item["name"] for item in trash["items"]] == ["luz-enero-2024.txt"]
    restored = live_api.json("trash", "restore", "luz-enero-2024.txt")
    assert restored["restored"] == 1
    assert live_api.json("stat", "/Documentos/Facturas/luz-enero-2024.txt")["items"][0]["kind"] == "asset"

    partial = live_api.cli("rm", "/Documentos/Facturas/luz-enero-2024.txt", "/No/Existe", "--json")
    assert partial.code == 7
    assert [item["status"] for item in partial.json["items"]] == ["trashed", "failed"]

    purge = live_api.cli("trash", "purge", "luz-enero-2024.txt", "--json")
    assert purge.code == 2 and purge.error["code"] == "confirmation_required"


def test_ambiguous_names_need_ids(live_api: LiveApi) -> None:
    live_api.cli("api", "POST", "/drive/folders", "--data", '{"name": "Gemelas"}', "--json")
    live_api.cli("api", "POST", "/drive/folders", "--data", '{"name": "Gemelas"}', "--json")
    result = live_api.cli("ls", "/Gemelas", "--json")
    assert result.code == 4
    assert result.error["code"] == "path_ambiguous"
    candidates = result.error["details"]["candidates"]
    assert len(candidates) == 2
    assert live_api.json("ls", f"id:{candidates[0]['id']}")["items"] == []
    # mkdir -p reuses the oldest of the twins instead of failing or creating a third.
    ensured = live_api.json("mkdir", "-p", "/Gemelas/Dentro")
    assert ensured["items"][0]["path"] == "/Gemelas/Dentro"


def test_find_download_round_trip_and_cat(live_api: LiveApi, tmp_path: Path) -> None:
    source = tmp_path / "src"
    _tree(source)
    live_api.json("upload", str(source / "Viaje"), "--to", "/Fotos")

    found = live_api.json("find", "playa")
    assert any(item["path"] == "/Fotos/Viaje/Dia1/playa.txt" for item in found["items"])

    target = tmp_path / "out"
    downloaded = live_api.json("download", "-r", "/Fotos/Viaje", "--to", str(target))
    assert downloaded["failed"] == 0 and downloaded["downloaded"] == 3
    assert (target / "Viaje" / "Dia1" / "playa.txt").read_text() == "arena y mar"
    assert (target / "Viaje" / "Dia2" / "notas.md").read_text() == "# notas del viaje"

    second = live_api.json("download", "-r", "/Fotos/Viaje", "--to", str(target))
    assert second["downloaded"] == 0 and second["skipped"] == 3

    single = live_api.json("download", "/Fotos/Viaje/Dia1/playa.txt", "--to", str(tmp_path / "one"), "--overwrite")
    assert single["downloaded"] == 1
    assert live_api.cli("download", "/Fotos/Viaje", "--json").code == 2  # folders need -r

    cat = live_api.cli("cat", "/Fotos/Viaje/Dia2/notas.md")
    assert cat.code == 0 and cat.stdout == "# notas del viaje"


def test_status_and_human_ls_in_spanish(live_api: LiveApi) -> None:
    status = live_api.cli("status", "--json")
    assert status.code == 0
    assert status.json["setup"] == {"required": False, "reason": None, "next": None}
    assert status.json["target"]["kind"] == "url"
    live_api.json("mkdir", "-p", "/Documentos")
    human = live_api.cli("ls", "/", "-l", "--lang", "es")
    assert "carpeta" in human.stdout and "Documentos/" in human.stdout
    empty = live_api.cli("ls", "/Documentos", "--lang", "es")
    assert "está vacía" in empty.stdout
