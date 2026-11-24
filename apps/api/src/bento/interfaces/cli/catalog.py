"""Command metadata: the single source for argparse, `bento commands --json`, and shell completion."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bento.interfaces.cli.context import Context

Handler = Callable[["Context"], int | None]


@dataclass(frozen=True, slots=True)
class Arg:
    flags: tuple[str, ...]
    help_en: str
    help_es: str
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def positional(self) -> bool:
        return not self.flags[0].startswith("-")

    @property
    def takes_value(self) -> bool:
        return self.options.get("action") not in {"store_true", "store_false", "count", "help", "version"}

    def describe(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.flags[0] if self.positional else self.flags[-1],
            "kind": "positional" if self.positional else "flag",
            "flags": list(self.flags) if not self.positional else [],
            "takes_value": self.takes_value,
            "description": self.help_en,
        }
        nargs = self.options.get("nargs")
        if nargs is not None:
            data["nargs"] = nargs
        if "choices" in self.options:
            data["choices"] = list(self.options["choices"])
        if self.options.get("required") or (self.positional and nargs not in {"?", "*"}):
            data["required"] = True
        if self.options.get("action") == "append" or nargs in {"*", "+"}:
            data["repeatable"] = True
        return data


@dataclass(frozen=True, slots=True)
class Command:
    path: tuple[str, ...]
    summary_en: str
    summary_es: str
    handler: Handler | None = None
    args: tuple[Arg, ...] = ()
    output: str = "Object"
    hidden: bool = False
    # A group run without a subcommand behaves like this child (e.g. `bento devices` = `bento devices ls`).
    default_child: str | None = None

    @property
    def name(self) -> str:
        return " ".join(self.path)

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": list(self.path),
            "description": self.summary_en,
            "args": [arg.describe() for arg in self.args],
            "output": self.output,
            "runnable": self.handler is not None,
            **({"default_subcommand": self.default_child} if self.default_child else {}),
        }


def arg(*flags: str, en: str, es: str, **options: Any) -> Arg:
    return Arg(flags=tuple(flags), help_en=en, help_es=es, options=options)


GLOBAL_ARGS: tuple[Arg, ...] = (
    arg("--json", en="Print exactly one JSON document on stdout", es="Imprime un único documento JSON en stdout", action="store_true"),
    arg("--profile", en="CLI profile (default: default)", es="Perfil de la CLI (por defecto: default)", metavar="NAME"),
    arg(
        "--target",
        en="Which Bento to use",
        es="Qué Bento usar",
        choices=("auto", "desktop", "daemon"),
    ),
    arg("--api-url", en="Use this API URL as-is (with BENTO_API_TOKEN)", es="Usa esta URL de API tal cual (con BENTO_API_TOKEN)", metavar="URL"),
    arg("--no-start", en="Never start the daemon automatically", es="No iniciar el daemon automáticamente", action="store_true"),
    arg("-y", "--yes", en="Confirm irreversible actions", es="Confirma acciones irreversibles", action="store_true"),
    arg("-q", "--quiet", en="Less human output", es="Menos salida para humanos", action="store_true"),
    arg("--timeout", en="Seconds to wait for the API / long operations", es="Segundos de espera para la API / operaciones largas", type=float, metavar="SECONDS"),
    arg("--lang", en="Output language", es="Idioma de la salida", choices=("es", "en")),
)


def all_commands() -> tuple[Command, ...]:
    from bento.interfaces.cli.commands import registry

    return registry()


def find(path: tuple[str, ...]) -> Command | None:
    for command in all_commands():
        if command.path == path:
            return command
    return None


def catalog_document(version: str) -> dict[str, Any]:
    return {
        "name": "bento",
        "version": version,
        "global_flags": [item.describe() for item in GLOBAL_ARGS],
        "exit_codes": {
            "0": "success",
            "1": "unexpected error",
            "2": "usage error / confirmation needed",
            "3": "not found",
            "4": "conflict (path_ambiguous, *_conflict)",
            "5": "Bento not reachable",
            "6": "setup required (error.details.next names the command)",
            "7": "partial failure (per-item results in the JSON)",
            "8": "waiting on Telegram (details.retry_after_seconds)",
            "130": "interrupted",
        },
        "commands": [command.describe() for command in all_commands() if not command.hidden],
    }
