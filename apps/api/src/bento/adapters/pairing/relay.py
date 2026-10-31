"""WebSocket client for the pairing relay (`PairingRelayPort` / `PairingChannelPort`).

The relay only addresses a room by its nameplate and forwards opaque binary frames; SPAKE2,
key confirmation and AES-GCM run end to end in `application.pairing`. Nothing here logs frame
contents or nameplates.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus, InvalidURI, WebSocketException

from bento.adapters.pairing.frames import (
    CLOSE_COMMAND,
    CLOSE_EXPIRED,
    MAX_FRAME_BYTES,
    MAX_FRAMES_PER_SIDE,
    RELAY_ERROR_CODES,
    RelayEvent,
    RelayFrameError,
    RelayFrameType,
    health_url,
    normalize_relay_url,
    pairing_error_code,
    parse_control_frame,
    room_url,
)
from bento.domain.errors import ValidationFailedError
from bento.domain.pairing import PairingError, PairingRole

logger = logging.getLogger("bento.pairing.relay")

Connect = Callable[..., Any]

_MESSAGES = {
    "pairing_peer_left": "The other device left the pairing",
    "pairing_timeout": "The other device did not answer in time",
    "pairing_expired": "The pairing room expired",
    "pairing_nameplate_taken": "The pairing room is already in use",
    "pairing_room_not_found": "No device is waiting for this code",
    "pairing_room_full": "This pairing code was already used",
    "pairing_rate_limited": "Too many pairing attempts; wait a minute",
    "pairing_protocol": "The pairing relay rejected the connection",
    "pairing_relay_unavailable": "The pairing relay is unreachable",
}


def relay_error(code: str) -> PairingError:
    return PairingError(code, _MESSAGES.get(code, "Pairing failed"))


def _unavailable(message: str, reason: str) -> PairingError:
    error = PairingError("pairing_relay_unavailable", message)
    error.details = {"reason": reason}
    return error


@dataclass(frozen=True, slots=True)
class _Ended:
    code: str


class WebSocketPairingChannel:
    """One open room. A reader task demultiplexes control frames from binary peer frames.

    Binary frames already received are always delivered before the end of the room is reported,
    so a final `done` message is not lost when the peer closes right after sending it.
    """

    def __init__(self, connection: ClientConnection, *, close_timeout: float = 2.0) -> None:
        self._connection = connection
        self._close_timeout = close_timeout
        self._inbox: asyncio.Queue[bytes | _Ended] = asyncio.Queue()
        self._welcome: asyncio.Future[RelayEvent] = asyncio.get_running_loop().create_future()
        self._peer_joined = asyncio.Event()
        self._ended: _Ended | None = None
        self._ended_event = asyncio.Event()
        self._sent_frames = 0
        self._closed = False
        self._reader = asyncio.create_task(self._read(), name="pairing-relay-reader")
        self.expires_at: datetime | None = None

    def __repr__(self) -> str:
        return f"WebSocketPairingChannel(peer_joined={self._peer_joined.is_set()}, ended={self._ended is not None})"

    async def welcome(self, timeout_seconds: float) -> RelayEvent:
        """Wait for the relay's `welcome`; raises the mapped `PairingError` for an `error` frame."""
        try:
            event = await asyncio.wait_for(asyncio.shield(self._welcome), timeout_seconds)
        except TimeoutError:
            raise relay_error("pairing_relay_unavailable") from None
        self.expires_at = event.expires_at
        return event

    async def wait_for_peer(self, timeout_seconds: float) -> bool:
        if self._peer_joined.is_set():
            return True
        if self._ended is not None:
            raise relay_error(self._ended.code)
        joined = asyncio.create_task(self._peer_joined.wait())
        ended = asyncio.create_task(self._ended_event.wait())
        try:
            await asyncio.wait({joined, ended}, timeout=max(0.0, timeout_seconds), return_when=asyncio.FIRST_COMPLETED)
        finally:
            joined.cancel()
            ended.cancel()
        if self._peer_joined.is_set():
            return True
        if self._ended is not None:
            raise relay_error(self._ended.code)
        return False

    async def send(self, frame: bytes) -> None:
        data = bytes(frame)
        if not data or len(data) > MAX_FRAME_BYTES:
            raise ValidationFailedError("Pairing frames must be between 1 byte and 64 KiB")
        if self._ended is not None or self._closed:
            raise relay_error(self._ended.code if self._ended is not None else "pairing_peer_left")
        if not self._peer_joined.is_set():
            raise relay_error("pairing_protocol")
        if self._sent_frames >= MAX_FRAMES_PER_SIDE:
            raise relay_error("pairing_protocol")
        self._sent_frames += 1
        try:
            await self._connection.send(data)
        except ConnectionClosed:
            await self._reader_settled()
            raise relay_error(self._ended.code if self._ended is not None else "pairing_peer_left") from None

    async def receive(self, timeout_seconds: float) -> bytes:
        try:
            item = await asyncio.wait_for(self._inbox.get(), max(0.0, timeout_seconds))
        except TimeoutError:
            raise relay_error("pairing_timeout") from None
        if isinstance(item, _Ended):
            self._inbox.put_nowait(item)
            raise relay_error(item.code)
        return item

    async def close(self) -> None:
        """Burn the room (`{"type":"close"}`) and close the socket. Idempotent."""
        if self._closed:
            return
        self._closed = True
        if self._ended is None:
            with contextlib.suppress(WebSocketException, OSError):
                await asyncio.wait_for(self._connection.send(CLOSE_COMMAND), self._close_timeout)
        with contextlib.suppress(WebSocketException, OSError, TimeoutError):
            await asyncio.wait_for(self._connection.close(), self._close_timeout)
        self._reader.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._reader
        self._end("pairing_peer_left")

    async def _reader_settled(self) -> None:
        with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(asyncio.shield(self._reader), self._close_timeout)

    async def _read(self) -> None:
        code = "pairing_relay_unavailable"
        try:
            async for message in self._connection:
                if isinstance(message, bytes):
                    if not self._welcome.done() or not self._peer_joined.is_set():
                        code = "pairing_protocol"
                        return
                    self._inbox.put_nowait(message)
                    continue
                try:
                    event = parse_control_frame(message)
                except RelayFrameError:
                    code = "pairing_protocol"
                    return
                result = self._on_control(event)
                if result is not None:
                    code = result
                    return
        except ConnectionClosed as exc:
            received = exc.rcvd
            if received is not None and received.code == CLOSE_EXPIRED:
                code = "pairing_expired"
            elif received is not None and received.reason in RELAY_ERROR_CODES:
                code = pairing_error_code(received.reason)
        except Exception:  # pragma: no cover - defensive: never leave waiters hanging
            logger.exception("pairing relay reader failed")
        finally:
            self._end(code)
            with contextlib.suppress(Exception):
                await self._connection.close()

    def _on_control(self, event: RelayEvent) -> str | None:
        """Apply one control frame; returns the end code when the room is over."""
        if event.type is RelayFrameType.WELCOME:
            if not self._welcome.done():
                self._welcome.set_result(event)
            return None
        if event.type is RelayFrameType.PEER_JOINED:
            self._peer_joined.set()
            return None
        if event.type is RelayFrameType.PEER_LEFT:
            return "pairing_peer_left"
        if event.type is RelayFrameType.ERROR:
            error = relay_error(pairing_error_code(event.code))
            if not self._welcome.done():
                self._welcome.set_exception(error)
            return error.code
        if event.reason == "expired":
            return "pairing_expired"
        return "pairing_peer_left"

    def _end(self, code: str) -> None:
        if self._ended is not None:
            return
        self._ended = _Ended(code)
        self._inbox.put_nowait(self._ended)
        self._ended_event.set()
        if not self._welcome.done():
            self._welcome.set_exception(relay_error(code))
        # Retrieve the exception so an unawaited welcome never warns.
        if self._welcome.done() and not self._welcome.cancelled():
            self._welcome.exception()


