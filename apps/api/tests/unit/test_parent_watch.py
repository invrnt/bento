from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from bento.infrastructure import parent_watch


def test_parent_pid_comes_only_from_a_valid_foreign_pid() -> None:
    assert parent_watch.parent_pid_from({}) is None
    assert parent_watch.parent_pid_from({"BENTO_PARENT_PID": "abc"}) is None
    assert parent_watch.parent_pid_from({"BENTO_PARENT_PID": "1"}) is None
    assert parent_watch.parent_pid_from({"BENTO_PARENT_PID": str(os.getpid())}) is None
    assert parent_watch.parent_pid_from({"BENTO_PARENT_PID": " 4242 "}) == 4242


def test_watch_requests_graceful_stop_then_hard_exit_once_parent_is_gone() -> None:
    alive = iter([True, True, False])
    events: list[str] = []

    parent_watch.watch_parent(
        lambda: next(alive),
        on_parent_exit=lambda: events.append("graceful"),
        hard_exit=lambda: events.append("hard"),
        interval=0.5,
        grace=5.0,
        sleep=lambda seconds: events.append(f"sleep {seconds}"),
    )

    assert events == ["sleep 0.5", "sleep 0.5", "graceful", "sleep 5.0", "hard"]


def test_start_without_parent_pid_does_nothing() -> None:
    assert parent_watch.start_parent_watch({}) is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process semantics")
def test_probe_tracks_a_real_process() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        probe = parent_watch.open_parent_probe(child.pid)
        assert probe() is True
    finally:
        child.kill()
        child.wait()
    assert probe() is False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_sidecar_process_stops_when_its_host_dies() -> None:
    # host -> sidecar; killing the host must stop the sidecar on its own within the grace period.
    sidecar_code = (
        "import signal, sys, time\n"
        "from bento.infrastructure import parent_watch\n"
        "parent_watch.POLL_INTERVAL_SECONDS = 0.05\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        "parent_watch.start_parent_watch()\n"
        "print('ready', flush=True)\n"
        "time.sleep(30)\n"
    )
    host_code = (
        "import os, subprocess, sys\n"
        "env = dict(os.environ, BENTO_PARENT_PID=str(os.getpid()))\n"
        f"child = subprocess.Popen([sys.executable, '-c', {sidecar_code!r}], env=env, stdout=subprocess.PIPE, text=True)\n"
        "assert child.stdout.readline().strip() == 'ready'\n"
        "print(child.pid, flush=True)\n"
        "import time; time.sleep(30)\n"
    )
    host = subprocess.Popen([sys.executable, "-c", host_code], stdout=subprocess.PIPE, text=True)
    try:
        sidecar_pid = int(host.stdout.readline())  # type: ignore[union-attr]
        host.kill()
        host.wait()
        # Well under poll interval + grace: the graceful SIGTERM path, not the hard exit, stops it.
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and _alive(sidecar_pid):
            time.sleep(0.05)
        assert not _alive(sidecar_pid)
    finally:
        if host.poll() is None:
            host.kill()


def _alive(pid: int) -> bool:
    # The orphaned sidecar is reparented to init/subreaper, which reaps it; a zombie counts as gone.
    if not os.path.isdir("/proc"):
        return parent_watch._posix_alive(pid)
    try:
        with open(f"/proc/{pid}/stat") as stat:
            return stat.read().split(") ", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False
