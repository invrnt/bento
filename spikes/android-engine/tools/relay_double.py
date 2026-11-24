"""Run the backend's Python relay double (apps/api/tests/integration/pairing/relay_double.py) on 127.0.0.1.

usage: uv run --project apps/api python spikes/android-engine/tools/relay_double.py   (prints the ws:// URL)
Expose it to the phone with `adb reverse tcp:<port> tcp:<port>`.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "apps" / "api"))
from tests.integration.pairing.relay_double import RelayDouble  # noqa: E402


async def main() -> None:
    relay = RelayDouble()
    print(await relay.start(), flush=True)
    await asyncio.Event().wait()


asyncio.run(main())
