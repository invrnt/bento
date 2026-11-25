"""Running build steps: one log file per step, short status lines on the terminal, toolchain lookup."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Environment variables whose values are secrets. They are passed to the children that need them but
# never written to logs, reports or the terminal.
SECRET_ENV = (
    "BENTO_TELEGRAM_API_HASH",
    "BENTO_UPDATE_SIGNING_KEY",
    "BENTO_ANDROID_KEYSTORE_PASSWORD",
    "BENTO_ANDROID_KEY_PASSWORD",
    "APPLE_APP_SPECIFIC_PASSWORD",
    "APPLE_CERTIFICATE_PASSWORD",
    "WINDOWS_CERTIFICATE_PASSWORD",
    "GH_TOKEN",
    "GITHUB_TOKEN",
)


class StepError(Exception):
    def __init__(self, step: str, message: str, log: Path | None = None) -> None:
        super().__init__(message)
        self.step = step
        self.log = log


def say(message: str) -> None:
    print(f"[bento-release] {message}", file=sys.stderr, flush=True)


def redact(text: str, env: dict[str, str] | None = None) -> str:
    values = [(env or os.environ).get(name, "") for name in SECRET_ENV]
    for value in sorted((v for v in values if len(v) >= 6), key=len, reverse=True):
        text = text.replace(value, "[redacted]")
    return text


class Runner:
    def __init__(self, root: Path, log_dir: Path, env: dict[str, str]) -> None:
        self.root = root
        self.log_dir = log_dir
        self.env = env
        log_dir.mkdir(parents=True, exist_ok=True)

    def run(self, step: str, command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: int = 7200) -> Path:
        """Runs `command`; output goes to logs/<step>.log (secret values redacted). Raises StepError on failure."""
        log = self.log_dir / f"{step}.log"
        merged = {**self.env, **(env or {})}
        executable = shutil.which(command[0], path=merged.get("PATH")) or command[0]
        say(f"{step}: {' '.join(Path(command[0]).name if i == 0 else part for i, part in enumerate(command))}")
        started = time.monotonic()
        with log.open("w", encoding="utf-8") as handle:
            handle.write(f"# {step}\n# cwd: {cwd or self.root}\n# cmd: {' '.join(command)}\n\n")
            handle.flush()
            try:
                # Streamed so a long step can be followed with `tail -f`; secret values are redacted below.
                process = subprocess.run([executable, *command[1:]], cwd=cwd or self.root, env=merged, stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
            except subprocess.TimeoutExpired:
                raise StepError(step, f"timed out after {timeout}s", log) from None
            except FileNotFoundError:
                raise StepError(step, f"{command[0]} not found", log) from None
        text = log.read_text(encoding="utf-8", errors="replace")
        redacted = redact(text, merged)
        if redacted != text:
            log.write_text(redacted, encoding="utf-8")
        elapsed = time.monotonic() - started
        if process.returncode != 0:
            tail = "".join(log.read_text(encoding="utf-8").splitlines(keepends=True)[-15:])
            say(f"{step}: FAILED after {elapsed:.0f}s (exit {process.returncode}); log {log}\n{tail}")
            raise StepError(step, f"exit {process.returncode}", log)
        say(f"{step}: ok ({elapsed:.0f}s)")
        return log


def node_version(node: str) -> tuple[int, ...] | None:
    try:
        out = subprocess.run([node, "--version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        return tuple(int(part) for part in out.strip().lstrip("v").split("."))
    except ValueError:
        return None


def find_node_dir() -> str | None:
    """A Node.js 22-25 bin directory (desktop packaging refuses 26); BENTO_RELEASE_NODE_DIR wins."""
    candidates = [os.environ.get("BENTO_RELEASE_NODE_DIR", "")]
    home = Path.home()
    candidates += [str(home / ".local/share/mise/installs/node/24/bin")]
    which = shutil.which("node")
    if which:
        candidates.append(str(Path(which).parent))
    for directory in candidates:
        if not directory:
            continue
        for name in ("node", "node.exe"):
            node = Path(directory) / name
            version = node_version(str(node)) if node.is_file() else None
            if version and 22 <= version[0] < 26:
                return directory
    return None


def tool_version(command: list[str]) -> str:
    try:
        out = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    return (out.strip().splitlines() or ["unavailable"])[0]
