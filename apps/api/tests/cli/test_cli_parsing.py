from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from bento.interfaces.cli.app import build_parser
from bento.interfaces.cli.catalog import all_commands, catalog_document
from bento.interfaces.cli.completion import SHELLS, completion_script
from tests.cli.conftest import CliResult

# Minimal valid argv for every runnable command (positionals and required flags).
SAMPLES: dict[str, list[str]] = {
    "setup": ["setup"],
    "status": ["status"],
    "login": ["login", "--phone", "+573001112233", "--code", "12345"],
    "logout": ["logout", "--yes"],
    "whoami": ["whoami"],
    "vault": ["vault"],
    "vault status": ["vault", "status"],
    "vault create": ["vault", "create"],
    "vault unlock": ["vault", "unlock", "--recovery-code", "AAAA-BBBB"],
    "vault recovery rotate": ["vault", "recovery", "rotate", "--yes"],
    "vault recovery verify": ["vault", "recovery", "verify", "AAAA-BBBB"],
    "vault recovery confirm": ["vault", "recovery", "confirm", "BBBB"],
    "pair": ["pair", "--wait"],
    "pair status": ["pair", "status", "pair_1"],
    "pair approve": ["pair", "approve", "pair_1"],
    "pair reject": ["pair", "reject", "pair_1"],
    "pair cancel": ["pair", "cancel", "pair_1"],
    "pair confirm": ["pair", "confirm", "pair_1"],
    "pair request": ["pair", "request", "--no-wait"],
    "pair requests": ["pair", "requests"],
    "pair review": ["pair", "review", "req_1"],
    "pair accept": ["pair", "accept", "req_1"],
    "pair deny": ["pair", "deny", "req_1"],
    "join": ["join", "K7Q2-MXR9-T4WA"],
    "devices": ["devices", "--include-removed"],
    "devices ls": ["devices", "ls"],
    "devices rename": ["devices", "rename", "dev_1", "Portátil"],
    "devices remove": ["devices", "remove", "dev_1", "--exclude", "dev_2", "dev_3", "--yes"],
    "devices ack": ["devices", "ack", "dev_1"],
    "ls": ["ls", "/Fotos", "-l", "--all"],
    "tree": ["tree", "/", "--depth", "2", "--no-files"],
    "stat": ["stat", "/a", "id:asset_1"],
    "mkdir": ["mkdir", "-p", "/a/b"],
    "mv": ["mv", "/a", "/b", "/c"],
    "rename": ["rename", "/a", "b"],
    "rm": ["rm", "-r", "/a"],
    "open": ["open", "/a.pdf"],
    "upload": ["upload", "a", "b", "--to", "/X", "--exclude", "*.tmp", "--include", "*.jpg", "--jobs", "3", "--dry-run"],
    "download": ["download", "/a", "--to", ".", "-r", "--overwrite"],
    "cat": ["cat", "/a.txt"],
    "find": ["find", "luz", "--in", "/Documentos", "--type", "document", "--from", "2024-01-01", "--to", "2024-12-31"],
    "photos": ["photos"],
    "photos timeline": ["photos", "timeline", "--limit", "10"],
    "albums": ["albums"],
    "albums ls": ["albums", "ls"],
    "albums create": ["albums", "create", "Viaje"],
    "albums show": ["albums", "show", "Viaje"],
    "albums add": ["albums", "add", "Viaje", "/a.jpg"],
    "albums remove": ["albums", "remove", "id:album_1", "/a.jpg"],
    "favorite": ["favorite", "/a.jpg", "--off"],
    "trash": ["trash", "--all"],
    "trash ls": ["trash", "ls"],
    "trash restore": ["trash", "restore", "id:asset_1"],
    "trash purge": ["trash", "purge", "id:asset_1", "--yes"],
    "trash empty": ["trash", "empty", "--yes"],
    "backup": ["backup"],
    "backup ls": ["backup", "ls"],
    "backup add": ["backup", "add", ".", "--label", "Docs"],
    "backup remove": ["backup", "remove", "src_1"],
    "backup enable": ["backup", "enable", "src_1"],
    "backup disable": ["backup", "disable", "src_1"],
    "backup scan": ["backup", "scan", "src_1"],
    "backup suggestions": ["backup", "suggestions"],
    "backup policy": ["backup", "policy", "--pause", "--pause-on-battery", "off", "--bandwidth-kbps", "500"],
    "sync": ["sync"],
    "sync status": ["sync", "status"],
    "sync now": ["sync", "now"],
    "activity": ["activity", "--watch"],
    "jobs": ["jobs", "--state", "failed"],
    "jobs ls": ["jobs", "ls"],
    "jobs retry": ["jobs", "retry", "job_1"],
    "reindex": ["reindex"],
    "telegram chats": ["telegram", "chats", "--query", "Ana"],
    "share": ["share", "/a.jpg", "--chat", "42", "--caption", "hola", "--yes"],
    "import": ["import", "--chat", "42", "--message-ids", "1", "2"],
    "import list": ["import", "list", "--chat", "42", "--kind", "photo"],
    "settings": ["settings"],
    "settings ls": ["settings", "ls"],
    "settings get": ["settings", "get", "ocr_provider"],
    "settings set": ["settings", "set", "ocr_provider=disabled"],
    "settings schema": ["settings", "schema"],
    "doctor": ["doctor"],
    "version": ["version"],
    "daemon": ["daemon"],
    "daemon status": ["daemon", "status"],
    "daemon start": ["daemon", "start"],
    "daemon stop": ["daemon", "stop"],
    "daemon restart": ["daemon", "restart"],
    "daemon run": ["daemon", "run"],
    "daemon logs": ["daemon", "logs", "-f", "-n", "10", "--name", "api"],
    "daemon install-service": ["daemon", "install-service"],
    "daemon uninstall-service": ["daemon", "uninstall-service"],
    "completion": ["completion", "bash"],
    "config lang": ["config", "lang", "en"],
    "commands": ["commands"],
    "guide": ["guide"],
    "api": ["api", "GET", "/drive/items", "--query", "limit=1", "--data", "{}"],
}


