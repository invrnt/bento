#!/usr/bin/env python3
"""A fake `llama-server` executable for the process adapter tests.

Accepts llama-server's flags, serves `tests/fakes/llama_server.py` on `--host` (a `.sock` path means a Unix
socket) and `--port`, and takes its key from `--api-key-file`, like the real server.

The child gets an allowlisted environment, so behaviour is controlled by a JSON file next to the model,
`<model>.fake.json` (all keys optional):
- `dims` (8): vector size. `loading_health_responses` (0): `/health` answers 503 that many times first.
- `fail_launches` (0): the first N launches exit with code 3 before serving.
- `crash_after_seconds`: exit with code 9 that long after starting to serve.
Each launch appends `{"argv", "env_keys", "key_file_mode"}` to `<model>.launches.jsonl`.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import threading
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llama_server import FakeLlamaState, make_server  # noqa: E402


def _control(model: str) -> Dict[str, Any]:
    try:
        with open(model + ".fake.json", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _launches(model: str) -> int:
    try:
        with open(model + ".launches.jsonl", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def main(argv: Optional[List[str]] = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("-m", dest="model", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--api-key-file", dest="api_key_file")
    parser.add_argument("-ub", dest="ubatch", type=int, default=512)
    parser.add_argument("--version", action="store_true")
    args, _ = parser.parse_known_args(raw)
    if args.version:
        print("version: 0 (fake)")
        return 0

    control = _control(args.model)
    previous = _launches(args.model)
    key = None
    key_mode = None
    if args.api_key_file:
        with open(args.api_key_file, encoding="utf-8") as handle:
            key = handle.readline().strip() or None
        key_mode = stat.S_IMODE(os.stat(args.api_key_file).st_mode)
    with open(args.model + ".launches.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": raw, "env_keys": sorted(os.environ), "key_file_mode": key_mode}) + "\n")

    if previous < int(control.get("fail_launches", 0)):
        return 3

    state = FakeLlamaState(
        api_key=key,
        dims=int(control.get("dims", 8)),
        n_ubatch=args.ubatch,
        loading_health_responses=int(control.get("loading_health_responses", 0)),
    )
    server = make_server(state, host=args.host, port=args.port)
    crash_after = control.get("crash_after_seconds")
    if crash_after is not None:
        timer = threading.Timer(float(crash_after), lambda: os._exit(9))
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever(poll_interval=0.05)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
