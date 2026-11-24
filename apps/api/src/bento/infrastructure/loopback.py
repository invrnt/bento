"""Loopback listeners the API serves on (desktop sidecar, headless `--ephemeral`, Android engine).

Kept free of argparse/alembic/uvicorn imports so embedded hosts can bind without the desktop launcher.
"""

from __future__ import annotations

import socket

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})
_LISTEN_BACKLOG = 2048


def bind_loopback_listener(host: str) -> socket.socket:
    """A listening socket on an OS-assigned port of `host`, which must be a loopback address."""
    if host not in LOOPBACK_HOSTS:
        raise ValueError("Only loopback listeners are allowed")
    listener = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
    try:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            # Windows: forbid any other socket from binding the same address and port.
            listener.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        listener.bind((host, 0))
        listener.listen(_LISTEN_BACKLOG)
    except BaseException:
        listener.close()
        raise
    return listener
