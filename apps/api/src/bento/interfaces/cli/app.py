"""Global flags, parser construction from the catalog, dispatch, and exit codes."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn, TextIO

import httpx

from bento.interfaces.cli import cli_version
from bento.interfaces.cli.catalog import GLOBAL_ARGS, Arg, all_commands
from bento.interfaces.cli.context import Context
from bento.interfaces.cli.errors import EXIT_INTERRUPTED, EXIT_UNEXPECTED, EXIT_USAGE, CliError
from bento.interfaces.cli.i18n import Translator, detect_lang
from bento.interfaces.cli.output import Output
from bento.interfaces.cli.profiles import PROFILE_NAME, Endpoint, Profile, cli_home


class Parser(argparse.ArgumentParser):
    """Raises instead of exiting so usage errors use the JSON error document and exit code 2."""

    def error(self, message: str) -> NoReturn:
        raise CliError("usage_error", message, {"usage": self.format_usage().strip()}, EXIT_USAGE)


def _add(parser: argparse.ArgumentParser, item: Arg, lang: str, *, suppress: bool = False) -> None:
    options = dict(item.options)
    options["help"] = item.help_es if lang == "es" else item.help_en
    if suppress:
        options["default"] = argparse.SUPPRESS
    parser.add_argument(*item.flags, **options)


def build_parser(lang: str) -> Parser:
    translator = Translator(lang)
    root = Parser(
        prog="bento",
        description=translator("app.description"),
        epilog=translator("app.epilog"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    for item in GLOBAL_ARGS:
        _add(root, item, lang)
    root.add_argument("--version", action="version", version=f"bento {cli_version()}")
    root.set_defaults(_handler=None, _command=(), _parser=root)

    shared = argparse.ArgumentParser(add_help=False)
    for item in GLOBAL_ARGS:
        _add(shared, item, lang, suppress=True)

    commands = sorted(all_commands(), key=lambda command: len(command.path))
    parsers: dict[tuple[str, ...], argparse.ArgumentParser] = {(): root}
    subparsers: dict[tuple[str, ...], Any] = {}
    by_path = {command.path: command for command in commands}
    for command in commands:
        parent_path = command.path[:-1]
        parent = parsers[parent_path]
        if parent_path not in subparsers:
            subparsers[parent_path] = parent.add_subparsers(
                dest=f"_sub_{len(parent_path)}", metavar=translator("app.command_metavar"), parser_class=Parser
            )
        summary = command.summary_es if lang == "es" else command.summary_en
        kwargs: dict[str, Any] = {"description": summary, "parents": [shared]}
        if not command.hidden:
            kwargs["help"] = summary
        parser = subparsers[parent_path].add_parser(command.path[-1], **kwargs)
        for item in command.args:
            _add(parser, item, lang)
        parser.set_defaults(_handler=command.handler, _command=command.path, _parser=parser)
        parsers[command.path] = parser
    for command in commands:
        if command.default_child:
            child = by_path[(*command.path, command.default_child)]
            parser = parsers[command.path]
            own = {flag for item in command.args for flag in item.flags}
            for item in child.args:
                if not item.positional and not own.intersection(item.flags):
                    _add(parser, item, lang)
            parser.set_defaults(_handler=child.handler, _command=child.path)
    return root


def _prescan(argv: Sequence[str], flag: str) -> str | None:
    for index, value in enumerate(argv):
        if value == flag and index + 1 < len(argv):
            return argv[index + 1]
        if value.startswith(flag + "="):
            return value.split("=", 1)[1]
    return None


def _config_file(argv: Sequence[str], environ: Mapping[str, str]) -> Path | None:
    name = _prescan(argv, "--profile") or environ.get("BENTO_PROFILE", "").strip() or "default"
    if not PROFILE_NAME.match(name):
        return None
    return cli_home(environ) / "profiles" / name / "config.json"


def _json_requested(argv: Sequence[str], environ: Mapping[str, str]) -> bool:
    return "--json" in argv or environ.get("BENTO_JSON", "").strip().lower() in {"1", "true", "yes"}


def run(
    argv: Sequence[str],
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    stdin: TextIO | None = None,
    environ: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
    start_daemon: Callable[[Profile, float], Endpoint] | None = None,
) -> int:
    env: Mapping[str, str] = os.environ if environ is None else environ
    _utf8_streams()
    lang = detect_lang(_prescan(argv, "--lang"), env, _config_file(argv, env))
    translator = Translator(lang)
    out = Output(
        json_mode=_json_requested(argv, env),
        quiet="-q" in argv or "--quiet" in argv,
        translator=translator,
        stdout=stdout,
        stderr=stderr,
        stdin=stdin,
    )
    ctx: Context | None = None
    try:
        parser = build_parser(lang)
        if not argv:
            out.stdout.write(parser.format_help())
            return 0
        try:
            args = parser.parse_args(list(argv))
        except SystemExit as exit_request:  # --help / --version
            return int(exit_request.code or 0)
        out.json_mode = bool(getattr(args, "json", False)) or out.json_mode
        out.quiet = bool(getattr(args, "quiet", False))
        ctx = Context(args, out, environ=env, transport=transport, start_daemon=start_daemon)
        handler = args._handler
        if handler is None:
            sub_parser: argparse.ArgumentParser = args._parser
            if not out.json_mode:
                out.stderr.write(sub_parser.format_help())
            raise CliError(
                "usage_error",
                translator("app.subcommand_required"),
                {"command": " ".join(args._command)},
                EXIT_USAGE,
            )
        result = handler(ctx)
        return int(result or 0)
    except CliError as error:
        out.error(error)
        return error.exit_code
    except KeyboardInterrupt:
        out.error(CliError("interrupted", translator("app.interrupted"), {}, EXIT_INTERRUPTED))
        return EXIT_INTERRUPTED
    except BrokenPipeError:
        _silence_broken_pipe()
        return 0
    except Exception as exc:  # noqa: BLE001 - last-resort mapping to the error document
        out.error(CliError("unexpected_error", f"{type(exc).__name__}: {exc}", {}, EXIT_UNEXPECTED))
        if env.get("BENTO_DEBUG"):
            raise
        return EXIT_UNEXPECTED
    finally:
        if ctx is not None:
            ctx.close()


def _utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        encoding = (getattr(stream, "encoding", "") or "").lower()
        if reconfigure is not None and encoding not in {"utf-8", "utf8"}:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _silence_broken_pipe() -> None:
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    except (OSError, ValueError):
        pass

