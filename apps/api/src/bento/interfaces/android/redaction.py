"""Redacted engine logs on Android (`architecture/android-runtime.md` §3, §10).

Python logging and stdout/stderr go to a rotating file in `noBackupFilesDir/logs`. Debug builds also mirror to the
original stderr (Chaquopy routes it to logcat); release builds never do. Every record passes through `redact`, which
removes the registered secrets (API token, wrapping key), bearer tokens, key-like strings, and phone numbers.
"""

from __future__ import annotations

import io
import logging
import logging.handlers
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

LOG_FILE = "engine.log"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 3
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_KEY_LIKE = re.compile(r"[A-Za-z0-9_-]{40,}")
_PHONE = re.compile(r"\+\d{7,15}")
_REDACTED = "<redacted>"


@dataclass
class _State:
    lock: threading.Lock = field(default_factory=threading.Lock)
    secrets: list[str] = field(default_factory=list)
    handlers: list[logging.Handler] = field(default_factory=list)
    previous_level: int | None = None
    stdout: TextIO | None = None
    stderr: TextIO | None = None


_state = _State()


def redact(text: str) -> str:
    for secret in _state.secrets:
        text = text.replace(secret, _REDACTED)
    text = _BEARER.sub(lambda match: match.group(1) + _REDACTED, text)
    text = _KEY_LIKE.sub(_REDACTED, text)
    return _PHONE.sub("<phone>", text)


class RedactingFilter(logging.Filter):
    """Formats the record once (message + traceback) and replaces it with its redacted text."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{logging.Formatter().formatException(record.exc_info)}"
            record.exc_info = None
            record.exc_text = None
        record.msg = redact(message)
        record.args = ()
        return True


class _StreamToLog(io.TextIOBase):
    """A text stream that forwards complete lines to a logger (stdout/stderr of prints and native libraries)."""

    def __init__(self, logger: logging.Logger, level: int) -> None:
        self._logger = logger
        self._level = level
        self._buffer = ""
        self._lock = threading.Lock()

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        with self._lock:
            self._buffer += text
            lines = self._buffer.split("\n")
            self._buffer = lines.pop()
        for line in lines:
            if line.strip():
                self._logger.log(self._level, line)
        return len(text)

    def flush(self) -> None:
        with self._lock:
            pending, self._buffer = self._buffer, ""
        if pending.strip():
            self._logger.log(self._level, pending)


def install(log_dir: Path, *, mirror: bool, secrets: tuple[str, ...] = ()) -> Path:
    """Route the root logger (and stdout/stderr) to a redacted rotating file; idempotent. Returns the log path."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / LOG_FILE
    with _state.lock:
        _state.secrets.extend(secret for secret in secrets if secret and secret not in _state.secrets)
        if _state.handlers:
            return path
        root = logging.getLogger()
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        file_handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
        )
        handlers: list[logging.Handler] = [file_handler]
        original_stderr = sys.stderr
        if mirror and original_stderr is not None:
            handlers.append(logging.StreamHandler(original_stderr))
        for handler in handlers:
            handler.addFilter(RedactingFilter())
            handler.setFormatter(formatter)
            handler.setLevel(logging.INFO)
            root.addHandler(handler)
        _state.handlers = handlers
        _state.previous_level = root.level
        root.setLevel(logging.INFO)
        logging.getLogger("alembic").setLevel(logging.WARNING)
        _state.stdout, _state.stderr = sys.stdout, sys.stderr
        sys.stdout = _StreamToLog(logging.getLogger("stdout"), logging.INFO)  # type: ignore[assignment]
        sys.stderr = _StreamToLog(logging.getLogger("stderr"), logging.WARNING)  # type: ignore[assignment]
    return path


def uninstall() -> None:
    """Restore stdout/stderr and the root logger (tests; a real process keeps the handlers until it dies)."""
    with _state.lock:
        root = logging.getLogger()
        for handler in _state.handlers:
            root.removeHandler(handler)
            handler.close()
        if _state.previous_level is not None:
            root.setLevel(_state.previous_level)
        if _state.stdout is not None:
            sys.stdout = _state.stdout
        if _state.stderr is not None:
            sys.stderr = _state.stderr
        _state.__init__()  # type: ignore[misc]
