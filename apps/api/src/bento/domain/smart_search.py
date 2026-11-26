"""Smart search (search by meaning) domain: model specs, embedding spaces, the
activation state machine, the chunker and Matryoshka truncation.

Pure: standard library only. Contract: `orchestration/api/smart-search-contract.md`.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from bento.domain.errors import DomainError
from bento.domain.indexing import IndexProviderState

Vector = tuple[float, ...]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{7,40}$")


class SmartSearchError(DomainError):
    pass


class InvalidModelSpecError(SmartSearchError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("invalid_model_spec", message, dict(details or {}))


class InvalidEmbeddingSpaceError(SmartSearchError):
    def __init__(self, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("invalid_embedding_space", message, dict(details or {}))


class UnsupportedModalityError(SmartSearchError):
    def __init__(self, space_id: str, modality: str) -> None:
        super().__init__(
            "unsupported_modality",
            "The active embedding space does not support this input",
            {"space_id": space_id, "modality": modality},
        )


class IllegalSmartSearchTransitionError(SmartSearchError):
    def __init__(self, state: SmartSearchState, event: SmartSearchEventKind) -> None:
        super().__init__(
            "illegal_smart_search_transition",
            "This smart search action is not allowed in the current state",
            {"state": state.value, "event": event.value},
        )


# --------------------------------------------------------------------------------------
# Model spec and manifest


class Modality(StrEnum):
    TEXT = "text"
    IMAGE = "image"


class Pooling(StrEnum):
    MEAN = "mean"
    LAST = "last"
    CLS = "cls"


class ModelFileRole(StrEnum):
    WEIGHTS = "weights"
    MMPROJ = "mmproj"


@dataclass(frozen=True, slots=True)
class ModelFile:
    name: str
    role: ModelFileRole
    urls: tuple[str, ...]
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        if not self.name or "/" in self.name or "\\" in self.name or self.name.startswith("."):
            raise InvalidModelSpecError("Model file name must be a plain file name", {"name": self.name})
        if not self.urls:
            raise InvalidModelSpecError("Model file needs at least one URL", {"name": self.name})
        for url in self.urls:
            if not url.startswith("https://"):
                raise InvalidModelSpecError("Model file URLs must use https", {"name": self.name})
        if self.size_bytes <= 0:
            raise InvalidModelSpecError("Model file size must be positive", {"name": self.name})
        if not _SHA256_RE.match(self.sha256):
            raise InvalidModelSpecError("Model file sha256 must be 64 lowercase hex chars", {"name": self.name})


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One managed model at one pinned revision (a manifest entry)."""

    model_id: str
    revision: str
    display_name: str
    license_spdx: str
    source_url: str
    files: tuple[ModelFile, ...]
    native_dims: int
    matryoshka_dims: tuple[int, ...]
    default_dims: int
    pooling: Pooling
    context_tokens: int
    ubatch_tokens: int
    query_template: str
    document_template: str
    modalities: frozenset[Modality] = frozenset({Modality.TEXT})
    chunk_tokens: int = 512

    def __post_init__(self) -> None:
        if not _ID_RE.match(self.model_id):
            raise InvalidModelSpecError("model_id must be lowercase kebab/dot id", {"model_id": self.model_id})
        if not _REVISION_RE.match(self.revision):
            raise InvalidModelSpecError("revision must be a hex commit id", {"revision": self.revision})
        if not self.license_spdx:
            raise InvalidModelSpecError("license_spdx is required", {"model_id": self.model_id})
        weights = [f for f in self.files if f.role is ModelFileRole.WEIGHTS]
        if len(weights) != 1:
            raise InvalidModelSpecError("A model needs exactly one weights file", {"model_id": self.model_id})
        if len({f.name for f in self.files}) != len(self.files):
            raise InvalidModelSpecError("Model file names must be unique", {"model_id": self.model_id})
        if self.native_dims not in self.matryoshka_dims:
            raise InvalidModelSpecError("matryoshka_dims must include native_dims", {"model_id": self.model_id})
        if any(d <= 0 or d > self.native_dims for d in self.matryoshka_dims):
            raise InvalidModelSpecError("matryoshka_dims must be in 1..native_dims", {"model_id": self.model_id})
        if self.default_dims not in self.matryoshka_dims:
            raise InvalidModelSpecError("default_dims must be a matryoshka dim", {"model_id": self.model_id})
        if "{q}" not in self.query_template:
            raise InvalidModelSpecError("query_template must contain {q}", {"model_id": self.model_id})
        if "{text}" not in self.document_template:
            raise InvalidModelSpecError("document_template must contain {text}", {"model_id": self.model_id})
        if Modality.TEXT not in self.modalities:
            raise InvalidModelSpecError("Every managed model embeds text", {"model_id": self.model_id})
        if not 0 < self.chunk_tokens <= self.ubatch_tokens <= self.context_tokens:
            raise InvalidModelSpecError(
                "Need 0 < chunk_tokens <= ubatch_tokens <= context_tokens", {"model_id": self.model_id}
            )

    @property
    def weights(self) -> ModelFile:
        return next(f for f in self.files if f.role is ModelFileRole.WEIGHTS)

    @property
    def text_bytes(self) -> int:
        """Bytes the person downloads to turn on text smart search."""
        return self.weights.size_bytes

    def validate_dims(self, dims: int) -> int:
        if dims not in self.matryoshka_dims:
            raise InvalidModelSpecError(
                "Unsupported embedding dimensions for this model",
                {"model_id": self.model_id, "dims": dims, "allowed": list(self.matryoshka_dims)},
            )
        return dims

    def space(self, dims: int | None = None, *, with_images: bool = False) -> EmbeddingSpace:
        chosen = self.validate_dims(self.default_dims if dims is None else dims)
        modalities = {Modality.TEXT}
        if with_images:
            if Modality.IMAGE not in self.modalities:
                raise UnsupportedModalityError(f"{self.model_id}@{self.revision}", Modality.IMAGE.value)
            modalities.add(Modality.IMAGE)
        return EmbeddingSpace(
            id=space_id_for(self.model_id, self.revision, chosen),
            model_id=self.model_id,
            revision=self.revision,
            dims=chosen,
            modalities=frozenset(modalities),
        )

    def format_query(self, query: str) -> str:
        return self.query_template.replace("{q}", query.strip())

    def format_document(self, text: str, title: str | None = None) -> str:
        clean_title = (title or "").strip() or "none"
        return self.document_template.replace("{title}", clean_title).replace("{text}", text)


