"""Boot two (or more) local Bento devices against the fake Telegram cloud for manual UI testing.

    uv run --project apps/api python scripts/smoke/two_devices.py                 # fresh devices a and b
    uv run --project apps/api python scripts/smoke/two_devices.py --setup paired  # a has a vault, b is paired
    uv run --project apps/api python scripts/smoke/two_devices.py --web           # also start one Vite per device

Every device runs the real entrypoints (`launcher migrate`, `bento.interfaces.http.main`,
`bento.interfaces.worker.main`) with its own data directory under `<root>/<name>/data` and its own API port;
all of them share `<root>/fake-telegram` and, unless `--no-relay`, an in-process pairing relay double.
State is kept between runs (use `--reset` to start over). Ctrl+C stops everything.

Helpers for a cloud that is already running (same `--root`):

    two_devices.py fault flood_wait 90   # every device gets FLOOD_WAIT for 90 s (Activity shows it after 60 s)
    two_devices.py fault network 30      # Telegram unreachable for 30 s
    two_devices.py fault clear
    two_devices.py inbox ~/Pictures/foto.jpg   # "forward" a file to the Bento · Bandeja channel
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from bento.adapters.fake_telegram import FakeTelegramCloud  # noqa: E402
from bento.adapters.fake_telegram.cloud import DocumentUpload  # noqa: E402
from bento.domain.vault import VaultChannelRole  # noqa: E402
from tests.e2e.harness import Device, World, relay_double, sigterm_as_interrupt, wait_until  # noqa: E402
from tests.e2e.journey_support import (  # noqa: E402
    DOCUMENT_BYTES,
    PHOTO_BYTES,
    channel_id,
    pair_over_relay,
    wait_for_pairing,
    wait_for_vault_ready,
)

NAMES = "abcde"


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    root = Path(arguments.root).expanduser().resolve()
    if arguments.command == "fault":
        return _fault(root, arguments.kind, arguments.seconds)
    if arguments.command == "inbox":
        return _inbox(root, Path(arguments.file).expanduser())
    return _up(root, arguments)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="two_devices.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--root", default=str(REPO_ROOT / "data" / "dev" / "smoke"), help="state directory (default: data/dev/smoke)"
    )
    _up_options(parser)
    commands = parser.add_subparsers(dest="command")
    fault = commands.add_parser("fault", help="inject a Telegram fault into the running fake cloud")
    fault.add_argument("kind", choices=("flood_wait", "network", "clear"))
    fault.add_argument("seconds", nargs="?", type=float, default=60.0)
    inbox = commands.add_parser("inbox", help="post a file to the Inbox channel, as if forwarded from a phone")
    inbox.add_argument("file")
    return parser


def _up_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--reset", action="store_true", help="delete the state directory first")
    parser.add_argument("--devices", type=int, default=2, choices=range(1, len(NAMES) + 1), metavar="N")
    parser.add_argument("--api-port", type=int, default=8000, help="API port of device a; the next ones count up")
    parser.add_argument("--web-port", type=int, default=5173, help="web port of device a; the next ones count up")
    parser.add_argument("--relay-url", default=None, help="use this relay (e.g. ws://127.0.0.1:8787 from wrangler dev)")
    parser.add_argument("--no-relay", action="store_true", help="no relay: pairing uses the Sync-channel fallback")
    parser.add_argument(
        "--manual-login",
        action="store_true",
        help="devices after a do not auto-approve their own QR (POST /api/dev/fake-telegram/approve-login)",
    )
    parser.add_argument(
        "--setup",
        choices=("none", "vault", "paired"),
        default="none",
        help="vault: a signs in, creates the vault and uploads samples; paired: b is also paired with a",
    )
    parser.add_argument("--web", action="store_true", help="also run `npm --prefix apps/web run dev` per device")


def _up(root: Path, arguments: argparse.Namespace) -> int:
    if arguments.reset and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    ports = [(arguments.api_port + index, arguments.web_port + index) for index in range(arguments.devices)]
    busy = [port for pair in ports for port in pair[: 2 if arguments.web else 1] if not _port_free(port)]
    if busy:
        ports_text = ", ".join(map(str, busy))
        print(f"Ports already in use: {ports_text} (stop the other instance or pass --api-port/--web-port)")
        return 1

    with sigterm_as_interrupt(), _relay(arguments) as relay_url:
        world = World(root, relay_url=relay_url)
        web: list[subprocess.Popen[bytes]] = []
        try:
            for index, (api_port, web_port) in enumerate(ports):
                name = NAMES[index]
                print(f"Starting device {name} ...", flush=True)
                world.device(name, port=api_port, web_port=web_port, manual_login=arguments.manual_login and index > 0)
            recovery = _prepare(world, arguments.setup)
            if arguments.web:
                web = [_start_web(device) for device in world.devices.values()]
            _print_summary(world, relay_url, recovery, web_started=bool(web))
            _wait_forever(world)
        except KeyboardInterrupt:
            pass
        finally:
            print("\nStopping ...", flush=True)
            for process in web:
                _stop_process(process)
            world.stop()
    return 0


@contextlib.contextmanager
def _relay(arguments: argparse.Namespace) -> Iterator[str]:
    if arguments.no_relay:
        yield ""
    elif arguments.relay_url:
        yield arguments.relay_url
    else:
        with relay_double() as url:
            yield url


def _prepare(world: World, setup: str) -> str | None:
    """Sign a in and create the vault (once); optionally pair b. Returns a fresh recovery code when one was made."""
    if setup == "none":
        return None
    devices = list(world.devices.values())
    host = devices[0]
    recovery = None
    if host.get("/vault")["state"] != "ready":
        if host.get("/account")["step"] != "authorized":
            host.sign_in_with_qr()
        recovery = host.post("/vault")["recovery_code"]
        host.upload("factura-demo.txt", DOCUMENT_BYTES, "text/plain")
        host.upload("playa-demo.jpg", PHOTO_BYTES, "image/jpeg", mode="photos")
    if setup == "paired" and len(devices) > 1:
        guest = devices[1]
        if guest.get("/vault")["state"] != "ready":
            if world.relay_url:
                pair_over_relay(host, guest)
            else:
                _pair_through_sync_channel(host, guest)
            wait_for_vault_ready(guest)
    return recovery


def _pair_through_sync_channel(host: Device, guest: Device) -> None:
    if guest.get("/account")["step"] != "authorized":
        guest.sign_in_with_qr()
    asked = guest.post("/pairing/request")
    request = wait_until(lambda: host.get("/pairing/requests")["items"], timeout=30, message="pair_request")[0]
    host.post(f"/pairing/requests/{request['id']}/review")
    wait_for_pairing(guest, asked["id"], {"awaiting_approval"})
    host.post(f"/pairing/requests/{request['id']}/approve")
    wait_for_pairing(guest, asked["id"], {"completed"}, timeout=40)


def _start_web(device: Device) -> subprocess.Popen[bytes]:
    if not (REPO_ROOT / "apps" / "web" / "node_modules").is_dir():
        raise SystemExit("apps/web/node_modules is missing: run `npm --prefix apps/web ci` first")
    log = (device.logs_dir / "web.log").open("ab")
    try:
        return subprocess.Popen(
            ["npm", "--prefix", "apps/web", "run", "dev", "--", "--port", str(device.web_port), "--strictPort"],
            cwd=REPO_ROOT,
            env={**os.environ, "VITE_API_BASE_URL": device.base_url},
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log.close()


def _print_summary(world: World, relay_url: str, recovery: str | None, *, web_started: bool) -> None:
    relay = relay_url or "none (pairing uses the Telegram Sync channel)"
    print(f"\nFake Telegram cloud: {_shown(world.cloud_dir)}\nRelay: {relay}\n")
    for device in world.devices.values():
        ui = f"http://127.0.0.1:{device.web_port}"
        print(f"  {device.name}  API {device.base_url}  UI {ui}  logs {_shown(device.logs_dir)}")
        if not web_started:
            print(
                f"     VITE_API_BASE_URL={device.base_url} npm --prefix apps/web run dev -- "
                f"--port {device.web_port} --strictPort"
            )
    if recovery:
        print(f"\nRecovery code of the new vault: {recovery}")
    print("\nPress Ctrl+C to stop. Faults: two_devices.py fault flood_wait 90 | network 30 | clear\n", flush=True)


def _wait_forever(world: World) -> None:
    while True:
        time.sleep(1.0)
        for device in world.devices.values():
            device.assert_running()


def _fault(root: Path, kind: str, seconds: float) -> int:
    cloud = FakeTelegramCloud(root / "fake-telegram")
    if kind == "clear":
        cloud.clear_fault()
        print("Fault cleared")
    else:
        cloud.inject_fault(kind, seconds=seconds)
        print(f"Injected {kind} for {seconds:.0f} s")
    return 0


def _inbox(root: Path, file: Path) -> int:
    if not file.is_file():
        print(f"Not a file: {file}")
        return 1
    cloud = FakeTelegramCloud(root / "fake-telegram")
    world = World(root)
    try:
        inbox = channel_id(world, VaultChannelRole.INBOX)
    except KeyError:
        print("No vault in this fake cloud yet: create one first")
        return 1
    message = cloud.post_message(inbox, document=DocumentUpload(file, file.name))
    print(f"Posted {file.name} to Bento · Bandeja (message {message.id})")
    return 0


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)


def _shown(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
