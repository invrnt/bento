"""Generic OpenAI-shape embedding client for llama-server (`EmbeddingProviderPort`).

- Applies the model's asymmetric prefixes: `ModelSpec.format_query` for queries and
  `ModelSpec.format_document` (title = file name or `none`) for chunks. Images take no prefix.
- Sends at most 8 inputs per request, each estimated below the model's `n_ubatch`.
- Truncates every vector to the space's Matryoshka dims and re-normalises it (`truncate_and_renormalize`).
- Reaches the server over a Unix socket or loopback with the per-launch key from the endpoint's key file.
- Never logs request bodies; errors carry only the HTTP status and the server's short message.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import mimetypes
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from bento.adapters.runtime.local_http import LocalHttpError, request
from bento.domain.indexing import EmbeddingRecord
from bento.domain.smart_search import (
    EMBEDDING_BATCH_SIZE,
    EmbeddingSpace,
    InvalidEmbeddingSpaceError,
    Modality,
    ModelSpec,
    UnsupportedModalityError,
    Vector,
    batched,
    chunk_text,
    estimate_tokens,
    parse_space_id,
    truncate_and_renormalize,
)
from bento.ports.models import EndpointInfo

EndpointSource = Callable[[], EndpointInfo | None]
EnsureEndpoint = Callable[[], Awaitable[EndpointInfo]]
AvailabilityCheck = Callable[[], Awaitable[bool]]
ModelSource = Callable[[], tuple[ModelSpec, EmbeddingSpace] | None]

EMBEDDINGS_PATH = "/v1/embeddings"
DOCUMENT_TIMEOUT_SECONDS = 300.0
QUERY_TIMEOUT_SECONDS = 30.0
MAX_IMAGE_BYTES = 16 * 1024 * 1024


class EmbeddingModelUnavailableError(RuntimeError):
    """No usable embedding server for this space (not installed, not started, or stopped)."""


class EmbeddingServerError(RuntimeError):
    """The server answered with an error or an unusable body."""


class EmbeddingInputTooLongError(EmbeddingServerError):
    """An input would not fit the model's physical batch (`n_ubatch`); the chunker should prevent it."""


