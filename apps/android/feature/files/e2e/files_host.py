"""Host side of the Archivos / Buscar / Compartir journeys (agent 40; testing/android-journeys.md 6, 8, 9).

Runs on the development machine, bound to 127.0.0.1 (exposed to the emulator with `adb reverse`):

- the remote fake Telegram cloud (`bento-sidecar fake-telegram-serve`, api/android-endpoints.md §9) on :8790,
- one headless "desktop" device (API on :8791 + worker) of the same account.

Journey 9 needs a desktop-indexed image. The OCR *engine* of that desktop is the backend's mock provider returning
`OCR_TEXT` for every image (RapidOCR models are not installed on CI hosts); thumbnails, the OCR job, the search index,
the encrypted sync to the phone and the phone's search are all real.

Usage: `uv run --project apps/api python files_host.py --root <dir>`; prints `FILES_HOST_READY {json}`.
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
FAKE_PORT = 8790
DESKTOP_PORT = 8791
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


def run(args: list[str], env: dict[str, str], log: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        ["uv", "run", "--quiet", "--project", str(API_ROOT), *args],
        env=env,
        stdout=log.open("ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


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
    root: Path = parser.parse_args().root
    root.mkdir(parents=True, exist_ok=True)
    base = {k: v for k, v in os.environ.items() if not k.startswith("BENTO_")}
    processes = [run(["bento-sidecar", "fake-telegram-serve", "--dir", str(root / "cloud"), "--port", str(FAKE_PORT)], base, root / "fake.log")]
    data = root / "desktop"
    data.mkdir(exist_ok=True)
    env = {
        **base,
        "BENTO_RUNTIME_MODE": "headless",
        "ENVIRONMENT": "development",
        "DATA_DIR": str(data),
        "STORAGE_BACKEND": "fake",
        "BENTO_FAKE_TELEGRAM_URL": f"http://127.0.0.1:{FAKE_PORT}",
        "BENTO_FAKE_TELEGRAM_MANUAL_LOGIN": "1",
        "BENTO_DEVICE_NAME": "Portátil de Ana",
        "EMBEDDINGS_PROVIDER": "disabled",
        "OCR_PROVIDER": "mock",
    }
    migrate = run(["bento-sidecar", "migrate"], env, root / "desktop.log")
    migrate.wait()
    processes.append(run(["bento-sidecar", "api", "--port", str(DESKTOP_PORT)], env, root / "desktop.log"))
    processes.append(run(["python", "-c", WORKER], env, root / "desktop.log"))
    wait_for(f"http://127.0.0.1:{DESKTOP_PORT}/api/health")
    print("FILES_HOST_READY " + json.dumps({"fake": FAKE_PORT, "desktop": DESKTOP_PORT, "ocr_text": OCR_TEXT}), flush=True)

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
