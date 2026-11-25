"""Host side of the multi-device trust journeys (agent 38).

Runs, on the development machine, everything the emulator's Bento shares a cloud with:

- the remote fake Telegram cloud (`bento-sidecar fake-telegram-serve`, api/android-endpoints.md §9),
- the backend's pairing relay double (`tests/integration/pairing/relay_double.py`, mirrors `apps/relay`),
- two headless "desktop" devices (API + worker each) pointed at that cloud and relay.

Everything binds 127.0.0.1 on the ports given (`--fake-port`, `--relay-port`, `--desktop-port`, `--desktop2-port`);
`run_journeys.sh` picks free ones and maps the phone's fixed loopback ports onto them with `adb reverse`. Usage:
`uv run --project apps/api python trust_host.py --root <dir> [--…-port N]`; prints `TRUST_HOST_READY {json}` when all
services answer, then runs until interrupted. Each sidecar's process group is listed in `<root>/pgids` so the runner
can still stop them if this process dies; on any exit this process stops them itself.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[4] / "api"
sys.path.insert(0, str(API_ROOT / "tests" / "integration" / "pairing"))

from relay_double import RelayDouble  # noqa: E402



class FixedPortRelay(RelayDouble):
    def __init__(self, port: int) -> None:
        super().__init__()
        self.port = port

    async def start(self) -> str:
        from websockets.asyncio.server import serve

        self._server = await serve(self._handle, "127.0.0.1", self.port, process_request=self._process_request, compression=None, max_size=None)
        self.url = f"ws://127.0.0.1:{self.port}"
        return self.url


def run_relay(port: int) -> None:
    loop = asyncio.new_event_loop()
    relay = FixedPortRelay(port)
    loop.run_until_complete(relay.start())
    loop.run_forever()


def sidecar(*args: str, env: dict[str, str], log: Path, pgids: Path) -> subprocess.Popen[bytes]:
    process = subprocess.Popen(
        ["uv", "run", "--quiet", "--project", str(API_ROOT), "bento-sidecar", *args],
        env=env,
        stdout=log.open("ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    with pgids.open("a") as file:
        file.write(f"{process.pid}\n")
    return process


def stop_all(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 10
    for process in processes:
        try:
            process.wait(max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def wait_for(url: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except Exception:  # noqa: BLE001 - not up yet
            time.sleep(0.5)
    raise SystemExit(f"{url} did not answer within {timeout}s")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--fake-port", type=int, default=8790)
    parser.add_argument("--relay-port", type=int, default=8788)
    parser.add_argument("--desktop-port", type=int, default=8791)
    parser.add_argument("--desktop2-port", type=int, default=8792)
    args = parser.parse_args()
    root: Path = args.root
    root.mkdir(parents=True, exist_ok=True)
    fake_port, relay_port = args.fake_port, args.relay_port
    host_ports = {"desktop": args.desktop_port, "desktop2": args.desktop2_port}
    pgids = root / "pgids"
    pgids.write_text("")
    processes: list[subprocess.Popen[bytes]] = []

    def on_signal(*_: object) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGHUP, on_signal)
    try:
        base = {k: v for k, v in os.environ.items() if not k.startswith("BENTO_")}
        processes.append(
            sidecar("fake-telegram-serve", "--dir", str(root / "cloud"), "--port", str(fake_port), env=base, log=root / "fake.log", pgids=pgids)
        )
        threading.Thread(target=run_relay, args=(relay_port,), daemon=True).start()

        for name, port in host_ports.items():
            data = root / name
            data.mkdir(exist_ok=True)
            env = {
                **base,
                "BENTO_RUNTIME_MODE": "headless",
                "ENVIRONMENT": "development",
                "DATA_DIR": str(data),
                "STORAGE_BACKEND": "fake",
                "BENTO_FAKE_TELEGRAM_URL": f"http://127.0.0.1:{fake_port}",
                "BENTO_FAKE_TELEGRAM_MANUAL_LOGIN": "1",
                "BENTO_RELAY_URL": f"ws://127.0.0.1:{relay_port}",
                "BENTO_DEVICE_NAME": "Portátil de Ana" if name == "desktop" else "Mac de Ana",
                "EMBEDDINGS_PROVIDER": "disabled",
                "OCR_PROVIDER": "disabled",
            }
            processes.append(sidecar("migrate", env=env, log=root / f"{name}.log", pgids=pgids))
            processes[-1].wait()
            processes.append(sidecar("api", "--port", str(port), env=env, log=root / f"{name}.log", pgids=pgids))
            processes.append(sidecar("worker", env=env, log=root / f"{name}.log", pgids=pgids))

        for port in host_ports.values():
            wait_for(f"http://127.0.0.1:{port}/api/health")
        print("TRUST_HOST_READY " + json.dumps({"fake": fake_port, "relay": relay_port, "hosts": host_ports}), flush=True)
        while all(process.poll() is None for process in processes if process.args[-1] != "migrate"):
            time.sleep(1)
        raise SystemExit("a sidecar exited; see the host logs")
    finally:
        stop_all(processes)


if __name__ == "__main__":
    raise SystemExit(main())
