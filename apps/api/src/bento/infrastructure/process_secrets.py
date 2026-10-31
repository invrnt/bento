"""Process-private holder for secrets the desktop host hands to a sidecar through its environment.

The sidecar launcher calls `adopt_environment_secrets` before anything else runs, which moves the
named variables out of `os.environ` (and therefore out of every child process environment) into this
module. Consumers read them with `get`; nothing here is ever logged or re-exported.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterable, MutableMapping

_lock = threading.Lock()
_values: dict[str, str] = {}


def adopt_environment_secrets(
    names: Iterable[str],
    environ: MutableMapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Remove `names` from `environ` (default `os.environ`) and keep the non-blank values here.

    Returns the adopted names. Blank values are removed but not kept, matching how an absent
    variable is treated.
    """
    target = os.environ if environ is None else environ
    adopted: list[str] = []
    with _lock:
        for name in names:
            value = target.pop(name, None)
            if value is not None and value.strip():
                _values[name] = value
                adopted.append(name)
    return tuple(adopted)


def get(name: str) -> str | None:
    with _lock:
        return _values.get(name)


def clear() -> None:
    """Forget every held secret (tests and controlled shutdown)."""
    with _lock:
        _values.clear()