class WebSocketPairingRelay:
    """`PairingRelayPort` for `settings.relay_url` (`wss://…`); an empty URL means the relay is disabled."""

    def __init__(
        self,
        relay_url: str,
        *,
        open_timeout: float = 10.0,
        health_timeout: float = 5.0,
        connect_factory: Connect = connect,
    ) -> None:
        self._invalid_reason: str | None = None
        try:
            self._relay_url = normalize_relay_url(relay_url)
        except ValueError as exc:
            logger.warning("pairing relay disabled: %s", exc)
            self._relay_url = ""
            self._invalid_reason = str(exc)
        self._open_timeout = open_timeout
        self._health_timeout = health_timeout
        self._connect = connect_factory

    def __repr__(self) -> str:
        return f"WebSocketPairingRelay(configured={bool(self._relay_url)})"

    @property
    def configured(self) -> bool:
        return bool(self._relay_url)

    async def available(self) -> bool:
        if not self._relay_url:
            return False
        return await asyncio.to_thread(self._health_ok, health_url(self._relay_url))

    async def open_room(self, nameplate: str, role: PairingRole) -> WebSocketPairingChannel:
        if self._invalid_reason is not None:
            raise _unavailable(f"The pairing relay is misconfigured: {self._invalid_reason}", "relay_url_invalid")
        if not self._relay_url:
            raise _unavailable("The pairing relay is disabled", "relay_not_configured")
        try:
            uri = room_url(self._relay_url, nameplate, role)
        except ValueError as exc:
            raise ValidationFailedError("Invalid pairing nameplate") from exc
        try:
            connection = await self._connect(
                uri,
                open_timeout=self._open_timeout,
                max_size=MAX_FRAME_BYTES,
                compression=None,
                close_timeout=2.0,
                user_agent_header="Bento",
            )
        except InvalidStatus as exc:
            status = exc.response.status_code
            logger.info("pairing relay refused the connection", extra={"status": status})
            raise relay_error("pairing_rate_limited" if status == 429 else "pairing_relay_unavailable") from None
        except (InvalidURI, InvalidHandshake, OSError, TimeoutError, WebSocketException):
            raise relay_error("pairing_relay_unavailable") from None
        channel = WebSocketPairingChannel(connection)
        try:
            await channel.welcome(self._open_timeout)
        except BaseException:
            await channel.close()
            raise
        return channel

    def _health_ok(self, url: str) -> bool:
        request = urllib.request.Request(url, headers={"User-Agent": "Bento"})
        try:
            with urllib.request.urlopen(request, timeout=self._health_timeout) as response:  # noqa: S310 - fixed scheme
                if response.status != 200:
                    return False
                payload = json.loads(response.read(4096).decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            return False
        return isinstance(payload, dict) and payload.get("ok") is True
