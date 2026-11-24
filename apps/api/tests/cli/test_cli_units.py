from __future__ import annotations

import io
import json
import os
import re
import sys
from pathlib import Path

import httpx
import pytest

from bento.interfaces.cli.client import api_error
from bento.interfaces.cli.errors import CliError, exit_code_for
from bento.interfaces.cli.i18n import EN, ERRORS, ES, Translator, detect_lang
from bento.interfaces.cli.local_files import WalkOptions, collect, safe_local_name, sha256_file
from bento.interfaces.cli.output import Output, display_width, human_size
from bento.interfaces.cli.paths import escape_name, join_path, join_segments, parse_ref
from bento.interfaces.cli.profiles import Endpoint, Profile, is_loopback_url, pid_alive, read_endpoint, write_private_json
from bento.interfaces.cli.qr import render_qr
from bento.interfaces.cli.target import TargetOptions, resolve_target

CLI_SOURCE = Path(__file__).resolve().parents[2] / "src" / "bento" / "interfaces" / "cli"


# Paths ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "segments", "must_be_folder", "canonical"),
    [
        ("/", (), False, "/"),
        ("", (), False, "/"),
        ("Fotos/Viaje", ("Fotos", "Viaje"), False, "/Fotos/Viaje"),
        ("/Documentos/Facturas/2024/", ("Documentos", "Facturas", "2024"), True, "/Documentos/Facturas/2024"),
        ("/Café", ("Café",), False, "/Café"),
    ],
)
def test_parse_paths(text: str, segments: tuple[str, ...], must_be_folder: bool, canonical: str) -> None:
    ref = parse_ref(text)
    assert ref.segments == segments
    assert ref.must_be_folder is must_be_folder
    assert ref.canonical == canonical
    assert ref.item_id is None


def test_parse_id_refs() -> None:
    ref = parse_ref("id:folder_abc")
    assert ref.item_id == "folder_abc" and ref.text == "id:folder_abc" and not ref.is_root


@pytest.mark.parametrize(("text", "reason"), [("/a//b", "empty_segment"), ("/a/../b", "dot_segment"), ("./x", "dot_segment"), ("id:", "invalid_id"), ("/" + "a/" * 70, "too_long")])
def test_invalid_paths_are_usage_errors(text: str, reason: str) -> None:
    with pytest.raises(CliError) as caught:
        parse_ref(text)
    assert caught.value.exit_code == 2
    assert caught.value.details["reason"] == reason


def test_join_and_escape() -> None:
    assert join_path("/", "a") == "/a"
    assert join_path("/A/B", "c.pdf") == "/A/B/c.pdf"
    assert escape_name("AC/DC") == "AC\\/DC"
    assert join_path("/Música", "AC/DC") == "/Música/AC\\/DC"
    assert join_segments(parse_ref("/Fotos"), ("Viaje", "Dia1")).canonical == "/Fotos/Viaje/Dia1"
    assert parse_ref("/A/B").parent.canonical == "/A"


# Errors --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "status", "exit_code"),
    [
        ("path_not_found", 404, 3),
        ("folder_not_found", 404, 3),
        ("path_ambiguous", 409, 4),
        ("settings_revision_conflict", 409, 4),
        ("pairing_state_conflict", 409, 4),
        ("duplicate_asset", 409, 4),
        ("bento_unreachable", None, 5),
        ("desktop_not_running", None, 5),
        ("signed_out", None, 6),
        ("vault_locked", 503, 6),
        ("vault_not_found", 503, 6),
        ("telegram_not_authorized", 409, 6),
        ("telegram_not_available", 503, 6),
        ("telegram_flood_wait", 429, 8),
        ("validation_failed", 400, 2),
        ("something_new", 500, 1),
        ("something_new", 404, 3),
    ],
)
def test_exit_code_mapping(code: str, status: int | None, exit_code: int) -> None:
    assert exit_code_for(code, status) == exit_code


def test_setup_errors_name_the_next_command() -> None:
    assert CliError("vault_locked", "x").details["next"] == "bento join CODE"
    assert CliError("no_vault", "x").details["next"] == "bento setup"
    assert CliError("vault_locked", "x", {"next": "custom"}).details["next"] == "custom"


def _response(status: int, body: object, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers, request=httpx.Request("GET", "http://127.0.0.1/api/x"))


