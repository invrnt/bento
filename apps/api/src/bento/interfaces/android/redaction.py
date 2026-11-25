"""Redacted engine logs on Android (`architecture/android-runtime.md` §3, §10).

Python logging and stdout/stderr go to a rotating file in `noBackupFilesDir/logs`. Debug builds also mirror to the
original stderr (Chaquopy routes it to logcat); release builds never do. Every record passes through `redact`, which
removes the registered secrets (API tokens, server keys, wrapping key, and whatever a service `register`s while it is
live), bearer tokens, key-like strings, pairing codes and join-link codes, phone numbers, login codes and passwords.

`install_early` (called first thing in `warm_up`, before the log directory is known) buffers redacted records in
memory so nothing reaches `logging.lastResort` (stderr, i.e. logcat); `install` flushes them into the file.
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
_PHONE = re.compile(r"\+\s?\d(?:[\d\s().-]{5,18})\d")
# `phone=573001234567`, `"phone": "300 123 4567"`, `phone_number: +57 300...` (no leading + needed in context).
_PHONE_CONTEXT = re.compile(
    r"(?i)(\b(?:phone|phone_number|phonenumber|tel|msisdn)\b[\"']?\s*[=:]\s*[\"']?)\+?\d[\d\s().-]{5,18}\d"
)
# Join links (`bento://join?v=1&c=...`, `https://host/join#c=...`).
_JOIN_CODE = re.compile(r"(?i)([?#&;]c=)[^&#\s\"']+")
# Pairing codes: 3 groups of 4 Crockford characters, `-` or no separator (any case), or space-separated uppercase.
_PAIRING_CODE = re.compile(
    r"(?i:\b[0-9a-z]{4}-?[0-9a-z]{4}-?[0-9a-z]{4}\b)|\b[0-9A-Z]{4} [0-9A-Z]{4} [0-9A-Z]{4}\b"
)
# 2FA passwords named in context: `password=hunter2`, `"passwd": "..."`.
_PASSWORD_CONTEXT = re.compile(
    r"(?i)(\b(?:password|passwd|pwd|passphrase|2fa|two_factor|srp)\b[\"']?\s*[=:]\s*[\"']?)[^\s\"',;&]+"
)
# Login and pairing codes named in context (`code=12345`, `pairing_code: 7KQ2...`); error codes such as
# `code=relay_closed` carry no digit and stay readable.
_CODE_CONTEXT = re.compile(
    r"(?i)(\b(?:code|login_code|phone_code|pairing_code)\b[\"']?\s*[=:]\s*[\"']?)[^\s\"',;&]*\d[^\s\"',;&]*"
)
# Telegram login codes in prose: "login code 12345", "code is 12345".
_CODE_PROSE = re.compile(r"(?i)(\bcode\b\D{0,12}?)\b\d{5,6}\b")
_REDACTED = "<redacted>"


@dataclass
class _State:
    lock: threading.RLock = field(default_factory=threading.RLock)
    secrets: list[str] = field(default_factory=list)
    handlers: list[logging.Handler] = field(default_factory=list)
    early: logging.handlers.MemoryHandler | None = None
    previous_level: int | None = None
    stdout: TextIO | None = None
    stderr: TextIO | None = None


_state = _State()


def redact(text: str) -> str:
    with _state.lock:
        secrets = sorted(_state.secrets, key=len, reverse=True)
    for secret in secrets:
        text = text.replace(secret, _REDACTED)
    text = _BEARER.sub(lambda match: match.group(1) + _REDACTED, text)
    text = _KEY_LIKE.sub(_REDACTED, text)
    text = _JOIN_CODE.sub(lambda match: match.group(1) + _REDACTED, text)
    text = _PASSWORD_CONTEXT.sub(lambda match: match.group(1) + _REDACTED, text)
    text = _CODE_CONTEXT.sub(lambda match: match.group(1) + _REDACTED, text)
    text = _CODE_PROSE.sub(lambda match: match.group(1) + _REDACTED, text)
    text = _PHONE_CONTEXT.sub(lambda match: match.group(1) + "<phone>", text)
    text = _PHONE.sub("<phone>", text)
    return _PAIRING_CODE.sub(_pairing_code, text)


def _pairing_code(match: re.Match[str]) -> str:
    value = match.group(0)
    # A random 12-character code virtually always mixes digits and letters; plain words and numbers are kept.
    if any(char.isdigit() for char in value) and any(char.isalpha() for char in value):
        return _REDACTED
    return value


def register(*secrets: str) -> None:
    """Redact `secrets` from every later record (a live pairing code, login code, 2FA password, API token)."""
    with _state.lock:
        _state.secrets.extend(secret for secret in secrets if secret and secret not in _state.secrets)


def unregister(*secrets: str) -> None:
    """Stop tracking `secrets` once they are dead (rotated tokens, finished pairing sessions)."""
    with _state.lock:
        _state.secrets[:] = [secret for secret in _state.secrets if secret not in secrets]


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


EARLY_CAPACITY = 500


def install_early() -> None:
    """Before `install`: buffer redacted records in memory so none reaches `logging.lastResort` (logcat)."""
    with _state.lock:
        if _state.handlers or _state.early is not None:
            return
        early = logging.handlers.MemoryHandler(EARLY_CAPACITY, flushLevel=logging.CRITICAL + 1, target=None)
        early.addFilter(RedactingFilter())
        early.setLevel(logging.INFO)
        logging.getLogger().addHandler(early)
        _state.early = early


def install(log_dir: Path, *, mirror: bool, secrets: tuple[str, ...] = ()) -> Path:
    """Route the root logger (and stdout/stderr) to a redacted rotating file; idempotent. Returns the log path."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / LOG_FILE
    register(*secrets)
    with _state.lock:
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
        early, _state.early = _state.early, None
        if early is not None:
            root.removeHandler(early)
            for record in early.buffer:
                for handler in handlers:
                    if record.levelno >= handler.level:
                        handler.handle(record)
            early.buffer.clear()
            early.close()
        _state.previous_level = root.level
        root.setLevel(logging.INFO)
        logging.getLogger("alembic").setLevel(logging.WARNING)
        _state.stdout, _state.stderr = sys.stdout, sys.stderr
        sys.stdout = _StreamToLog(_stream_logger("stdout"), logging.INFO)  # type: ignore[assignment]
        sys.stderr = _StreamToLog(_stream_logger("stderr"), logging.WARNING)  # type: ignore[assignment]
    return path


def _stream_logger(name: str) -> logging.Logger:
    """A logger for captured output that a `logging.config` call (`disable_existing_loggers`) cannot silence."""
    logger = logging.getLogger(name)
    logger.disabled = False
    logger.propagate = True
    logger.setLevel(logging.NOTSET)
    return logger


def uninstall() -> None:
    """Restore stdout/stderr and the root logger (tests; a real process keeps the handlers until it dies)."""
    with _state.lock:
        root = logging.getLogger()
        for handler in [*_state.handlers, *([_state.early] if _state.early is not None else [])]:
            root.removeHandler(handler)
            handler.close()
        if _state.previous_level is not None:
            root.setLevel(_state.previous_level)
        if _state.stdout is not None:
            sys.stdout = _state.stdout
        if _state.stderr is not None:
            sys.stderr = _state.stderr
        _state.__init__()  # type: ignore[misc]