MANIFEST_SCHEMA_VERSION = 1


def parse_manifest(data: Mapping[str, Any]) -> tuple[tuple[ModelSpec, ...], str]:
    """Parse `infrastructure/models/manifest.json` content.

    Returns the specs and the recommended (default) model id.
    """
    if data.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise InvalidModelSpecError("Unsupported manifest schema_version", {"got": data.get("schema_version")})
    raw_models = data.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise InvalidModelSpecError("Manifest needs a non-empty models list")
    specs = tuple(_parse_model(entry) for entry in raw_models)
    keys = [(s.model_id, s.revision) for s in specs]
    if len(set(keys)) != len(keys):
        raise InvalidModelSpecError("Duplicate model_id@revision in manifest")
    default_id = data.get("default_model_id")
    if default_id not in {s.model_id for s in specs}:
        raise InvalidModelSpecError("default_model_id must name a manifest model", {"got": default_id})
    return specs, str(default_id)


def _parse_model(entry: Any) -> ModelSpec:
    if not isinstance(entry, Mapping):
        raise InvalidModelSpecError("Manifest model entries must be objects")
    try:
        files = tuple(
            ModelFile(
                name=str(f["name"]),
                role=ModelFileRole(f["role"]),
                urls=tuple(str(u) for u in f["urls"]),
                size_bytes=int(f["size_bytes"]),
                sha256=str(f["sha256"]),
            )
            for f in entry["files"]
        )
        return ModelSpec(
            model_id=str(entry["model_id"]),
            revision=str(entry["revision"]),
            display_name=str(entry["display_name"]),
            license_spdx=str(entry["license_spdx"]),
            source_url=str(entry["source_url"]),
            files=files,
            native_dims=int(entry["native_dims"]),
            matryoshka_dims=tuple(int(d) for d in entry["matryoshka_dims"]),
            default_dims=int(entry["default_dims"]),
            pooling=Pooling(entry["pooling"]),
            context_tokens=int(entry["context_tokens"]),
            ubatch_tokens=int(entry["ubatch_tokens"]),
            query_template=str(entry["query_template"]),
            document_template=str(entry["document_template"]),
            modalities=frozenset(Modality(m) for m in entry.get("modalities", ["text"])),
            chunk_tokens=int(entry.get("chunk_tokens", 512)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidModelSpecError("Malformed manifest model entry", {"error": type(exc).__name__}) from exc


# --------------------------------------------------------------------------------------
# Embedding spaces

LEGACY_SPACE_PREFIX = "legacy:"


@dataclass(frozen=True, slots=True)
class EmbeddingSpace:
    """A vector space: vectors are comparable only within the same space id."""

    id: str
    model_id: str
    revision: str
    dims: int
    modalities: frozenset[Modality] = frozenset({Modality.TEXT})

    def __post_init__(self) -> None:
        if self.dims <= 0:
            raise InvalidEmbeddingSpaceError("dims must be positive", {"dims": self.dims})

    @property
    def is_legacy(self) -> bool:
        return self.id.startswith(LEGACY_SPACE_PREFIX)

    def supports(self, modality: Modality) -> bool:
        return modality in self.modalities


def space_id_for(model_id: str, revision: str, dims: int) -> str:
    return f"{model_id}@{revision}/{dims}"


def legacy_space_id(provider: str, dims: int) -> str:
    """Space id for vectors written before Stage 24 (`asset_embeddings.provider`)."""
    return f"{LEGACY_SPACE_PREFIX}{provider or 'unknown'}/{dims}"


def parse_space_id(space_id: str) -> tuple[str, str, int]:
    """Split `<model_id>@<revision>/<dims>` (or `legacy:<provider>/<dims>`)."""
    head, sep, dims_text = space_id.rpartition("/")
    if not sep or not dims_text.isdigit() or int(dims_text) <= 0:
        raise InvalidEmbeddingSpaceError("Malformed space id", {"space_id": space_id})
    if head.startswith(LEGACY_SPACE_PREFIX):
        provider = head[len(LEGACY_SPACE_PREFIX) :]
        if not provider:
            raise InvalidEmbeddingSpaceError("Malformed space id", {"space_id": space_id})
        return provider, "", int(dims_text)
    model_id, at, revision = head.partition("@")
    if not at or not _ID_RE.match(model_id) or not _REVISION_RE.match(revision):
        raise InvalidEmbeddingSpaceError("Malformed space id", {"space_id": space_id})
    return model_id, revision, int(dims_text)


class PeerVectorDecision(StrEnum):
    INDEX = "index"
    STORE_ONLY = "store_only"


def peer_vector_decision(
    active_space_id: str | None, peer_space_id: str | None, peer_dims: int
) -> PeerVectorDecision:
    """Synced `asset_index.embedding` vectors are indexed only in the same space.

    Peers that send no `space` (pre-Stage-24) are an unknown space: stored, never indexed.
    """
    if active_space_id is None or not peer_space_id or peer_space_id != active_space_id:
        return PeerVectorDecision.STORE_ONLY
    try:
        _, _, dims = parse_space_id(peer_space_id)
    except InvalidEmbeddingSpaceError:
        return PeerVectorDecision.STORE_ONLY
    return PeerVectorDecision.INDEX if dims == peer_dims else PeerVectorDecision.STORE_ONLY


# --------------------------------------------------------------------------------------
# Matryoshka truncation


def truncate_and_renormalize(vector: Sequence[float], dims: int) -> Vector:
    """Keep the first `dims` components and L2-normalise them (Matryoshka truncation)."""
    if dims <= 0:
        raise InvalidEmbeddingSpaceError("dims must be positive", {"dims": dims})
    if dims > len(vector):
        raise InvalidEmbeddingSpaceError("dims exceeds the vector length", {"dims": dims, "length": len(vector)})
    head = [float(v) for v in vector[:dims]]
    if any(not math.isfinite(v) for v in head):
        raise InvalidEmbeddingSpaceError("Vector has non-finite values")
    norm = math.sqrt(math.fsum(v * v for v in head))
    if norm == 0.0:
        raise InvalidEmbeddingSpaceError("Cannot normalise a zero vector")
    return tuple(v / norm for v in head)


def best_chunk_scores(hits: Iterable[tuple[str, float]]) -> dict[str, float]:
    """An asset's vector score is the best score among its chunks."""
    best: dict[str, float] = {}
    for asset_id, score in hits:
        if asset_id not in best or score > best[asset_id]:
            best[asset_id] = score
    return best


# --------------------------------------------------------------------------------------
# Chunker

DEFAULT_CHUNK_TOKENS = 512
MAX_CHUNKS_PER_ASSET = 16
CHARS_PER_TOKEN = 3
EMBEDDING_BATCH_SIZE = 8


@dataclass(frozen=True, slots=True)
class TextChunk:
    chunk_no: int
    text: str
    page: int | None
    estimated_tokens: int


def _is_wide(char: str) -> bool:
    code = ord(char)
    return (
        0x3040 <= code <= 0x30FF  # kana
        or 0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF  # CJK ideographs
        or 0xAC00 <= code <= 0xD7AF  # hangul
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x2FFFF
    )


def _is_symbol(char: str) -> bool:
    return ord(char) > 0x2000 and unicodedata.category(char) in {"So", "Sk", "Cs", "Co"}


def _char_cost(char: str) -> tuple[int, int]:
    """(whole tokens, plain chars) contributed by one character."""
    if char.isspace() or char.isalpha() and not _is_wide(char):
        return 0, 1
    if _is_wide(char) or char.isdigit():
        return 1, 0  # CJK chars and digits tokenize ~1:1 (Gemma and Qwen split digits)
    if _is_symbol(char):
        return 3, 0  # emoji / pictographs: several byte-level tokens
    return 1, 0  # punctuation, currency, combining marks, ZWJ, variation selectors


class _Budget:
    __slots__ = ("plain", "whole")

    def __init__(self) -> None:
        self.plain = 0
        self.whole = 0

    def add(self, text: str) -> None:
        for char in text:
            whole, plain = _char_cost(char)
            self.whole += whole
            self.plain += plain

    def tokens_with(self, text: str) -> int:
        whole, plain = self.whole, self.plain
        for char in text:
            w, p = _char_cost(char)
            whole += w
            plain += p
        return whole + math.ceil(plain / CHARS_PER_TOKEN)


def estimate_tokens(text: str) -> int:
    """Conservative token estimate: letters and spaces at 3 chars/token; digits, CJK and
    punctuation 1 token each; emoji 3. Calibrated against llama-server `/tokenize` for
    EmbeddingGemma 2 and Qwen3 in the Stage 23 spike (`research/embedding-models-2026.md`)."""
    return _Budget().tokens_with(text) if text else 0


_SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+|\n+")
_WORD_RE = re.compile(r"\S+\s*")


def _split_units(text: str, max_tokens: int) -> Iterator[str]:
    """Yield sentence-ish units ≤ `max_tokens`; hard-split by words, then by characters
    (long tokens, CJK without spaces). Lazy, so the chunk cap stops the work early."""
    for raw in _SENTENCE_RE.split(text):
        piece = raw.strip()
        if not piece:
            continue
        if estimate_tokens(piece) <= max_tokens:
            yield piece
            continue
        current, budget = "", _Budget()
        for match in _WORD_RE.finditer(piece):
            word = match.group(0)
            if budget.tokens_with(word.rstrip()) <= max_tokens:
                current += word
                budget.add(word)
                continue
            if current.strip():
                yield current.strip()
            current, budget = "", _Budget()
            for char in word:
                if budget.tokens_with(char) > max_tokens:
                    if current.strip():
                        yield current.strip()
                    current, budget = "", _Budget()
                current += char
                budget.add(char)
        if current.strip():
            yield current.strip()


def chunk_pages(
    pages: Sequence[str],
    *,
    max_tokens: int = DEFAULT_CHUNK_TOKENS,
    max_chunks: int = MAX_CHUNKS_PER_ASSET,
) -> tuple[TextChunk, ...]:
    """Pack text into ≤ `max_tokens` windows, first pages first, capped at `max_chunks`.

    Windows never span pages, so a chunk maps to one page. Empty input → no chunks.
    """
    if max_tokens <= 0 or max_chunks <= 0:
        raise ValueError("max_tokens and max_chunks must be positive")
    chunks: list[TextChunk] = []
    single = len(pages) == 1
    for page_index, page in enumerate(pages):
        # Never look past what the chunk cap can hold (x2 slack for window-edge waste).
        limit = max_chunks * max_tokens * CHARS_PER_TOKEN * 2
        normalized = unicodedata.normalize("NFC", (page or "")[:limit])
        current: list[str] = []

        def flush() -> None:
            nonlocal current
            if current:
                text = " ".join(current)
                chunks.append(
                    TextChunk(
                        chunk_no=len(chunks),
                        text=text,
                        page=None if single else page_index + 1,
                        estimated_tokens=estimate_tokens(text),
                    )
                )
            current = []

        for unit in _split_units(normalized, max_tokens):
            if current and estimate_tokens(" ".join([*current, unit])) > max_tokens:
                flush()
                if len(chunks) >= max_chunks:
                    return tuple(chunks)
            current.append(unit)
        flush()
        if len(chunks) >= max_chunks:
            return tuple(chunks[:max_chunks])
    return tuple(chunks)


def chunk_text(
    text: str, *, max_tokens: int = DEFAULT_CHUNK_TOKENS, max_chunks: int = MAX_CHUNKS_PER_ASSET
) -> tuple[TextChunk, ...]:
    return chunk_pages([text], max_tokens=max_tokens, max_chunks=max_chunks)


def batched(items: Sequence[str], size: int = EMBEDDING_BATCH_SIZE) -> tuple[tuple[str, ...], ...]:
    if size <= 0:
        raise ValueError("size must be positive")
    return tuple(tuple(items[i : i + size]) for i in range(0, len(items), size))


# --------------------------------------------------------------------------------------
# Activation state machine


class SmartSearchState(StrEnum):
    OFF = "off"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    VERIFYING = "verifying"
    STARTING = "starting"
    INDEXING = "indexing"
    READY = "ready"
    ERROR = "error"


class SmartSearchErrorCode(StrEnum):
    DOWNLOAD = "download"
    CHECKSUM = "checksum"
    SPACE = "space"
    RUNTIME = "runtime"


class SmartSearchEventKind(StrEnum):
    ACTIVATE = "activate"
    PAUSE = "pause"
    RESUME = "resume"
    NETWORK_LOST = "network_lost"
    NETWORK_RESTORED = "network_restored"
    DOWNLOADED = "downloaded"
    VERIFIED = "verified"
    RUNTIME_READY = "runtime_ready"
    INDEXED = "indexed"
    BACKLOG = "backlog"
    FAIL = "fail"
    RETRY = "retry"
    CANCEL = "cancel"
    REMOVE = "remove"


BACKLOG_REINDEX_THRESHOLD = 50

# Error codes each step may fail with. `ready` can only lose its runtime.
_FAILABLE: dict[SmartSearchState, frozenset[SmartSearchErrorCode]] = {
    SmartSearchState.DOWNLOADING: frozenset({SmartSearchErrorCode.DOWNLOAD, SmartSearchErrorCode.SPACE}),
    SmartSearchState.VERIFYING: frozenset({SmartSearchErrorCode.CHECKSUM}),
    SmartSearchState.STARTING: frozenset({SmartSearchErrorCode.RUNTIME}),
    SmartSearchState.INDEXING: frozenset({SmartSearchErrorCode.RUNTIME}),
    SmartSearchState.READY: frozenset({SmartSearchErrorCode.RUNTIME}),
}

_CANCELLABLE = frozenset(
    {
        SmartSearchState.DOWNLOADING,
        SmartSearchState.PAUSED,
        SmartSearchState.VERIFYING,
        SmartSearchState.STARTING,
        SmartSearchState.ERROR,
    }
)


@dataclass(frozen=True, slots=True)
class SmartSearchEvent:
    kind: SmartSearchEventKind
    error_code: SmartSearchErrorCode | None = None
    backlog: int = 0
    bytes_total: int = 0
    space_id: str | None = None


@dataclass(frozen=True, slots=True)
class SmartSearchStatus:
    state: SmartSearchState = SmartSearchState.OFF
    space_id: str | None = None
    bytes_done: int = 0
    bytes_total: int = 0
    waiting_network: bool = False
    indexed_done: int = 0
    indexed_total: int = 0
    error_code: SmartSearchErrorCode | None = None
    failed_step: SmartSearchState | None = None
    # Set when `ready` lost its runtime: after the restart it returns to `ready`, not `indexing`.
    was_ready: bool = False

    def __post_init__(self) -> None:
        if (self.state is SmartSearchState.ERROR) != (self.error_code is not None):
            raise SmartSearchError("invalid_status", "error_code is set exactly when state is error")
        if self.waiting_network and self.state is not SmartSearchState.DOWNLOADING:
            raise SmartSearchError("invalid_status", "waiting_network is a sub-state of downloading")
        if self.bytes_done < 0 or self.indexed_done < 0:
            raise SmartSearchError("invalid_status", "progress counters cannot be negative")

    @property
    def search_available(self) -> bool:
        """Vector search serves queries only once the space is ready (or re-indexing it)."""
        return self.state in {SmartSearchState.READY, SmartSearchState.INDEXING}

    def legacy_embeddings_state(self) -> IndexProviderState:
        """Fold into the pre-Stage-24 `embeddings_state` field for old clients."""
        return {
            SmartSearchState.OFF: IndexProviderState.DISABLED,
            SmartSearchState.READY: IndexProviderState.READY,
            SmartSearchState.ERROR: IndexProviderState.FAILED,
        }.get(self.state, IndexProviderState.PENDING)


def transition(status: SmartSearchStatus, event: SmartSearchEvent) -> SmartSearchStatus:
    """The single source of truth for legal smart search transitions.

    Raises `IllegalSmartSearchTransitionError` for anything not listed in the contract.
    """
    state, kind = status.state, event.kind
    illegal = IllegalSmartSearchTransitionError(state, kind)

    if kind is SmartSearchEventKind.ACTIVATE:
        if state is not SmartSearchState.OFF:
            raise illegal
        return SmartSearchStatus(
            state=SmartSearchState.DOWNLOADING, space_id=event.space_id, bytes_total=event.bytes_total
        )
    if kind is SmartSearchEventKind.PAUSE:
        if state is not SmartSearchState.DOWNLOADING:
            raise illegal
        return replace(status, state=SmartSearchState.PAUSED, waiting_network=False)
    if kind is SmartSearchEventKind.RESUME:
        if state is not SmartSearchState.PAUSED:
            raise illegal
        return replace(status, state=SmartSearchState.DOWNLOADING)
    if kind in {SmartSearchEventKind.NETWORK_LOST, SmartSearchEventKind.NETWORK_RESTORED}:
        if state is not SmartSearchState.DOWNLOADING:
            raise illegal
        return replace(status, waiting_network=kind is SmartSearchEventKind.NETWORK_LOST)
    if kind is SmartSearchEventKind.DOWNLOADED:
        if state is not SmartSearchState.DOWNLOADING:
            raise illegal
        return replace(
            status, state=SmartSearchState.VERIFYING, waiting_network=False, bytes_done=status.bytes_total
        )
    if kind is SmartSearchEventKind.VERIFIED:
        if state is not SmartSearchState.VERIFYING:
            raise illegal
        return replace(status, state=SmartSearchState.STARTING)
    if kind is SmartSearchEventKind.RUNTIME_READY:
        if state is not SmartSearchState.STARTING:
            raise illegal
        target = SmartSearchState.READY if status.was_ready else SmartSearchState.INDEXING
        return replace(status, state=target, was_ready=False)
    if kind is SmartSearchEventKind.INDEXED:
        if state is not SmartSearchState.INDEXING:
            raise illegal
        return replace(status, state=SmartSearchState.READY, indexed_done=status.indexed_total)
    if kind is SmartSearchEventKind.BACKLOG:
        if state is not SmartSearchState.READY:
            raise illegal
        if event.backlog <= BACKLOG_REINDEX_THRESHOLD:
            return status
        return replace(status, state=SmartSearchState.INDEXING, indexed_done=0, indexed_total=event.backlog)
    if kind is SmartSearchEventKind.FAIL:
        allowed = _FAILABLE.get(state)
        if allowed is None or event.error_code not in allowed:
            raise illegal
        failed_step = SmartSearchState.STARTING if state is SmartSearchState.READY else state
        return replace(
            status,
            state=SmartSearchState.ERROR,
            error_code=event.error_code,
            failed_step=failed_step,
            waiting_network=False,
            was_ready=state is SmartSearchState.READY,
        )
    if kind is SmartSearchEventKind.RETRY:
        if state is not SmartSearchState.ERROR or status.failed_step is None:
            raise illegal
        if status.error_code is SmartSearchErrorCode.CHECKSUM:
            # The bad file was deleted: download again from zero.
            return replace(
                status, state=SmartSearchState.DOWNLOADING, error_code=None, failed_step=None, bytes_done=0
            )
        return replace(status, state=status.failed_step, error_code=None, failed_step=None)
    if kind is SmartSearchEventKind.CANCEL:
        if state not in _CANCELLABLE:
            raise illegal
        return SmartSearchStatus()
    if kind is SmartSearchEventKind.REMOVE:
        if state is SmartSearchState.OFF:
            raise illegal
        return SmartSearchStatus()
    raise illegal  # pragma: no cover - exhaustive over SmartSearchEventKind


def with_download_progress(status: SmartSearchStatus, bytes_done: int) -> SmartSearchStatus:
    if status.state not in {SmartSearchState.DOWNLOADING, SmartSearchState.PAUSED}:
        raise SmartSearchError("invalid_progress", "Download progress outside the download step")
    return replace(status, bytes_done=max(0, min(bytes_done, status.bytes_total or bytes_done)))


def with_index_progress(status: SmartSearchStatus, done: int, total: int) -> SmartSearchStatus:
    if status.state is not SmartSearchState.INDEXING:
        raise SmartSearchError("invalid_progress", "Index progress outside the indexing step")
    total = max(0, total)
    return replace(status, indexed_done=max(0, min(done, total)), indexed_total=total)


# --------------------------------------------------------------------------------------
# Settings migration and onboarding (contracts for Stage 24/25)

EMBEDDINGS_PROVIDER_CHOICES = ("disabled", "managed", "custom", "mock")
ONBOARDING_MIN_CORES = 4
ONBOARDING_MIN_RAM_BYTES = 8 * 1024**3


def migrate_embeddings_provider(provider: str, custom_model_exists: bool) -> str:
    """`0009_smart_search` rewrite: `jina` → `custom` when its model file exists, else `disabled`."""
    if provider == "jina":
        return "custom" if custom_model_exists else "disabled"
    if provider in EMBEDDINGS_PROVIDER_CHOICES:
        return provider
    return "disabled"


def follows_smart_search_status(configured_provider: str, *, locked: bool, offered: Sequence[str]) -> bool:
    """Whether a running process should follow the persisted smart search status instead of the provider it
    started with: activation (`disabled` → `managed`) and removal (`managed` → `disabled`) then take effect with
    no restart. Not when the environment pins `disabled`, when `managed` is not offered on the platform, or for
    `custom`/`mock`, which keep their own wiring."""
    if "managed" not in offered:
        return False
    return configured_provider == "managed" or (configured_provider == "disabled" and not locked)


def suggest_in_onboarding(cpu_cores: int, ram_bytes: int) -> bool:
    """D8: onboarding offers smart search on capable machines; it is never enabled
    without the person's explicit consent (the activation sheet)."""
    return cpu_cores >= ONBOARDING_MIN_CORES and ram_bytes >= ONBOARDING_MIN_RAM_BYTES


def default_embedding_threads(cpu_cores: int) -> int:
    return min(4, max(1, cpu_cores // 2))
