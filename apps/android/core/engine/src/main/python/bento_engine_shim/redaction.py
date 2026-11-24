"""Python stdout/stderr and logging → redacted rotating log in `noBackupFilesDir/logs` (android-runtime.md §3).

Release builds never mirror to logcat. Kept by agent 35's engine if useful; otherwise deleted with the shim.
"""

from __future__ import annotations

import io
import logging
import logging.handlers
import re
import sys
from pathlib import Path

_secrets: list[str] = []
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_KEY_LIKE = re.compile(r"[A-Za-z0-9_-]{40,}")
_PHONE = re.compile(r"\+\d{7,15}")


def redact(text: str) -> str:
    for secret in _secrets:
        text = text.replace(secret, "<redacted>")
    text = _BEARER.sub(lambda m: m.group(1) + "<redacted>", text)
    text = _KEY_LIKE.sub("<redacted>", text)
    return _PHONE.sub("<phone>", text)


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


class _StreamToLog(io.TextIOBase):
    def __init__(self, logger: logging.Logger, level: int) -> None:
        self._logger = logger
        self._level = level
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._logger.log(self._level, line)
        return len(text)

    def flush(self) -> None:
        if self._buffer.strip():
            self._logger.log(self._level, self._buffer)
        self._buffer = ""


_installed: list[logging.Handler] = []


def reinstall() -> None:
    """Restore the redacted handlers after something (alembic's fileConfig) reset the root logger."""
    root = logging.getLogger()
    for handler in _installed:
        if handler not in root.handlers:
            root.addHandler(handler)
    if _installed:
        root.setLevel(logging.INFO)
    logging.getLogger("alembic").setLevel(logging.WARNING)


def install(log_dir: Path, *, mirror: bool, secrets: tuple[str, ...]) -> None:
    _secrets.extend(s for s in secrets if s and s not in _secrets)
    root = logging.getLogger()
    if any(getattr(h, "_bento", False) for h in root.handlers):
        return
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(log_dir / "engine.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler._bento = True  # type: ignore[attr-defined]
    handler.addFilter(_RedactingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    original_stderr = sys.stderr  # Chaquopy routes this to logcat
    root.handlers = [handler]
    if mirror and original_stderr is not None:
        console = logging.StreamHandler(original_stderr)
        console.addFilter(_RedactingFilter())
        console.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        root.addHandler(console)
    root.setLevel(logging.INFO)
    _installed[:] = list(root.handlers)
    sys.stdout = _StreamToLog(logging.getLogger("stdout"), logging.INFO)
    sys.stderr = _StreamToLog(logging.getLogger("stderr"), logging.WARNING)
