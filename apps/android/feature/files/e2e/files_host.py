"""Host side of the Archivos / Buscar / Compartir journeys (agent 40; testing/android-journeys.md 6, 8, 9).

Runs on the development machine, bound to 127.0.0.1 (exposed to the emulator with `adb reverse`):

- the remote fake Telegram cloud (`bento-sidecar fake-telegram-serve`, api/android-endpoints.md §9) on :8790,
- one headless "desktop" device (API on :8791 + worker) of the same account.

Journey 9 needs a desktop-indexed image. The OCR *engine* of that desktop is the backend's mock provider returning
`OCR_TEXT` for every image (RapidOCR models are not installed on CI hosts); thumbnails, the OCR job, the search index,
the encrypted sync to the phone and the phone's search are all real.

Usage: `uv run --project apps/api python files_host.py --root <dir> [--fake-port N --desktop-port N]`; prints
`FILES_HOST_READY {json}`. `run_journeys.sh` picks free host ports and maps the phone's fixed ones onto them. Sidecar
process groups are listed in `<root>/pgids` for the runner; on any exit this process stops them itself.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[4] / "api"
OCR_TEXT = "Factura de luz noviembre 2026"

# The worker, with only the OCR engine swapped for the mock (patched before anything imports it).
WORKER = f"""
import sys
import bento.infrastructure.services as services
from bento.adapters.ocr import MockOCRAdapter
services.get_ocr_provider = lambda settings: MockOCRAdapter(default_text={OCR_TEXT!r})
from bento.interfaces.desktop.launcher import main
sys.exit(main(["worker"]))
"""


def run(args: list[str], env: dict[str, str], log: Path, pgids: Path) -> subprocess.Popen[bytes]:
    process = subprocess.Popen(
        ["uv", "run", "--quiet", "--project", str(API_ROOT), *args],
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


def wait_for(url: str, timeout: float = 90) -> None:
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
    parser.add_argument("--desktop-port", type=int, default=8791)
    args = parser.parse_args()
    root: Path = args.root
    fake_port, desktop_port = args.fake_port, args.desktop_port
    root.mkdir(parents=True, exist_ok=True)
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
        cloud = ["bento-sidecar", "fake-telegram-serve", "--dir", str(root / "cloud"), "--port", str(fake_port)]
        processes.append(run(cloud, base, root / "fake.log", pgids))
        data = root / "desktop"
        data.mkdir(exist_ok=True)
        env = {
            **base,
            "BENTO_RUNTIME_MODE": "headless",
            "ENVIRONMENT": "development",
            "DATA_DIR": str(data),
            "STORAGE_BACKEND": "fake",
            "BENTO_FAKE_TELEGRAM_URL": f"http://127.0.0.1:{fake_port}",
            "BENTO_FAKE_TELEGRAM_MANUAL_LOGIN": "1",
            "BENTO_DEVICE_NAME": "Portátil de Ana",
            "EMBEDDINGS_PROVIDER": "disabled",
            "OCR_PROVIDER": "mock",
        }
        run(["bento-sidecar", "migrate"], env, root / "desktop.log", pgids).wait()
        processes.append(run(["bento-sidecar", "api", "--port", str(desktop_port)], env, root / "desktop.log", pgids))
        processes.append(run(["python", "-c", WORKER], env, root / "desktop.log", pgids))
        wait_for(f"http://127.0.0.1:{desktop_port}/api/health")
        print("FILES_HOST_READY " + json.dumps({"fake": fake_port, "desktop": desktop_port, "ocr_text": OCR_TEXT}), flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        raise SystemExit("a sidecar exited; see the host logs")
    finally:
        stop_all(processes)


if __name__ == "__main__":
    raise SystemExit(main())