def test_api_error_shapes() -> None:
    domain = api_error(_response(409, {"error": {"code": "path_ambiguous", "message": "m", "details": {"candidates": []}, "request_id": "r"}}))
    assert (domain.code, domain.exit_code, domain.details) == ("path_ambiguous", 4, {"candidates": []})
    flood = api_error(_response(429, {"error": {"code": "telegram_flood_wait", "message": "m", "details": {}}}, {"Retry-After": "17"}))
    assert flood.exit_code == 8 and flood.details["retry_after_seconds"] == 17
    missing_route = api_error(_response(404, {"detail": "Not Found"}))
    assert missing_route.code == "endpoint_not_available" and missing_route.exit_code == 1
    schema = api_error(_response(422, {"detail": [{"loc": ["body", "name"], "msg": "x"}]}))
    assert schema.exit_code == 2 and schema.details["fields"] == ["name"]
    desktop = api_error(_response(401, {"detail": {"code": "desktop_auth_required", "message": "Request rejected"}}))
    assert desktop.code == "desktop_auth_required" and desktop.exit_code == 5
    token = api_error(_response(401, {"error": {"code": "api_token_required", "message": "m", "details": {}}}))
    assert token.exit_code == 5


def test_error_json_document() -> None:
    error = CliError("path_not_found", "Path not found", {"path": "/x"})
    assert error.to_json() == {"error": {"code": "path_not_found", "message": "Path not found", "details": {"path": "/x"}, "exit_code": 3}}


# Output --------------------------------------------------------------------------------------


def _output(json_mode: bool = False, lang: str = "es") -> tuple[Output, io.StringIO, io.StringIO]:
    stdout, stderr = io.StringIO(), io.StringIO()
    return Output(json_mode=json_mode, quiet=False, translator=Translator(lang), stdout=stdout, stderr=stderr, stdin=io.StringIO()), stdout, stderr


def test_sizes_follow_the_language() -> None:
    assert human_size(512) == "512 B"
    assert human_size(1536, "es") == "1,5 KB"
    assert human_size(1536, "en") == "1.5 KB"
    assert human_size(5 * 1024**3, "en") == "5.0 GB"


def test_table_alignment_counts_wide_characters() -> None:
    out, stdout, _ = _output()
    out.table(["A", "B"], [["🐙x", "1"], ["ab", "22"]])
    lines = stdout.getvalue().splitlines()
    assert display_width("🐙x") == 3
    # The second column starts at the same display column on every row.
    assert [display_width(line[: line.index(cell)]) for line, cell in zip(lines[1:], ["1", "22"], strict=True)] == [5, 5]


def test_json_errors_go_to_stderr_and_human_errors_are_localized() -> None:
    out, stdout, stderr = _output(json_mode=True)
    out.error(CliError("path_not_found", "Path not found", {"path": "/x"}))
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue())["error"]["exit_code"] == 3

    human, _, stderr = _output(lang="es")
    human.error(
        CliError("path_ambiguous", "m", {"path": "/Fotos", "candidates": [{"id": "folder_1", "kind": "folder", "path": "/Fotos", "created_at": None}]})
    )
    text = stderr.getvalue()
    assert "Hay varios elementos" in text and "id:folder_1" in text
    setup, _, stderr = _output(lang="en")
    setup.error(CliError("no_vault", "m"))
    assert "Next step: bento setup" in stderr.getvalue()


def test_every_translation_key_exists_in_both_languages() -> None:
    assert set(ES) == set(EN)
    assert set(ERRORS["es"]) == set(ERRORS["en"])
    used: set[str] = set()
    pattern = re.compile(r"""\bt\(\s*"([a-z_]+\.[a-z_.]+)\"""")
    for path in CLI_SOURCE.rglob("*.py"):
        used.update(pattern.findall(path.read_text(encoding="utf-8")))
    missing = sorted(key for key in used if key not in ES)
    assert missing == []


def test_detect_lang_order(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"lang": "en"}))
    assert detect_lang(None, {}) == "es"
    assert detect_lang(None, {"LANG": "en_US.UTF-8"}) == "en"
    assert detect_lang(None, {"LANG": "C.UTF-8"}) == "es"
    assert detect_lang(None, {"LANG": "es_CO.UTF-8"}, config) == "en"
    assert detect_lang(None, {"BENTO_LANG": "es", "LANG": "en_US"}, config) == "es"
    assert detect_lang("en", {"BENTO_LANG": "es"}) == "en"


# QR ------------------------------------------------------------------------------------------


def test_qr_rendering_uses_half_blocks_with_quiet_zone() -> None:
    qr = {"size": 2, "rows": ["10", "01"]}
    plain = render_qr(qr, ansi=False, quiet=1).splitlines()
    # 4x4 grid with quiet zone → 2 text rows of 4 characters; light modules are drawn.
    assert plain == ["█▀██", "██▄█"]
    colored = render_qr(qr, ansi=True, quiet=0)
    assert "\x1b[30;107m▀" in colored and colored.endswith("\x1b[0m")
    assert render_qr(None, ansi=False) == ""
    assert render_qr({"rows": "bad"}, ansi=False) == ""


