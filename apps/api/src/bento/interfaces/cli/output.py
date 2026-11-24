"""Rendering: one JSON document on stdout (`--json`) or concise human output; progress and prompts on stderr."""

from __future__ import annotations

import json
import os
import sys
import time
import unicodedata
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, TextIO

from bento.interfaces.cli.errors import CliError
from bento.interfaces.cli.i18n import Translator


def is_tty(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def display_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char) or char in "‍️":
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def human_size(value: int | None, lang: str = "es") -> str:
    if value is None:
        return "-"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            text = f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            return text.replace(".", ",") if lang == "es" else text
        size /= 1024
    return str(value)


def human_date(value: str | None) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.strftime("%Y-%m-%d %H:%M")


class Output:
    def __init__(
        self,
        *,
        json_mode: bool,
        quiet: bool,
        translator: Translator,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        stdin: TextIO | None = None,
    ) -> None:
        self.json_mode = json_mode
        self.quiet = quiet
        self.t = translator
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr
        self.stdin = stdin or sys.stdin
        self.emitted = False

    @property
    def lang(self) -> str:
        return self.t.lang

    @property
    def interactive(self) -> bool:
        """Prompts are allowed only when both stdin and stderr are terminals."""
        return is_tty(self.stdin) and is_tty(self.stderr)

    @property
    def stderr_tty(self) -> bool:
        return is_tty(self.stderr)

    # Results ----------------------------------------------------------------------------------

    def result(self, data: Any, human: Callable[[Output, Any], None] | None = None) -> None:
        self.emitted = True
        if self.json_mode:
            self.json(data)
        elif human is not None:
            human(self, data)
        else:
            self.json(data)

    def json(self, data: Any, *, stream: TextIO | None = None, compact: bool | None = None) -> None:
        target = stream or self.stdout
        use_compact = (not is_tty(target)) if compact is None else compact
        text = json.dumps(data, ensure_ascii=False, indent=None if use_compact else 2, default=str)
        target.write(text + "\n")
        target.flush()

    def line(self, text: str = "") -> None:
        """Human result text (stdout)."""
        self.stdout.write(text + "\n")
        self.stdout.flush()

    def event(self, name: str, data: dict[str, Any]) -> None:
        """Progress event for long-running commands: one compact NDJSON line on stderr in JSON mode
        (stdout still carries exactly one final document); nothing in human mode."""
        if not self.json_mode:
            return
        self.stderr.write(json.dumps({"event": name, **data}, ensure_ascii=False, default=str) + "\n")
        self.stderr.flush()

    def note(self, text: str) -> None:
        """Human hints and status (stderr); silent with --json or --quiet."""
        if self.json_mode or self.quiet:
            return
        self.stderr.write(text + "\n")
        self.stderr.flush()

    def table(self, headers: Sequence[str], rows: Sequence[Sequence[Any]], *, empty: str | None = None) -> None:
        if not rows:
            if empty:
                self.line(empty)
            return
        cells = [[("" if cell is None else str(cell)) for cell in row] for row in rows]
        widths = [display_width(header) for header in headers]
        for row in cells:
            for index, cell in enumerate(row):
                widths[index] = max(widths[index], display_width(cell))
        self.line("  ".join(pad(header, widths[i]) for i, header in enumerate(headers)).rstrip())
        for row in cells:
            self.line("  ".join(pad(cell, widths[i]) for i, cell in enumerate(row)).rstrip())

    def fields(self, pairs: Sequence[tuple[str, Any]]) -> None:
        width = max((display_width(label) for label, _ in pairs), default=0)
        for label, value in pairs:
            self.line(f"{pad(label + ':', width + 1)} {'-' if value is None or value == '' else value}")

    def error(self, error: CliError) -> None:
        if self.json_mode:
            self.json(error.to_json(), stream=self.stderr, compact=True)
            return
        message = self.t.error_message(error.code, error.message, error.details)
        self.stderr.write(f"{self.t('error.prefix')}: {message}\n")
        candidates = error.details.get("candidates")
        if isinstance(candidates, list) and candidates:
            self.stderr.write(self.t("error.candidates") + "\n")
            for candidate in candidates:
                if isinstance(candidate, dict):
                    self.stderr.write(
                        f"  id:{candidate.get('id')}  {candidate.get('kind', '')}  {candidate.get('path', '')}"
                        f"  {human_date(candidate.get('created_at'))}\n"
                    )
        next_step = error.details.get("next")
        if isinstance(next_step, str):
            self.stderr.write(self.t("error.next", command=next_step) + "\n")
        self.stderr.flush()

    # Prompts ----------------------------------------------------------------------------------

    def prompt(self, question: str, *, secret: bool = False) -> str:
        if secret:
            import getpass

            return getpass.getpass(question + " ", stream=self.stderr)
        self.stderr.write(question + " ")
        self.stderr.flush()
        answer = self.stdin.readline()
        if not answer:
            raise EOFError
        return answer.strip()

    def confirm(self, question: str, *, default: bool = False) -> bool:
        suffix = self.t("prompt.yes_no_default_yes") if default else self.t("prompt.yes_no")
        answer = self.prompt(f"{question} {suffix}").strip().lower()
        if not answer:
            return default
        return answer in {"s", "si", "sí", "y", "yes"}

    def progress(self, total: int, label: str) -> Progress:
        enabled = self.stderr_tty and not self.json_mode and not self.quiet
        return Progress(self.stderr, total, label, enabled=enabled, lang=self.lang)


class Progress:
    """A single-line progress bar on stderr (TTY only)."""

    def __init__(self, stream: TextIO, total: int, label: str, *, enabled: bool, lang: str) -> None:
        self._stream = stream
        self.total = max(total, 0)
        self.done = 0
        self._label = label
        self._enabled = enabled
        self._lang = lang
        self._last = 0.0

    def advance(self, amount: int = 1) -> None:
        self.done += amount
        self.render()

    def render(self, *, force: bool = False) -> None:
        if not self._enabled:
            return
        now = time.monotonic()
        if not force and now - self._last < 0.1 and self.done < self.total:
            return
        self._last = now
        columns = _columns()
        ratio = 1.0 if self.total == 0 else min(1.0, self.done / self.total)
        bar_width = max(10, min(30, columns - 40))
        filled = int(bar_width * ratio)
        bar = "█" * filled + "░" * (bar_width - filled)
        text = f"\r{self._label} {bar} {int(ratio * 100):3d}%"
        if self.total and self.total > 0:
            text += f"  {human_size(self.done, self._lang)}/{human_size(self.total, self._lang)}"
        self._stream.write(text[: columns - 1].ljust(min(columns - 1, len(text))))
        self._stream.flush()

    def close(self) -> None:
        if self._enabled:
            self.render(force=True)
            self._stream.write("\n")
            self._stream.flush()


def _columns() -> int:
    try:
        return os.get_terminal_size(sys.stderr.fileno()).columns
    except (OSError, ValueError, AttributeError):
        return 80
