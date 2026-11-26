"""A stdlib fake of llama-server's embedding API (no aiohttp, no model, no network beyond loopback).

Endpoints, shaped like llama-server b12777:
- `GET /health`: `{"status": "ok"}`, or `503` while "loading" (`loading_health_responses`).
- `POST /v1/embeddings`: `input` as a string, a list of strings, or a list of `{"content": [parts]}` items
  (text and `image_url` parts). Returns OpenAI-shape `data[{index, embedding}]` with deterministic unit vectors
  from a hash of the exact input text (prefix included), so prefixes change the vector.
- `POST /tokenize`: `{"tokens": [...]}`, one fake token per whitespace-separated word.
Everything except `/health` requires `Authorization: Bearer <api key>` when a key is set (401 otherwise).
Inputs over `n_ubatch` fake tokens get llama-server's 500 "input is too large" error.

Standard library only and Python 3.8-compatible syntax, so `fake_llama_server_bin.py` can run it anywhere.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional


def fake_vector(text: str, dims: int) -> List[float]:
    values: List[float] = []
    counter = 0
    while len(values) < dims:
        block = hashlib.sha256("{}:{}".format(text, counter).encode("utf-8")).digest()
        for index in range(0, len(block), 4):
            raw = int.from_bytes(block[index : index + 4], "big", signed=False)
            values.append((raw / 0xFFFFFFFF) * 2.0 - 1.0)
            if len(values) == dims:
                break
        counter += 1
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


def fake_token_count(text: str) -> int:
    return max(1, len(text.split()))


class FakeLlamaState:
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        dims: int = 8,
        n_ubatch: int = 2048,
        loading_health_responses: int = 0,
        embedding_status: int = 200,
    ) -> None:
        self.api_key = api_key
        self.dims = dims
        self.n_ubatch = n_ubatch
        self.loading_health_responses = loading_health_responses
        self.embedding_status = embedding_status
        self.lock = threading.Lock()
        self.requests: List[Dict[str, Any]] = []

    def embedding_requests(self) -> List[Dict[str, Any]]:
        with self.lock:
            return [request for request in self.requests if request["path"] == "/v1/embeddings"]

    def embedding_inputs(self) -> List[List[Any]]:
        """The `input` list of every embeddings request, in order."""
        out = []
        for request in self.embedding_requests():
            raw = request["body"].get("input")
            out.append(raw if isinstance(raw, list) else [raw])
        return out


def _input_text(item: Any) -> Optional[str]:
    if isinstance(item, str):
        return item
    if isinstance(item, dict) and isinstance(item.get("content"), list):
        pieces = []
        for part in item["content"]:
            if not isinstance(part, dict):
                return None
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                pieces.append(part["text"])
            elif part.get("type") == "image_url" and isinstance(part.get("image_url"), dict):
                pieces.append("<image:{}>".format(hashlib.sha256(str(part["image_url"].get("url")).encode()).hexdigest()))
            else:
                return None
        return "".join(pieces)
    return None


class _Handler(BaseHTTPRequestHandler):
    server_version = "fake-llama-server/0"
    protocol_version = "HTTP/1.1"

    @property
    def state(self) -> FakeLlamaState:
        return self.server.fake_state  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return None

    def address_string(self) -> str:
        return "local"

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        self._record({})
        if self.path == "/health":
            with self.state.lock:
                loading = self.state.loading_health_responses > 0
                if loading:
                    self.state.loading_health_responses -= 1
            if loading:
                self._send(503, {"error": {"code": 503, "message": "Loading model", "type": "unavailable_error"}})
            else:
                self._send(200, {"status": "ok"})
            return
        self._send(404, {"error": {"code": 404, "message": "File Not Found", "type": "not_found_error"}})

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            self._record({})
            self._send(400, {"error": {"code": 400, "message": "Invalid JSON", "type": "invalid_request_error"}})
            return
        self._record(body)
        if not self._authorized():
            self._send(401, {"error": {"code": 401, "message": "Invalid API Key", "type": "authentication_error"}})
            return
        if self.path == "/v1/embeddings":
            self._embeddings(body)
        elif self.path == "/tokenize":
            content = body.get("content", "")
            self._send(200, {"tokens": list(range(fake_token_count(str(content))))})
        else:
            self._send(404, {"error": {"code": 404, "message": "File Not Found", "type": "not_found_error"}})

    def _embeddings(self, body: Dict[str, Any]) -> None:
        state = self.state
        if state.embedding_status != 200:
            self._send(state.embedding_status, {"error": {"code": state.embedding_status, "message": "Injected failure"}})
            return
        raw = body.get("input")
        items = raw if isinstance(raw, list) else [raw]
        texts = []
        for item in items:
            text = _input_text(item)
            if text is None:
                self._send(400, {"error": {"code": 400, "message": "Invalid input", "type": "invalid_request_error"}})
                return
            if fake_token_count(text) > state.n_ubatch:
                self._send(
                    500,
                    {"error": {"code": 500, "message": "input is too large to process. increase the physical batch size"}},
                )
                return
            texts.append(text)
        data = [{"object": "embedding", "index": i, "embedding": fake_vector(t, state.dims)} for i, t in enumerate(texts)]
        tokens = sum(fake_token_count(t) for t in texts)
        self._send(
            200,
            {
                "object": "list",
                "model": body.get("model", "fake"),
                "data": data,
                "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
            },
        )

    def _authorized(self) -> bool:
        key = self.state.api_key
        return not key or self.headers.get("Authorization") == "Bearer {}".format(key)

    def _record(self, body: Dict[str, Any]) -> None:
        with self.state.lock:
            self.state.requests.append(
                {"method": self.command, "path": self.path, "body": body, "authorization": self.headers.get("Authorization")}
            )

    def _send(self, status: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class _UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def get_request(self) -> Any:
        request, _ = super().get_request()
        return request, ("local", 0)


def make_server(state: FakeLlamaState, *, host: str = "127.0.0.1", port: int = 0) -> Any:
    """A loopback server, or a Unix socket server when `host` ends with `.sock` (like llama-server)."""
    server: Any
    if host.endswith(".sock"):
        server = _UnixHTTPServer(host, _Handler)
    else:
        server = ThreadingHTTPServer((host, port), _Handler)
        server.daemon_threads = True
    server.fake_state = state
    return server


class FakeLlamaServer:
    """In-process fake for unit tests: `with FakeLlamaServer(api_key="k") as fake: fake.base_url`."""

    def __init__(self, *, socket_path: Optional[str] = None, **state: Any) -> None:
        self.state = FakeLlamaState(**state)
        self._socket_path = socket_path
        self._server: Any = None
        self._thread: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        if self._socket_path:
            return "http+unix://{}".format(self._socket_path)
        host, port = self._server.server_address[:2]
        return "http://{}:{}".format(host, port)

    def __enter__(self) -> "FakeLlamaServer":
        self._server = make_server(self.state, host=self._socket_path or "127.0.0.1")
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._socket_path and os.path.exists(self._socket_path):
            os.unlink(self._socket_path)


__all__ = ["FakeLlamaServer", "FakeLlamaState", "fake_token_count", "fake_vector", "make_server"]