def runnable_names() -> set[str]:
    names = set()
    for command in all_commands():
        if command.handler is not None or command.default_child:
            names.add(command.name)
    return names


def test_every_runnable_command_has_a_parsing_sample() -> None:
    assert runnable_names() == set(SAMPLES)


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_every_command_parses_and_dispatches(name: str) -> None:
    parser = build_parser("en")
    args = parser.parse_args(SAMPLES[name])
    command = next(command for command in all_commands() if command.name == name)
    expected = command.handler
    if command.default_child:
        expected = next(child.handler for child in all_commands() if child.path == (*command.path, command.default_child))
    assert args._handler is expected


def test_global_flags_work_before_and_after_the_command() -> None:
    parser = build_parser("es")
    before = parser.parse_args(["--json", "--profile", "work", "ls", "/A"])
    after = parser.parse_args(["ls", "/A", "--json", "--profile", "work", "-y", "--timeout", "5"])
    for args in (before, after):
        assert args.json is True and args.profile == "work" and args.path == "/A"
    assert after.yes is True and after.timeout == 5.0


def test_subcommand_specific_values() -> None:
    parser = build_parser("en")
    args = parser.parse_args(SAMPLES["import list"])
    assert args.list_chat == 42 and args.kind == "photo"
    args = parser.parse_args(SAMPLES["devices remove"])
    assert args.exclude == ["dev_2", "dev_3"]
    args = parser.parse_args(["tree"])
    assert args.files is True and args.depth == 3


def test_usage_errors_are_json_with_exit_2(mock_cli: Callable[..., CliResult]) -> None:
    result = mock_cli(["ls", "--json", "--bogus"], lambda request: httpx.Response(500))
    assert result.code == 2
    assert result.stdout == ""
    assert result.error["code"] == "usage_error" and result.error["exit_code"] == 2
    missing = mock_cli(["mv", "/only-one", "--json"], lambda request: httpx.Response(500))
    assert missing.code == 2


def test_group_without_subcommand_is_a_usage_error(mock_cli: Callable[..., CliResult]) -> None:
    result = mock_cli(["vault", "recovery", "--json"], lambda request: httpx.Response(500))
    assert result.code == 2
    assert result.error["details"]["command"] == "vault recovery"


def test_no_arguments_prints_help(mock_cli: Callable[..., CliResult]) -> None:
    result = mock_cli([], lambda request: httpx.Response(500))
    assert result.code == 0 and "bento setup" in result.stdout


def test_bento_json_env_enables_json(mock_cli: Callable[..., CliResult]) -> None:
    result = mock_cli(["commands"], lambda request: httpx.Response(500), env={"BENTO_JSON": "1"})
    assert json.loads(result.stdout)["name"] == "bento"


def test_commands_catalog_shape(mock_cli: Callable[..., CliResult]) -> None:
    result = mock_cli(["commands", "--json"], lambda request: httpx.Response(500))
    document = result.json
    assert document == catalog_document(document["version"])
    names = {command["name"] for command in document["commands"]}
    assert {"setup", "join", "pair", "upload", "mkdir", "vault recovery rotate", "daemon install-service", "guide", "api"} <= names
    upload = next(command for command in document["commands"] if command["name"] == "upload")
    assert upload["output"] == "UploadSummary"
    flags = {arg["name"]: arg for arg in upload["args"]}
    assert flags["local"]["kind"] == "positional" and flags["local"]["repeatable"] is True
    assert flags["--exclude"]["repeatable"] is True
    assert document["exit_codes"]["6"].startswith("setup required")
    assert all(command["name"] != "_sidecar" for command in document["commands"])


@pytest.mark.parametrize("shell", SHELLS)
def test_completion_scripts_cover_the_catalog(shell: str) -> None:
    script = completion_script(shell)
    for word in ("upload", "mkdir", "recovery", "install-service", "json", "--to" if shell != "fish" else "-l to"):
        assert word in script


def test_guide_is_packaged(mock_cli: Callable[..., CliResult]) -> None:
    result = mock_cli(["guide"], lambda request: httpx.Response(500))
    assert result.code == 0
    for topic in ("bento status --json", "mkdir -p", "upload", "path_ambiguous", "id:", "Never purge", "exit `6`"):
        assert topic in result.stdout
    as_json = mock_cli(["guide", "--json"], lambda request: httpx.Response(500)).json
    assert as_json["format"] == "markdown" and as_json["guide"] == result.stdout


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    from bento.interfaces.cli.app import run

    assert run(["--version"]) == 0
    assert capsys.readouterr().out.startswith("bento ")


def test_sidecar_is_delegated_to_the_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    from bento.interfaces.cli import main as cli_main
    from bento.interfaces.desktop import launcher

    calls: list[list[str]] = []
    monkeypatch.setattr(launcher, "main", lambda argv: calls.append(list(argv)) or 0)
    assert cli_main.main(["_sidecar", "worker"]) == 0
    assert calls == [["worker"]]