class LlamaCppEmbeddingProvider:
    """`spec`/`space` are the configured model. With `model_source` (the worker's runtime), the model the runtime
    serves now wins: the activation status may pick another model or Matryoshka dims than the settings."""

    def __init__(
        self,
        *,
        spec: ModelSpec,
        space: EmbeddingSpace,
        endpoint: EndpointSource,
        ensure: EnsureEndpoint | None = None,
        available: AvailabilityCheck | None = None,
        model_source: ModelSource | None = None,
        batch_size: int = EMBEDDING_BATCH_SIZE,
        document_timeout_seconds: float = DOCUMENT_TIMEOUT_SECONDS,
        query_timeout_seconds: float = QUERY_TIMEOUT_SECONDS,
    ) -> None:
        _check_pair(spec, space)
        if not 0 < batch_size <= EMBEDDING_BATCH_SIZE:
            raise ValueError(f"batch_size must be in 1..{EMBEDDING_BATCH_SIZE}")
        self._spec = spec
        self._space = space
        self._endpoint = endpoint
        self._ensure = ensure
        self._available = available
        self._model_source = model_source
        self._batch_size = batch_size
        self._document_timeout = document_timeout_seconds
        self._query_timeout = query_timeout_seconds
        self._keys: dict[Path, str] = {}

    @property
    def space(self) -> EmbeddingSpace:
        return self._model()[1]

    @property
    def spec(self) -> ModelSpec:
        return self._model()[0]

    @property
    def chunk_tokens(self) -> int:
        return self._model()[0].chunk_tokens

    async def is_enabled(self) -> bool:
        if self._available is not None:
            return await self._available()
        return self._usable(self._endpoint()) is not None

    async def embed_query(self, text: str) -> Vector:
        query = text.strip()
        if not query:
            raise ValueError("The query is empty")
        info = await self._resolve(refresh=False)
        spec, space = self._model()
        if estimate_tokens(spec.format_query(query)) >= spec.ubatch_tokens:
            query = chunk_text(query, max_tokens=spec.chunk_tokens, max_chunks=1)[0].text
        vectors = await self._embed_inputs(info, [spec.format_query(query)], space.dims, self._query_timeout)
        return vectors[0]

    async def embed_documents(self, texts: Sequence[str], *, title: str | None = None) -> tuple[Vector, ...]:
        if not texts:
            return ()
        spec, _ = self._model()
        for text in texts:  # fail before starting anything when the chunker was bypassed
            if estimate_tokens(spec.format_document(text, title)) >= spec.ubatch_tokens:
                raise EmbeddingInputTooLongError("A text chunk does not fit the model's batch size")
        info = await self._resolve(refresh=False)
        spec, space = self._model()
        formatted = [spec.format_document(text, title) for text in texts]
        vectors: list[Vector] = []
        for batch in batched(formatted, self._batch_size):
            vectors.extend(await self._embed_inputs(info, list(batch), space.dims, self._document_timeout))
        return tuple(vectors)

    async def embed_image(self, path: Path) -> Vector:
        if not self.space.supports(Modality.IMAGE):
            raise UnsupportedModalityError(self.space.id, Modality.IMAGE.value)
        content = await asyncio.to_thread(_read_image, path)
        mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        data_url = f"data:{mime_type};base64,{base64.b64encode(content).decode('ascii')}"
        part = {"type": "image_url", "image_url": {"url": data_url}}
        info = await self._resolve(refresh=False)
        vectors = await self._embed_inputs(info, [{"content": [part]}], self.space.dims, self._document_timeout)
        return vectors[0]

    async def embed_asset(self, asset_id: str, source_ref: str) -> EmbeddingRecord:
        """Pre-Stage-24 entry point: embeds `source_ref` as one document text."""
        await self.embed_documents([source_ref])
        spec, space = self._model()
        digest = hashlib.sha1(f"{space.id}:{asset_id}:{source_ref}".encode("utf-8")).hexdigest()
        return EmbeddingRecord(
            id=f"emb_{digest[:24]}",
            asset_id=asset_id,
            provider=spec.model_id,
            vector_ref=f"llama.cpp:{digest[:32]}",
            dimensions=space.dims,
        )

    # ----------------------------------------------------------------------------------

    def _model(self) -> tuple[ModelSpec, EmbeddingSpace]:
        if self._model_source is not None:
            current = self._model_source()
            if current is not None:
                return current
        return self._spec, self._space

    def _usable(self, info: EndpointInfo | None) -> EndpointInfo | None:
        """The endpoint serves the current model (any Matryoshka dims of it)."""
        if info is None:
            return None
        try:
            model_id, revision, _ = parse_space_id(info.space_id)
        except InvalidEmbeddingSpaceError:
            return None
        spec, _ = self._model()
        if (model_id, revision) != (spec.model_id, spec.revision):
            return None
        return info

    async def _resolve(self, *, refresh: bool) -> EndpointInfo:
        info = self._usable(self._endpoint())
        if info is not None and not refresh:
            return info
        if self._ensure is not None:
            try:
                info = self._usable(await self._ensure())
            except Exception as exc:  # noqa: BLE001 - surfaced as "unavailable" to the indexing job
                raise EmbeddingModelUnavailableError("The embedding server is not available") from exc
        if info is None:
            raise EmbeddingModelUnavailableError("The embedding server is not available")
        return info

    async def _embed_inputs(self, info: EndpointInfo, inputs: list[Any], dims: int, timeout: float) -> tuple[Vector, ...]:
        body = {"input": inputs, "model": self._model()[0].model_id, "encoding_format": "float"}
        for attempt in range(2):
            last = attempt == 1
            try:
                api_key = self._api_key(info)
                response = await asyncio.to_thread(
                    request, info.base_url, "POST", EMBEDDINGS_PATH, body=body, api_key=api_key, timeout=timeout
                )
            except (OSError, LocalHttpError) as exc:
                if last:
                    raise EmbeddingServerError("The embedding server is unavailable") from exc
                info = await self._resolve(refresh=True)
                continue
            if response.status == 401 and not last:  # the server restarted with a new key
                self._keys.pop(info.api_key_file, None)
                info = await self._resolve(refresh=True)
                continue
            if not response.ok:
                message = response.error_message()
                suffix = f": {message}" if message else ""
                raise EmbeddingServerError(f"The embedding server returned {response.status}{suffix}")
            try:
                return self._vectors(response.json(), expected=len(inputs), dims=dims)
            except LocalHttpError as exc:
                raise EmbeddingServerError(str(exc)) from exc
        raise EmbeddingServerError("The embedding server is unavailable")  # pragma: no cover

    def _api_key(self, info: EndpointInfo) -> str | None:
        path = info.api_key_file
        if str(path) in {"", "."}:
            return None  # an external server configured by the person: no key
        key = self._keys.get(path)
        if key is None:
            key = path.read_text(encoding="utf-8").strip()
            self._keys = {path: key}  # only the current launch's key is kept
        return key

    @staticmethod
    def _vectors(payload: Any, *, expected: int, dims: int) -> tuple[Vector, ...]:
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or len(data) != expected:
            raise EmbeddingServerError("The embedding server returned an unexpected number of vectors")
        rows: list[tuple[int, Any]] = []
        for position, row in enumerate(data):
            if not isinstance(row, dict):
                raise EmbeddingServerError("The embedding server returned a malformed vector")
            index = row.get("index", position)
            rows.append((index if isinstance(index, int) else position, row.get("embedding")))
        vectors: list[Vector] = []
        for _, embedding in sorted(rows, key=lambda item: item[0]):
            if not isinstance(embedding, list) or not all(
                isinstance(value, int | float) and not isinstance(value, bool) for value in embedding
            ):
                raise EmbeddingServerError("The embedding server returned a malformed vector")
            try:
                vectors.append(truncate_and_renormalize(embedding, dims))
            except InvalidEmbeddingSpaceError as exc:
                raise EmbeddingServerError("The embedding server returned an unusable vector") from exc
        return tuple(vectors)


def _check_pair(spec: ModelSpec, space: EmbeddingSpace) -> None:
    if (space.model_id, space.revision) != (spec.model_id, spec.revision):
        raise ValueError("The embedding space does not belong to this model")


def _read_image(path: Path) -> bytes:
    size = path.stat().st_size
    if size > MAX_IMAGE_BYTES:
        raise ValueError("Image previews for embedding must be at most 16 MiB")
    return path.read_bytes()
