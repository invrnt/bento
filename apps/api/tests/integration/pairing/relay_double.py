"""In-process pairing relay implementing `orchestration/api/pairing-relay-contract.md` with `websockets`.

Behavior mirrors `apps/relay` (see its README): host first, `nameplate_taken` while a room lives or is
burned, `room_not_found` / `room_full` for guests, burning on close command or disconnect, error frames
followed by close `4001`, expiry with close `4000`, 64 KiB / 128 frame limits, and `429` before upgrade.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

NAMEPLATE = re.compile(r"^/v1/rooms/([0-9A-HJKMNP-TV-Z]{4})$")
ROLES = ("host", "guest")


@dataclass
class Room:
    created_at: float
    expires_at: float
    sockets: dict[str, ServerConnection] = field(default_factory=dict)
    burned: bool = False
    guest_joined: bool = False
    frames: dict[str, int] = field(default_factory=lambda: {"host": 0, "guest": 0})
    frame_sizes: list[int] = field(default_factory=list)
    alarm: asyncio.TimerHandle | None = None


class RelayDouble:
    def __init__(
        self,
        *,
        ttl_seconds: float = 600.0,
        max_frame_bytes: int = 64 * 1024,
        max_frames_per_side: int = 128,
        rate_limit_per_minute: int | None = None,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_frame_bytes = max_frame_bytes
        self.max_frames_per_side = max_frames_per_side
        self.rate_limit_per_minute = rate_limit_per_minute
        self.rooms: dict[str, Room] = {}
        self.events: list[tuple[str, str]] = []
        self.text_frames_seen: list[str] = []
        self._connections: list[float] = []
        self._server: Server | None = None
        self.url = ""

    async def start(self) -> str:
        self._server = await serve(
            self._handle, "127.0.0.1", 0, process_request=self._process_request, compression=None, max_size=None
        )
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}"
        return self.url

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        for room in self.rooms.values():
            if room.alarm is not None:
                room.alarm.cancel()

    # HTTP before upgrade

    def _process_request(self, connection: ServerConnection, request: Request) -> Response | None:
        parts = urlsplit(request.path)
        if parts.path == "/v1/health":
            return _json_response(HTTPStatus.OK, {"ok": True, "version": "0.0.0-double"})
        match = NAMEPLATE.match(parts.path)
        if match is None:
            return _json_response(HTTPStatus.NOT_FOUND, {"type": "error", "code": "not_found"})
        roles = parse_qs(parts.query).get("role", [])
        if len(roles) != 1 or roles[0] not in ROLES:
            return _json_response(HTTPStatus.BAD_REQUEST, {"type": "error", "code": "invalid_role"})
        if self.rate_limit_per_minute is not None:
            now = time.monotonic()
            self._connections = [stamp for stamp in self._connections if now - stamp < 60]
            if len(self._connections) >= self.rate_limit_per_minute:
                response = _json_response(HTTPStatus.TOO_MANY_REQUESTS, {"type": "error", "code": "rate_limited"})
                response.headers["Retry-After"] = "60"
                return response
            self._connections.append(now)
        if "upgrade" not in request.headers.get("Connection", "").lower():
            return _json_response(HTTPStatus.UPGRADE_REQUIRED, {"type": "error", "code": "upgrade_required"})
        return None

    # Rooms

    async def _handle(self, ws: ServerConnection) -> None:
        assert ws.request is not None
        parts = urlsplit(ws.request.path)
        match = NAMEPLATE.match(parts.path)
        assert match is not None
        nameplate = match.group(1)
        role = parse_qs(parts.query)["role"][0]
        error = await (self._admit_host(nameplate, ws) if role == "host" else self._admit_guest(nameplate, ws))
        if error is not None:
            self.events.append(("rejected", error))
            await _send(ws, {"type": "error", "code": error})
            await ws.close(4001, error)
            return
        room = self.rooms[nameplate]
        try:
            async for message in ws:
                await self._on_message(room, nameplate, role, ws, message)
        except ConnectionClosed:
            pass
        finally:
            current = self.rooms.get(nameplate)
            if current is room and not room.burned and room.sockets.get(role) is ws:
                await self._burn(room, None)

    async def _admit_host(self, nameplate: str, ws: ServerConnection) -> str | None:
        now = time.monotonic()
        existing = self.rooms.get(nameplate)
        if existing is not None:
            if now < existing.expires_at:
                return "nameplate_taken"
            await self._expire(nameplate)
        room = Room(created_at=now, expires_at=now + self.ttl_seconds)
        room.sockets["host"] = ws
        room.alarm = asyncio.get_running_loop().call_later(
            self.ttl_seconds, lambda: asyncio.ensure_future(self._expire(nameplate))
        )
        self.rooms[nameplate] = room
        self.events.append(("room_opened", nameplate))
        await _send(ws, _welcome("host", room))
        return None

    async def _admit_guest(self, nameplate: str, ws: ServerConnection) -> str | None:
        room = self.rooms.get(nameplate)
        if room is None:
            return "room_not_found"
        if time.monotonic() >= room.expires_at:
            await self._expire(nameplate)
            return "expired"
        if room.burned:
            return "room_full" if room.guest_joined else "room_not_found"
        if room.guest_joined:
            return "room_full"
        host = room.sockets.get("host")
        if host is None:
            await self._burn(room, None)
            return "room_not_found"
        room.guest_joined = True
        room.sockets["guest"] = ws
        await _send(ws, _welcome("guest", room))
        await _send(ws, {"type": "peer_joined"})
        await _send(host, {"type": "peer_joined"})
        self.events.append(("peer_joined", nameplate))
        return None

    async def _on_message(
        self, room: Room, nameplate: str, role: str, ws: ServerConnection, message: str | bytes
    ) -> None:
        if room.burned:
            return
        if time.monotonic() >= room.expires_at:
            await self._expire(nameplate)
            return
        size = len(message.encode("utf-8")) if isinstance(message, str) else len(message)
        if size > self.max_frame_bytes:
            await self._fail(room, ws, role, "message_too_large")
            return
        if isinstance(message, str):
            self.text_frames_seen.append(message)
            try:
                command = json.loads(message)
            except ValueError:
                command = None
            if command == {"type": "close"}:
                await self._burn(room, role)
            else:
                await self._fail(room, ws, role, "protocol")
            return
        peer = room.sockets.get("guest" if role == "host" else "host")
        if peer is None or room.frames[role] >= self.max_frames_per_side:
            await self._fail(room, ws, role, "protocol")
            return
        room.frames[role] += 1
        room.frame_sizes.append(size)
        try:
            await peer.send(message)
        except ConnectionClosed:
            await self._burn(room, None)

    async def _fail(self, room: Room, ws: ServerConnection, role: str, code: str) -> None:
        self.events.append(("frame_rejected", code))
        await _send(ws, {"type": "error", "code": code})
        await ws.close(4001, code)
        await self._burn(room, role)

    async def _burn(self, room: Room, initiator: str | None) -> None:
        if room.burned:
            return
        room.burned = True
        self.events.append(("room_burned", initiator or "disconnect"))
        for role, ws in list(room.sockets.items()):
            if role != initiator:
                await _send(ws, {"type": "peer_left"})
            await _send(ws, {"type": "closed", "reason": "burned"})
            await ws.close(1000, "burned")

    async def _expire(self, nameplate: str) -> None:
        room = self.rooms.pop(nameplate, None)
        if room is None:
            return
        if room.alarm is not None:
            room.alarm.cancel()
        self.events.append(("room_expired", nameplate))
        for ws in list(room.sockets.values()):
            await _send(ws, {"type": "closed", "reason": "expired"})
            await ws.close(4000, "expired")


@contextmanager
def relay_in_thread(**options: object) -> Iterator[RelayDouble]:
    """Run a `RelayDouble` on its own event loop thread (for TestClient-driven apps)."""
    relay = RelayDouble(**options)  # type: ignore[arg-type]
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(relay.start())
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=run, name="relay-double", daemon=True)
    thread.start()
    assert ready.wait(10)
    try:
        yield relay
    finally:
        asyncio.run_coroutine_threadsafe(relay.stop(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(10)
        loop.close()


async def _send(ws: ServerConnection, payload: dict[str, object]) -> None:
    with contextlib.suppress(ConnectionClosed):
        await ws.send(json.dumps(payload, separators=(",", ":")))


def _welcome(role: str, room: Room) -> dict[str, object]:
    expires = datetime.now(UTC).timestamp() + (room.expires_at - time.monotonic())
    return {"type": "welcome", "role": role, "expires_at": datetime.fromtimestamp(expires, UTC).isoformat()}


def _json_response(status: HTTPStatus, payload: dict[str, object]) -> Response:
    body = json.dumps(payload).encode("utf-8")
    headers = Headers([("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return Response(status.value, status.phrase, headers, body)
