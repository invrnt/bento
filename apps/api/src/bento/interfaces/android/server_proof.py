"""Server identity proof for the embedded loopback API (`architecture/android-runtime.md` §2.1).

Every API start gets a fresh bearer token and a fresh `server_key`; both live in memory only. The Kotlin client
sends a random `X-Bento-Nonce` with each request, and this middleware answers with
`X-Bento-Proof: base64url(HMAC-SHA256(server_key, "bento-server-proof-v1|<port>|<nonce>"))`. The key never
crosses the socket, so another app that binds a port Bento freed cannot produce a valid proof, and the client
drops the response and restarts the API with new credentials. Binding the port into the MAC stops a squatter
from relaying a nonce to the real API on its new port.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re

from starlette.types import ASGIApp, Message, Receive, Scope, Send

NONCE_HEADER = b"x-bento-nonce"
PROOF_HEADER = b"x-bento-proof"
PROOF_LABEL = b"bento-server-proof-v1"
MIN_KEY_LENGTH = 32
_NONCE = re.compile(rb"^[A-Za-z0-9_-]{16,128}$")


def server_proof(key: str, port: int, nonce: str) -> str:
    """The proof for `nonce` on `port` (base64url, no padding); shared with the Kotlin client's check."""
    message = b"|".join((PROOF_LABEL, str(int(port)).encode("ascii"), nonce.encode("ascii")))
    digest = hmac.new(key.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class ServerProofMiddleware:
    """Adds `X-Bento-Proof` to HTTP responses and WebSocket accepts that carry a well-formed nonce.

    It wraps the request guard, so rejections (401, 400) are signed too: the proof says who answered, not
    whether the caller is authorized."""

    def __init__(self, app: ASGIApp, *, key: str, port: int) -> None:
        if len(key) < MIN_KEY_LENGTH:
            raise ValueError(f"server_key must contain at least {MIN_KEY_LENGTH} characters")
        self._app = app
        self._key = key
        self._port = int(port)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self._app(scope, receive, send)
            return
        nonces = [value for key, value in scope.get("headers", ()) if key.lower() == NONCE_HEADER]
        if len(nonces) != 1 or not _NONCE.match(nonces[0]):
            await self._app(scope, receive, send)
            return
        proof = server_proof(self._key, self._port, nonces[0].decode("ascii")).encode("ascii")

        async def signed_send(message: Message) -> None:
            if message["type"] in {"http.response.start", "websocket.accept"}:
                headers = [(k, v) for k, v in message.get("headers", ()) if k.lower() != PROOF_HEADER]
                message = {**message, "headers": [*headers, (PROOF_HEADER, proof)]}
            await send(message)

        await self._app(scope, receive, signed_send)