def test_qr_from_the_real_matrix_is_square() -> None:
    from bento.interfaces.http.qr import qr_matrix

    matrix = qr_matrix("bento://join?v=1&c=K7Q2-MXR9-T4WA").model_dump()
    lines = render_qr(matrix, ansi=False).splitlines()
    assert len(lines) == (matrix["size"] + 4 + 1) // 2
    assert {len(line) for line in lines} == {matrix["size"] + 4}


# Local files ---------------------------------------------------------------------------------


def _tree(root: Path) -> Path:
    (root / "Viaje" / "sub").mkdir(parents=True)
    (root / "Viaje" / "a.jpg").write_bytes(b"a")
    (root / "Viaje" / "b.tmp").write_bytes(b"b")
    (root / "Viaje" / "sub" / "c.jpg").write_bytes(b"c")
    (root / "Viaje" / ".DS_Store").write_bytes(b"x")
    (root / "Viaje" / "._a.jpg").write_bytes(b"x")
    (root / "Viaje" / "Thumbs.db").write_bytes(b"x")
    (root / "Viaje" / ".git").mkdir()
    (root / "Viaje" / ".git" / "config").write_bytes(b"x")
    return root / "Viaje"


def _relative(result_files: list) -> set[str]:  # type: ignore[type-arg]
    return {"/".join((*item.relative_dir, item.name)) for item in result_files}


def test_walk_recreates_structure_and_skips_junk(tmp_path: Path) -> None:
    viaje = _tree(tmp_path)
    result = collect([str(viaje)], WalkOptions())
    assert _relative(result.files) == {"Viaje/a.jpg", "Viaje/b.tmp", "Viaje/sub/c.jpg"}
    reasons = {Path(item.path).name: item.reason for item in result.skipped}
    assert reasons == {".DS_Store": "junk", "._a.jpg": "junk", "Thumbs.db": "junk", ".git": "hidden"}


def test_walk_filters(tmp_path: Path) -> None:
    viaje = _tree(tmp_path)
    contents = collect([str(viaje) + os.sep], WalkOptions(exclude=("*.tmp", "sub")))
    assert _relative(contents.files) == {"a.jpg"}
    included = collect([str(viaje)], WalkOptions(include=("*.jpg",)))
    assert _relative(included.files) == {"Viaje/a.jpg", "Viaje/sub/c.jpg"}
    flat = collect([str(viaje)], WalkOptions(flatten=True))
    assert {item.relative_dir for item in flat.files} == {()}
    hidden = collect([str(viaje)], WalkOptions(hidden=True))
    assert "Viaje/.git/config" in _relative(hidden.files) and "Viaje/.DS_Store" in _relative(hidden.files)
    missing = collect([str(tmp_path / "nope")], WalkOptions())
    assert missing.missing == [tmp_path / "nope"]


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_symlinks_are_skipped_unless_followed_and_loops_stop(tmp_path: Path) -> None:
    viaje = _tree(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "o.jpg").write_bytes(b"o")
    (viaje / "link").symlink_to(outside)
    (viaje / "sub" / "loop").symlink_to(viaje)
    skipped = collect([str(viaje)], WalkOptions())
    assert {Path(item.path).name for item in skipped.skipped if item.reason == "symlink"} == {"link", "loop"}
    followed = collect([str(viaje)], WalkOptions(follow_symlinks=True))
    assert "Viaje/link/o.jpg" in _relative(followed.files)
    assert any(item.reason == "symlink" and Path(item.path).name == "loop" for item in followed.skipped)


def test_hash_and_safe_names(tmp_path: Path) -> None:
    file = tmp_path / "x.bin"
    file.write_bytes(b"hello")
    assert sha256_file(file) == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert safe_local_name("../../etc/passwd") == ".._.._etc_passwd"
    assert safe_local_name("..") == "archivo"
    assert safe_local_name("CON.txt") == "_CON.txt"
    assert safe_local_name('a<b>:"c"|?*.pdf') == "a_b___c____.pdf"


# Profiles and target resolution --------------------------------------------------------------


def test_profile_directories_and_private_files(tmp_path: Path) -> None:
    profile = Profile.load("work", tmp_path / "home")
    profile.ensure()
    assert profile.data_dir == tmp_path / "home" / "profiles" / "work" / "data"
    assert (profile.data_dir / "db").is_dir()
    write_private_json(profile.endpoint_file, {"url": "http://127.0.0.1:1"})
    if os.name == "posix":
        assert (profile.root.stat().st_mode & 0o777) == 0o700
        assert (profile.endpoint_file.stat().st_mode & 0o777) == 0o600
    with pytest.raises(CliError) as caught:
        Profile.load("../evil", tmp_path)
    assert caught.value.exit_code == 2


