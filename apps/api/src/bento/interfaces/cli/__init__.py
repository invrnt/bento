"""The `bento` command-line interface: a thin HTTP client of the local Bento API (`product/cli.md`)."""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def cli_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("bento-api")
    except PackageNotFoundError:
        return "0.0.0"
