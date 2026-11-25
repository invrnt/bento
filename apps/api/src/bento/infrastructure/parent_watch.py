"""Stop a sidecar once the desktop host that launched it is gone.

Electron passes its own PID in `BENTO_PARENT_PID`. Watching that PID (not `getppid()`) also works when
a wrapper such as `uv run` sits between the host and this process. When the host disappears, the
sidecar asks itself to stop through its normal signal path and, if that does not finish within the
grace period, exits hard so no orphan keeps the data directory open.
"""

from __future__ import annotations

import ctypes
import os
import select
import signal
import sys
import threading
import time
from collections.abc import Callable, Mapping
from typing import NoReturn

PARENT_PID_ENV = "BENTO_PARENT_PID"
POLL_INTERVAL_SECONDS = 1.0
GRACE_SECONDS = 5.0

_WINDOWS_SYNCHRONIZE = 0x00100000
_WINDOWS_WAIT_OBJECT_0 = 0x00000000
_WINDOWS_ERROR_INVALID_PARAMETER = 87

ParentProbe = Callable[[], bool]
"""Returns True while the parent process is alive."""


def parent_pid_from(environ: Mapping[str, str]) -> int | None:
    raw = environ.get(PARENT_PID_ENV, "").strip()
    if not raw.isdigit():
        return None
    pid = int(raw)
    return pid if pid > 1 and pid != os.getpid() else None


def open_parent_probe(pid: int) -> ParentProbe:
    """Bind to the parent now, so a later PID reuse cannot pass for the original parent where the
    platform allows it (pidfd on Linux, a process handle on Windows)."""
    if sys.platform == "win32":
        return _windows_probe(pid)
    pidfd_open = getattr(os, "pidfd_open", None)
    if pidfd_open is not None:
        try:
            descriptor = pidfd_open(pid)
        except ProcessLookupError:
            return lambda: False
        except OSError:
            pass
        else:
            return lambda: not select.select([descriptor], [], [], 0)[0]
    return lambda: _posix_alive(pid)


def stop_after_parent_exit() -> None:
    detach_stdio()
    request_graceful_stop()


def detach_stdio() -> None:
    """The host read our stdout/stderr pipes; with it gone, writes to them fail during shutdown and
    stall it, so send both to the null device."""
    try:
        null = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        return
    try:
        for stream in (sys.stdout, sys.stderr):
            if stream is None:
                continue
            try:
                os.dup2(null, stream.fileno())
            except (OSError, ValueError):
                continue
    finally:
        os.close(null)


def request_graceful_stop() -> None:
    # API (uvicorn) and worker both stop cleanly on SIGTERM on POSIX; Windows only delivers SIGINT.
    if sys.platform == "win32":
        signal.raise_signal(signal.SIGINT)
        return
    # Target the main thread: a signal raised here would land on this watcher thread and leave a
    # main thread blocked in a sleep or a system call unaware of it.
    main_thread_id = threading.main_thread().ident
    if main_thread_id is None:
        os.kill(os.getpid(), signal.SIGTERM)
        return
    signal.pthread_kill(main_thread_id, signal.SIGTERM)


def _hard_exit() -> NoReturn:
    os._exit(1)


def watch_parent(
    probe: ParentProbe,
    *,
    on_parent_exit: Callable[[], None] = stop_after_parent_exit,
    hard_exit: Callable[[], object] = _hard_exit,
    interval: float = POLL_INTERVAL_SECONDS,
    grace: float = GRACE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Blocks until the parent is gone, then stops this process."""
    while probe():
        sleep(interval)
    on_parent_exit()
    sleep(grace)
    hard_exit()


def start_parent_watch(environ: Mapping[str, str] = os.environ) -> threading.Thread | None:
    pid = parent_pid_from(environ)
    if pid is None:
        return None
    probe = open_parent_probe(pid)
    thread = threading.Thread(target=watch_parent, args=(probe,), name="bento-parent-watch", daemon=True)
    thread.start()
    return thread


def _posix_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_probe(pid: int) -> ParentProbe:
    # os.kill(pid, 0) would terminate the process on Windows, so use a waitable handle instead.
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(_WINDOWS_SYNCHRONIZE, False, pid)
    if not handle:
        # No such process means the host is already gone; any other failure disables the watch.
        gone = ctypes.get_last_error() == _WINDOWS_ERROR_INVALID_PARAMETER  # type: ignore[attr-defined]
        return lambda: not gone
    return lambda: kernel32.WaitForSingleObject(handle, 0) != _WINDOWS_WAIT_OBJECT_0
