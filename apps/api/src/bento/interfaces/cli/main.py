"""Console entry point `bento`. `_sidecar` (hidden) runs the API/worker/migrations inside the same executable."""

from __future__ import annotations

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    if getattr(sys, "frozen", False):
        import multiprocessing

        multiprocessing.freeze_support()
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["_sidecar"]:
        from bento.interfaces.desktop.launcher import main as launcher_main

        return launcher_main(args[1:])
    from bento.interfaces.cli.app import run

    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