def test_endpoint_files_must_be_loopback(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    write_private_json(good, {"url": "http://127.0.0.1:5000/", "token": "t", "pid": 12, "kind": "desktop"})
    endpoint = read_endpoint(good)
    assert endpoint == Endpoint(kind="desktop", url="http://127.0.0.1:5000", token="t", pid=12)
    assert "token" not in endpoint.public()
    bad = tmp_path / "bad.json"
    write_private_json(bad, {"url": "http://evil.example:5000", "pid": 12})
    assert read_endpoint(bad) is None
    assert not is_loopback_url("https://127.0.0.1")
    assert read_endpoint(tmp_path / "missing.json") is None


def test_pid_alive() -> None:
    assert pid_alive(os.getpid())
    assert not pid_alive(None)
    assert not pid_alive(2**22 + 12345)


def _write_endpoint(path: Path, port: int, pid: int, kind: str) -> None:
    write_private_json(path, {"version": 1, "kind": kind, "url": f"http://127.0.0.1:{port}", "token": f"tok-{kind}", "pid": pid})


def test_target_resolution_order(tmp_path: Path) -> None:
    env = {"BENTO_DESKTOP_USER_DATA": str(tmp_path / "desktop")}
    profile = Profile.load("default", tmp_path / "home")
    desktop_file = tmp_path / "desktop" / "bento-desktop" / "cli-endpoint.json"
    healthy = lambda url, token: True  # noqa: E731
    started: list[str] = []

    def start(selected: Profile, timeout: float) -> Endpoint:
        started.append(selected.name)
        return Endpoint(kind="daemon", url="http://127.0.0.1:7777", token="new", pid=os.getpid())

    options = TargetOptions(profile=profile)
    # 1. --api-url / BENTO_API_URL wins.
    explicit = resolve_target(options, environ={**env, "BENTO_API_URL": "http://127.0.0.1:1", "BENTO_API_TOKEN": "x"}, check=healthy)
    assert (explicit.kind, explicit.token) == ("url", "x")
    # 2. A live desktop app.
    _write_endpoint(desktop_file, 5001, os.getpid(), "desktop")
    desktop = resolve_target(options, environ=env, check=healthy, start_daemon=start)
    assert (desktop.kind, desktop.url, desktop.token) == ("desktop", "http://127.0.0.1:5001", "tok-desktop")
    # --profile skips the desktop; --target daemon too.
    _write_endpoint(profile.endpoint_file, 5002, os.getpid(), "daemon")
    assert resolve_target(TargetOptions(profile=profile, profile_explicit=True), environ=env, check=healthy).kind == "daemon"
    assert resolve_target(TargetOptions(profile=profile, target="daemon"), environ=env, check=healthy).kind == "daemon"
    # 3. A dead desktop PID falls back to the profile daemon.
    _write_endpoint(desktop_file, 5001, 2**22 + 12345, "desktop")
    assert resolve_target(options, environ=env, check=healthy).url == "http://127.0.0.1:5002"
    # --target desktop never falls back.
    with pytest.raises(CliError) as caught:
        resolve_target(TargetOptions(profile=profile, target="desktop"), environ=env, check=healthy)
    assert caught.value.code == "desktop_not_running" and caught.value.exit_code == 5
    # 4. Nothing alive: start the daemon, unless --no-start.
    _write_endpoint(profile.endpoint_file, 5002, 2**22 + 12345, "daemon")
    with pytest.raises(CliError) as no_start:
        resolve_target(TargetOptions(profile=profile, no_start=True), environ=env, check=healthy)
    assert no_start.value.code == "daemon_not_running" and no_start.value.exit_code == 5
    target = resolve_target(options, environ=env, check=healthy, start_daemon=start)
    assert target.started and target.url == "http://127.0.0.1:7777" and started == ["default"]
    # An unhealthy endpoint is not used either.
    _write_endpoint(profile.endpoint_file, 5002, os.getpid(), "daemon")
    resolve_target(options, environ=env, check=lambda url, token: False, start_daemon=start)
    assert started == ["default", "default"]


def test_events_are_ndjson_on_stderr_only_in_json_mode() -> None:
    out, stdout, stderr = _output(json_mode=True)
    out.event("pairing_code", {"code": "K7Q2-MXR9-T4WA"})
    out.result({"ok": True})
    assert json.loads(stderr.getvalue()) == {"event": "pairing_code", "code": "K7Q2-MXR9-T4WA"}
    assert json.loads(stdout.getvalue()) == {"ok": True}
    human, human_stdout, human_stderr = _output(json_mode=False)
    human.event("pairing_code", {"code": "K7Q2-MXR9-T4WA"})
    assert human_stdout.getvalue() == "" and human_stderr.getvalue() == ""
