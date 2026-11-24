"""Host side of the multi-device trust journeys (agent 38).

Runs, on the development machine, everything the emulator's Bento shares a cloud with:

- the remote fake Telegram cloud (`bento-sidecar fake-telegram-serve`, api/android-endpoints.md §9),
- the backend's pairing relay double (`tests/integration/pairing/relay_double.py`, mirrors `apps/relay`),
- two headless "desktop" devices (API + worker each) pointed at that cloud and relay.

Everything binds 127.0.0.1; `run_journeys.sh` exposes the ports to the emulator with `adb reverse`, so the phone
uses the same loopback URLs. Usage: `uv run --project apps/api python trust_host.py --root <dir>`; prints
`TRUST_HOST_READY {json}` when all services answer, then runs until interrupted.
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

FAKE_PORT = 8790
RELAY_PORT = 8788
HOST_PORTS = {"desktop": 8791, "desktop2": 8792}


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


def sidecar(*args: str, env: dict[str, str], log: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        ["uv", "run", "--quiet", "--project", str(API_ROOT), "bento-sidecar", *args],
        env=env,
        stdout=log.open("ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


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
    args = parser.parse_args()
    root: Path = args.root
    root.mkdir(parents=True, exist_ok=True)
    processes: list[subprocess.Popen[bytes]] = []

    base = {k: v for k, v in os.environ.items() if not k.startswith("BENTO_")}
    processes.append(sidecar("fake-telegram-serve", "--dir", str(root / "cloud"), "--port", str(FAKE_PORT), env=base, log=root / "fake.log"))
    threading.Thread(target=run_relay, args=(RELAY_PORT,), daemon=True).start()

    for name, port in HOST_PORTS.items():
        data = root / name
        data.mkdir(exist_ok=True)
        env = {
            **base,
            "BENTO_RUNTIME_MODE": "headless",
            "ENVIRONMENT": "development",
            "DATA_DIR": str(data),
            "STORAGE_BACKEND": "fake",
            "BENTO_FAKE_TELEGRAM_URL": f"http://127.0.0.1:{FAKE_PORT}",
            "BENTO_FAKE_TELEGRAM_MANUAL_LOGIN": "1",
            "BENTO_RELAY_URL": f"ws://127.0.0.1:{RELAY_PORT}",
            "BENTO_DEVICE_NAME": "Portátil de Ana" if name == "desktop" else "Mac de Ana",
            "EMBEDDINGS_PROVIDER": "disabled",
            "OCR_PROVIDER": "disabled",
        }
        processes.append(sidecar("migrate", env=env, log=root / f"{name}.log"))
        processes[-1].wait()
        processes.append(sidecar("api", "--port", str(port), env=env, log=root / f"{name}.log"))
        processes.append(sidecar("worker", env=env, log=root / f"{name}.log"))

    for port in HOST_PORTS.values():
        wait_for(f"http://127.0.0.1:{port}/api/health")
    print("TRUST_HOST_READY " + json.dumps({"fake": FAKE_PORT, "relay": RELAY_PORT, "hosts": HOST_PORTS}), flush=True)

    def stop(*_: object) -> None:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while True:
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
