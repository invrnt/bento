"""Vector index over embedding spaces (`orchestration/api/smart-search-contract.md` §Embedding spaces).

Storage:
- `asset_embedding_chunks(space_id, asset_id, chunk_no, page, vector, created_at)` holds every vector (float32,
  little endian). It is the source of truth in both modes.
- `asset_embeddings` keeps one metadata row per (space, asset).
- With the sqlite-vec extension, each searchable space also has a `vec0` table `asset_embedding_vec_<hash8>`
  (created here, at runtime, because the dimension is part of the DDL). `asset_embedding_vec_rows` maps its
  rowids to chunks; `AUTOINCREMENT` keeps rowids from ever being reused. The table mirrors the chunks of its
  space and is rebuilt from them whenever the two disagree.
- `embedding_spaces` registers managed spaces (`building | active | retired`); at most one is active.

Search always runs inside exactly one space, and an asset's score is the best score among its chunks. Without the
extension (Docker dev, Android, a failed load) the same top-k comes from an exact scan of the chunk rows.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import DateTime, bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from bento.application.smart_search.reembed import EmbeddingSpaceState
from bento.domain.indexing import EmbeddingRecord
from bento.domain.smart_search import (
    LEGACY_SPACE_PREFIX,
    MAX_CHUNKS_PER_ASSET,
    EmbeddingSpace,
    InvalidEmbeddingSpaceError,
    best_chunk_scores,
    legacy_space_id,
    parse_space_id,
)
from bento.infrastructure.db.engine import session_scope
from bento.ports.repositories import ClockPort

LOGGER = logging.getLogger("bento.search.vectors")

Vector = tuple[float, ...]

CHUNKS_TABLE = "asset_embedding_chunks"
ROWS_TABLE = "asset_embedding_vec_rows"
SPACES_TABLE = "embedding_spaces"
VEC_TABLE_PREFIX = "asset_embedding_vec_"
UNKNOWN_PEER_PROVIDER_PREFIX = "unknown."
MAX_SEARCH_LIMIT = 100
_KNN_MAX = 4096  # sqlite-vec's default upper bound for `k`
_LEGACY_FALLBACK_TABLE = "asset_embedding_vectors_fallback"
_LEGACY_MAP_TABLE = "asset_embedding_vector_map"
_LEGACY_VEC_TABLE = "asset_embedding_vec"
_TIMESTAMP = DateTime(timezone=True)


class ChunkVectorLike(Protocol):
    """`application.indexing.embedding.ChunkVector`, structurally (adapters do not import application DTOs)."""

    @property
    def chunk_no(self) -> int: ...

    @property
    def page(self) -> int | None: ...

    @property
    def vector(self) -> Sequence[float]: ...


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    asset_id: str
    embedding_id: str
    provider: str
    distance: float
    score: float
    space_id: str = ""
    chunk_no: int = 0


@dataclass(frozen=True, slots=True)
class StoredChunk:
    chunk_no: int
    page: int | None
    vector: bytes


@dataclass(frozen=True, slots=True)
class StoredEmbedding:
    """One asset's vectors in one space, as stored (raw float32 blobs)."""

    space_id: str
    asset_id: str
    provider: str
    dimensions: int
    chunks: tuple[StoredChunk, ...]


@dataclass(frozen=True, slots=True)
class SpaceRecord:
    id: str
    state: EmbeddingSpaceState
    dims: int


def vec_table_name(space_id: str) -> str:
    return f"{VEC_TABLE_PREFIX}{hashlib.sha256(space_id.encode('utf-8')).hexdigest()[:8]}"


def unknown_peer_space_id(provider: str, dims: int) -> str:
    """Where vectors from peers that send no (or a malformed) `space` are kept: never searched."""
    return legacy_space_id(f"{UNKNOWN_PEER_PROVIDER_PREFIX}{provider or 'unknown'}", dims)


def is_unknown_peer_space(space_id: str) -> bool:
    return space_id.startswith(f"{LEGACY_SPACE_PREFIX}{UNKNOWN_PEER_PROVIDER_PREFIX}")


def space_dims(space_id: str) -> int:
    return parse_space_id(space_id)[2]


class SQLiteVecSearchIndex:
    """Space-aware vector index. Also the `embedding_spaces` registry, so the blue/green flip is one transaction.

    `space_id` is the default space for writes and searches that name none; without it, writes go to the
    record's legacy space (`legacy:<provider>/<dims>`). `dimensions` is kept for older callers only.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        clock: ClockPort,
        *,
        dimensions: int | None = None,
        space_id: str | None = None,
        allow_fallback: bool = True,
        prefer_sqlite_vec: bool = True,
    ) -> None:
        if dimensions is not None and dimensions < 1:
            raise ValueError("dimensions must be positive")
        if space_id is not None:
            parse_space_id(space_id)
        self._session_factory = session_factory
        self._clock = clock
        self._dimensions = dimensions
        self._space_id = space_id
        self._allow_fallback = allow_fallback
        self._prefer_sqlite_vec = prefer_sqlite_vec
        self._initialized = False
        self._using_sqlite_vec = False
        self._verified_spaces: set[str] = set()

    @property
    def using_sqlite_vec(self) -> bool:
        return self._using_sqlite_vec

    async def initialize(self) -> None:
        if self._initialized:
            return
        with session_scope(self._session_factory) as session:
            self._using_sqlite_vec = self._prefer_sqlite_vec and _load_sqlite_vec(session)
            if not self._using_sqlite_vec and not self._allow_fallback:
                raise RuntimeError("sqlite-vec extension is unavailable")
            _create_rows_table(session)
            _import_legacy_vectors(session)
        _drop_legacy_vec_table(self._session_factory)
        self._initialized = True

    # Writes

    async def index_embedding(self, record: EmbeddingRecord, *, space_id: str | None = None) -> None:
        """Metadata only (no vector): the asset has an embedding row in the space."""
        await self.initialize()
        space = self._write_space(record, space_id)
        with session_scope(self._session_factory) as session:
            _persist_metadata(session, space, record, self._clock.now())

    async def index_embedding_vector(
        self, record: EmbeddingRecord, vector: Vector, *, space_id: str | None = None
    ) -> None:
        """One vector for the asset (a single chunk), replacing its earlier vectors in that space."""
        await self.index_chunks(record, (vector,), space_id=space_id)

    async def index_chunks(
        self,
        record: EmbeddingRecord,
        vectors: Sequence[Vector],
        *,
        space_id: str | None = None,
        pages: Sequence[int | None] | None = None,
        searchable: bool = True,
    ) -> None:
        """Replace the asset's chunk vectors in a space (at most `MAX_CHUNKS_PER_ASSET`, first chunks first).

        `searchable=False` stores the vectors without building a search table for the space (peer vectors from
        another space); an existing table still mirrors them so it never goes stale.
        """
        space = self._write_space(record, space_id)
        dims = space_dims(space)
        if record.dimensions != dims:
            raise ValueError("record dimensions do not match the embedding space")
        kept = tuple(vectors[:MAX_CHUNKS_PER_ASSET])
        for vector in kept:
            _validate_vector(vector, dims)
        chunk_pages = tuple(pages[: len(kept)]) if pages is not None else ()
        await self.initialize()
        now = self._clock.now()
        with session_scope(self._session_factory) as session:
            vec_ready = self._vec_table_for_write(session, space, create=searchable)
            _persist_metadata(session, space, record, now)
            _delete_asset_chunks(session, space, record.asset_id, vec_ready=vec_ready)
            if not kept:
                return
            rows = [
                {
                    "space_id": space,
                    "asset_id": record.asset_id,
                    "chunk_no": chunk_no,
                    "page": chunk_pages[chunk_no] if chunk_no < len(chunk_pages) else None,
                    "vector": pack_vector(vector),
                    "created_at": now,
                }
                for chunk_no, vector in enumerate(kept)
            ]
            session.execute(
                text(
                    f"""
                    INSERT INTO {CHUNKS_TABLE} (space_id, asset_id, chunk_no, page, vector, created_at)
                    VALUES (:space_id, :asset_id, :chunk_no, :page, :vector, :created_at)
                    """
                ).bindparams(bindparam("created_at", type_=_TIMESTAMP)),
                rows,
            )
            if vec_ready:
                _insert_vec_rows(session, space, record.asset_id, [(row["chunk_no"], row["vector"]) for row in rows])

    async def index_chunk_vectors(
        self, space_id: str, record: EmbeddingRecord, chunks: Sequence[ChunkVectorLike]
    ) -> None:
        """`ChunkVectorIndexPort` (`application/indexing/embedding.py`): the asset's chunks in `space_id`, in
        `chunk_no` order, replacing its earlier ones there. Chunk numbers are stored densely from 0."""
        ordered = sorted(chunks, key=lambda chunk: chunk.chunk_no)
        await self.index_chunks(
            record,
            [tuple(chunk.vector) for chunk in ordered],
            space_id=space_id,
            pages=[chunk.page for chunk in ordered],
        )

    async def remove_asset(self, asset_id: str, *, space_id: str | None = None) -> None:
        """Remove the asset's vectors from one space, or from every space."""
        await self.initialize()
        with session_scope(self._session_factory) as session:
            spaces = [space_id] if space_id is not None else _asset_spaces(session, asset_id)
            for space in spaces:
                vec_ready = _vec_table_exists(session, space) and _load_sqlite_vec(session)
                _delete_asset_chunks(session, space, asset_id, vec_ready=vec_ready)
                session.execute(
                    text("DELETE FROM asset_embeddings WHERE space_id = :space_id AND asset_id = :asset_id"),
                    {"space_id": space, "asset_id": asset_id},
                )
            if space_id is None:
                session.execute(text("DELETE FROM asset_embeddings WHERE asset_id = :asset_id"), {"asset_id": asset_id})
                session.execute(text(f"DELETE FROM {ROWS_TABLE} WHERE asset_id = :asset_id"), {"asset_id": asset_id})

    async def drop_space(self, space_id: str) -> None:
        """Delete every vector, metadata row and the search table of a space."""
        await self.initialize()
        with session_scope(self._session_factory) as session:
            _drop_space_rows(session, space_id)
        self._verified_spaces.discard(space_id)

    async def retire_space(self, space_id: str) -> None:
        """Smart search was removed or cancelled: drop the space's vectors and search table and mark it
        `retired`, so search falls back to text and a later activation starts it again as `building`."""
        await self.initialize()
        with session_scope(self._session_factory) as session:
            _drop_space_rows(session, space_id)
            session.execute(
                text(f"UPDATE {SPACES_TABLE} SET state = :retired WHERE id = :id"),
                {"retired": EmbeddingSpaceState.RETIRED.value, "id": space_id},
            )
        self._verified_spaces.discard(space_id)

    async def registered_space_ids(self, *, include_retired: bool = False) -> tuple[str, ...]:
        """The managed spaces in `embedding_spaces` (`building` and `active`, plus `retired` when asked)."""
        with session_scope(self._session_factory) as session:
            rows = session.execute(text(f"SELECT id, state FROM {SPACES_TABLE} ORDER BY created_at, id")).all()
        return tuple(
            str(space_id)
            for space_id, state in rows
            if include_retired or state != EmbeddingSpaceState.RETIRED.value
        )

    async def rebuild_space_index(self, space_id: str) -> bool:
        """Build (or repair) the space's `vec0` table from its chunks. False when sqlite-vec is not in use."""
        await self.initialize()
        if not self._using_sqlite_vec:
            return False
        with session_scope(self._session_factory) as session:
            return self._ensure_vec_table(session, space_id)

    # Reads

    async def search_vectors(
        self,
        vector: Vector,
        *,
        limit: int = 50,
        provider: str | None = None,
        space_id: str | None = None,
    ) -> tuple[VectorSearchHit, ...]:
        """Top `limit` assets of one space by their best chunk (L2 on unit vectors ranks like the dot product)."""
        await self.initialize()
        limit = max(min(limit, MAX_SEARCH_LIMIT), 1)
        with session_scope(self._session_factory) as session:
            space = self._search_space(session, vector, provider=provider, space_id=space_id)
            if space is None:
                return ()
            _validate_vector(vector, space_dims(space))
            if self._using_sqlite_vec and _has_vectors(session, space) and self._ensure_vec_table(session, space):
                distances = _sqlite_vec_distances(session, space, vector, limit=limit)
            else:
                distances = _fallback_distances(session, space, vector)
            return _top_hits(session, space, distances, limit=limit)

    async def assets_with_vectors(self, space_id: str, asset_ids: Sequence[str]) -> frozenset[str]:
        if not asset_ids:
            return frozenset()
        await self.initialize()
        with session_scope(self._session_factory) as session:
            rows = session.execute(
                text(
                    f"SELECT DISTINCT asset_id FROM {CHUNKS_TABLE} WHERE space_id = :space_id AND asset_id IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {"space_id": space_id, "ids": list(asset_ids)},
            ).scalars()
            return frozenset(str(asset_id) for asset_id in rows)

    async def count_assets(self, space_id: str) -> int:
        await self.initialize()
        with session_scope(self._session_factory) as session:
            value = session.execute(
                text(f"SELECT COUNT(DISTINCT asset_id) FROM {CHUNKS_TABLE} WHERE space_id = :space_id"),
                {"space_id": space_id},
            ).scalar()
            return int(value or 0)

    # Space registry

    async def active_space_id(self) -> str | None:
        with session_scope(self._session_factory) as session:
            return active_space_id(session)

    async def get_space(self, space_id: str) -> SpaceRecord | None:
        with session_scope(self._session_factory) as session:
            row = (
                session.execute(text(f"SELECT id, state, dims FROM {SPACES_TABLE} WHERE id = :id"), {"id": space_id})
                .mappings()
                .first()
            )
            if row is None:
                return None
            return SpaceRecord(id=str(row["id"]), state=EmbeddingSpaceState(str(row["state"])), dims=int(row["dims"]))

    async def space_state(self, space_id: str) -> EmbeddingSpaceState | None:
        record = await self.get_space(space_id)
        return record.state if record is not None else None

    async def register_space(
        self, space: EmbeddingSpace, *, state: EmbeddingSpaceState = EmbeddingSpaceState.BUILDING
    ) -> None:
        """Add the space if it is new. A retired space comes back as `building`; an active one stays active."""
        if state is EmbeddingSpaceState.ACTIVE:
            raise ValueError("Spaces become active only through activate_space()")
        now = self._clock.now()
        with session_scope(self._session_factory) as session:
            existing = session.execute(text(f"SELECT state FROM {SPACES_TABLE} WHERE id = :id"), {"id": space.id}).scalar()
            if existing is None:
                session.execute(
                    text(
                        f"""
                        INSERT INTO {SPACES_TABLE} (id, model_id, revision, dims, modalities, state, created_at, activated_at)
                        VALUES (:id, :model_id, :revision, :dims, :modalities, :state, :created_at, NULL)
                        """
                    ).bindparams(bindparam("created_at", type_=_TIMESTAMP)),
                    {
                        "id": space.id,
                        "model_id": space.model_id,
                        "revision": space.revision,
                        "dims": space.dims,
                        "modalities": json.dumps(sorted(modality.value for modality in space.modalities)),
                        "state": state.value,
                        "created_at": now,
                    },
                )
            elif existing == EmbeddingSpaceState.RETIRED.value:
                session.execute(
                    text(f"UPDATE {SPACES_TABLE} SET state = :state WHERE id = :id"),
                    {"id": space.id, "state": state.value},
                )

    async def activate_space(self, space_id: str) -> tuple[str, ...]:
        """The blue/green flip, in one transaction: the space becomes the only active one, the previous active
        space is retired and its vectors, metadata and search table are dropped. Activating a managed space
        also drops the legacy (pre-Stage-24) vectors. Returns the dropped space ids."""
        await self.initialize()
        now = self._clock.now()
        with session_scope(self._session_factory) as session:
            state = session.execute(text(f"SELECT state FROM {SPACES_TABLE} WHERE id = :id"), {"id": space_id}).scalar()
            if state is None:
                raise InvalidEmbeddingSpaceError("Unknown embedding space", {"space_id": space_id})
            if state == EmbeddingSpaceState.ACTIVE.value:
                return ()
            previous = [
                str(value)
                for value in session.execute(
                    text(f"SELECT id FROM {SPACES_TABLE} WHERE state = :active AND id != :id"),
                    {"active": EmbeddingSpaceState.ACTIVE.value, "id": space_id},
                ).scalars()
            ]
            session.execute(
                text(f"UPDATE {SPACES_TABLE} SET state = :retired WHERE state = :active AND id != :id"),
                {"retired": EmbeddingSpaceState.RETIRED.value, "active": EmbeddingSpaceState.ACTIVE.value, "id": space_id},
            )
            session.execute(
                text(f"UPDATE {SPACES_TABLE} SET state = :active, activated_at = :now WHERE id = :id").bindparams(
                    bindparam("now", type_=_TIMESTAMP)
                ),
                {"active": EmbeddingSpaceState.ACTIVE.value, "now": now, "id": space_id},
            )
            dropped = list(previous)
            if not space_id.startswith(LEGACY_SPACE_PREFIX):
                dropped.extend(space for space in _stored_spaces(session) if space.startswith(LEGACY_SPACE_PREFIX))
            for space in dict.fromkeys(dropped):
                _drop_space_rows(session, space)
        for space in dropped:
            self._verified_spaces.discard(space)
        return tuple(dict.fromkeys(dropped))

    # Internals

    def _write_space(self, record: EmbeddingRecord, space_id: str | None) -> str:
        space = space_id or self._space_id or legacy_space_id(record.provider, record.dimensions)
        parse_space_id(space)
        return space

    def _search_space(
        self, session: Session, vector: Vector, *, provider: str | None, space_id: str | None
    ) -> str | None:
        if space_id is not None:
            return space_id
        if provider is not None:
            return legacy_space_id(provider, len(vector))
        if self._space_id is not None:
            return self._space_id
        active = active_space_id(session)
        if active is not None and space_dims(active) == len(vector):
            return active
        # Callers from before embedding spaces: the space this device wrote last with these dimensions.
        return _latest_local_space(session, len(vector))

    def _vec_table_for_write(self, session: Session, space_id: str, *, create: bool) -> bool:
        """Whether the write must also update the space's `vec0` table (creating it when `create`)."""
        if not self._using_sqlite_vec:
            # Keep a table written by a process that has the extension in step, when this connection can load it.
            return _vec_table_exists(session, space_id) and _load_sqlite_vec(session)
        if create:
            return self._ensure_vec_table(session, space_id)
        return _vec_table_exists(session, space_id) and self._ensure_vec_table(session, space_id)

    def _ensure_vec_table(self, session: Session, space_id: str) -> bool:
        """Create the space's `vec0` table, or rebuild it when it disagrees with the chunk rows."""
        if not _load_sqlite_vec(session):
            return False
        name = vec_table_name(space_id)
        dims = space_dims(space_id)
        if not _vec_table_exists(session, space_id):
            session.execute(text(f"DELETE FROM {ROWS_TABLE} WHERE space_id = :space_id"), {"space_id": space_id})
            session.execute(text(f"CREATE VIRTUAL TABLE IF NOT EXISTS {name} USING vec0(embedding float[{dims}])"))
            _fill_vec_table(session, space_id, dims)
            self._verified_spaces.add(space_id)
            return True
        if space_id in self._verified_spaces:
            return True
        if not _vec_table_consistent(session, space_id):
            LOGGER.info("Rebuilding a vector search table from its stored chunks")
            session.execute(text(f"DROP TABLE {name}"))
            session.execute(text(f"DELETE FROM {ROWS_TABLE} WHERE space_id = :space_id"), {"space_id": space_id})
            session.execute(text(f"CREATE VIRTUAL TABLE {name} USING vec0(embedding float[{dims}])"))
            _fill_vec_table(session, space_id, dims)
        self._verified_spaces.add(space_id)
        return True


# Registry helpers (also used by the sync read-back, which runs inside the caller's session)


def active_space_id(session: Session) -> str | None:
    value = session.execute(
        text(f"SELECT id FROM {SPACES_TABLE} WHERE state = :active ORDER BY activated_at DESC, id LIMIT 1"),
        {"active": EmbeddingSpaceState.ACTIVE.value},
    ).scalar()
    return str(value) if value is not None else None


def stored_embeddings(session: Session, asset_ids: Sequence[str]) -> dict[str, list[StoredEmbedding]]:
    if not asset_ids:
        return {}
    metadata = session.execute(
        text(
            """
            SELECT space_id, asset_id, provider, dimensions
            FROM asset_embeddings
            WHERE asset_id IN :ids
            ORDER BY asset_id, created_at DESC, id DESC
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": list(asset_ids)},
    ).mappings()
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    order: dict[str, list[str]] = {}
    for row in metadata:
        key = (str(row["space_id"]), str(row["asset_id"]))
        if key in rows:
            continue
        rows[key] = dict(row)
        order.setdefault(key[1], []).append(key[0])
    chunks: dict[tuple[str, str], list[StoredChunk]] = {}
    for row in session.execute(
        text(
            f"""
            SELECT space_id, asset_id, chunk_no, page, vector
            FROM {CHUNKS_TABLE}
            WHERE asset_id IN :ids
            ORDER BY asset_id, space_id, chunk_no
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": list(asset_ids)},
    ).mappings():
        page = row["page"]
        chunks.setdefault((str(row["space_id"]), str(row["asset_id"])), []).append(
            StoredChunk(chunk_no=int(row["chunk_no"]), page=int(page) if page is not None else None, vector=bytes(row["vector"]))
        )
    result: dict[str, list[StoredEmbedding]] = {}
    for asset_id, spaces in order.items():
        for space in spaces:
            stored = chunks.get((space, asset_id))
            if not stored:
                continue
            meta = rows[(space, asset_id)]
            dims = int(meta["dimensions"])
            valid = tuple(chunk for chunk in stored if len(chunk.vector) == dims * 4)
            if not valid:
                continue
            result.setdefault(asset_id, []).append(
                StoredEmbedding(space_id=space, asset_id=asset_id, provider=str(meta["provider"]), dimensions=dims, chunks=valid)
            )
    return result


# Extension loading


def _load_sqlite_vec(session: Session) -> bool:
    """Load sqlite-vec on the session's connection (once per connection). False when it is missing or fails."""
    connection = _dbapi_connection(session)
    try:
        connection.execute("SELECT vec_version()").fetchone()
        return True
    except sqlite3.Error:
        pass
    try:
        import sqlite_vec  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError:
        return False
    try:
        connection.enable_load_extension(True)
        try:
            sqlite_vec.load(connection)
        finally:
            connection.enable_load_extension(False)
        connection.execute("SELECT vec_version()").fetchone()
    except (AttributeError, OSError, sqlite3.Error):
        return False
    return True


def _dbapi_connection(session: Session) -> sqlite3.Connection:
    connection = session.connection().connection
    driver_connection = getattr(connection, "driver_connection", None)
    if driver_connection is not None:
        return driver_connection  # type: ignore[no-any-return]
    dbapi_connection = getattr(connection, "dbapi_connection", None)
    if dbapi_connection is not None:
        return dbapi_connection  # type: ignore[no-any-return]
    return connection  # type: ignore[return-value]


# Tables


def _table_exists(session: Session, name: str) -> bool:
    return (
        session.execute(text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name"), {"name": name}).scalar()
        is not None
    )


def _vec_table_exists(session: Session, space_id: str) -> bool:
    return _table_exists(session, vec_table_name(space_id))


def _has_vectors(session: Session, space_id: str) -> bool:
    """Whether the space has chunks (an empty or retired space gets no search table)."""
    return (
        session.execute(text(f"SELECT 1 FROM {CHUNKS_TABLE} WHERE space_id = :space_id LIMIT 1"), {"space_id": space_id}).scalar()
        is not None
    )


def _create_rows_table(session: Session) -> None:
    session.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {ROWS_TABLE} (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                space_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                chunk_no INTEGER NOT NULL,
                UNIQUE (space_id, asset_id, chunk_no)
            )
            """
        )
    )
    session.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{ROWS_TABLE}_asset ON {ROWS_TABLE}(asset_id)"))


def _import_legacy_vectors(session: Session) -> None:
    """Move pre-Stage-24 vectors (`asset_embedding_vectors_fallback`) into chunk 0 of their legacy space."""
    if not _table_exists(session, _LEGACY_FALLBACK_TABLE):
        return
    session.execute(
        text(
            f"""
            INSERT OR IGNORE INTO {CHUNKS_TABLE} (space_id, asset_id, chunk_no, page, vector, created_at)
            SELECT e.space_id, e.asset_id, 0, NULL, f.vector, e.created_at
            FROM {_LEGACY_FALLBACK_TABLE} AS f
            JOIN asset_embeddings AS e ON e.id = f.embedding_id
            WHERE length(f.vector) = e.dimensions * 4
            """
        )
    )
    session.execute(text(f"DROP TABLE {_LEGACY_FALLBACK_TABLE}"))
    session.execute(text(f"DROP TABLE IF EXISTS {_LEGACY_MAP_TABLE}"))
    LOGGER.info("Moved legacy embedding vectors into their legacy embedding space")


def _drop_legacy_vec_table(session_factory: sessionmaker[Session]) -> None:
    """The pre-Stage-24 `vec0` table was never filled (the extension never loaded); drop it when possible."""
    try:
        with session_scope(session_factory) as session:
            if _table_exists(session, _LEGACY_VEC_TABLE) and _load_sqlite_vec(session):
                session.execute(text(f"DROP TABLE {_LEGACY_VEC_TABLE}"))
                session.execute(text(f"DROP TABLE IF EXISTS {_LEGACY_MAP_TABLE}"))
    except Exception as exc:  # noqa: BLE001 - leftover tables are harmless
        LOGGER.info("Kept the legacy vector table: %s", exc.__class__.__name__)


def _fill_vec_table(session: Session, space_id: str, dims: int) -> None:
    session.execute(
        text(
            f"""
            INSERT INTO {ROWS_TABLE} (space_id, asset_id, chunk_no)
            SELECT space_id, asset_id, chunk_no FROM {CHUNKS_TABLE}
            WHERE space_id = :space_id AND length(vector) = :size
            ORDER BY asset_id, chunk_no
            """
        ),
        {"space_id": space_id, "size": dims * 4},
    )
    session.execute(
        text(
            f"""
            INSERT INTO {vec_table_name(space_id)} (rowid, embedding)
            SELECT r.rowid, c.vector
            FROM {ROWS_TABLE} AS r
            JOIN {CHUNKS_TABLE} AS c
              ON c.space_id = r.space_id AND c.asset_id = r.asset_id AND c.chunk_no = r.chunk_no
            WHERE r.space_id = :space_id
            """
        ),
        {"space_id": space_id},
    )


def _vec_table_consistent(session: Session, space_id: str) -> bool:
    params = {"space_id": space_id, "size": space_dims(space_id) * 4}
    chunks = session.execute(
        text(f"SELECT COUNT(*) FROM {CHUNKS_TABLE} WHERE space_id = :space_id AND length(vector) = :size"), params
    ).scalar()
    mapped = session.execute(
        text(
            f"""
            SELECT COUNT(*) FROM {ROWS_TABLE} AS r
            JOIN {CHUNKS_TABLE} AS c
              ON c.space_id = r.space_id AND c.asset_id = r.asset_id AND c.chunk_no = r.chunk_no
            WHERE r.space_id = :space_id
            """
        ),
        {"space_id": space_id},
    ).scalar()
    rows = session.execute(text(f"SELECT COUNT(*) FROM {ROWS_TABLE} WHERE space_id = :space_id"), {"space_id": space_id}).scalar()
    vectors = session.execute(text(f"SELECT COUNT(*) FROM {vec_table_name(space_id)}")).scalar()
    return int(chunks or 0) == int(mapped or 0) == int(rows or 0) == int(vectors or 0)


def _insert_vec_rows(session: Session, space_id: str, asset_id: str, chunks: Iterable[tuple[int, bytes]]) -> None:
    table = vec_table_name(space_id)
    for chunk_no, vector in chunks:
        session.execute(
            text(f"INSERT INTO {ROWS_TABLE} (space_id, asset_id, chunk_no) VALUES (:space_id, :asset_id, :chunk_no)"),
            {"space_id": space_id, "asset_id": asset_id, "chunk_no": chunk_no},
        )
        rowid = session.execute(
            text(
                f"SELECT rowid FROM {ROWS_TABLE} WHERE space_id = :space_id AND asset_id = :asset_id AND chunk_no = :chunk_no"
            ),
            {"space_id": space_id, "asset_id": asset_id, "chunk_no": chunk_no},
        ).scalar_one()
        session.execute(text(f"INSERT INTO {table} (rowid, embedding) VALUES (:rowid, :embedding)"), {"rowid": rowid, "embedding": vector})


def _delete_asset_chunks(session: Session, space_id: str, asset_id: str, *, vec_ready: bool) -> None:
    params = {"space_id": space_id, "asset_id": asset_id}
    if vec_ready:
        table = vec_table_name(space_id)
        for rowid in session.execute(
            text(f"SELECT rowid FROM {ROWS_TABLE} WHERE space_id = :space_id AND asset_id = :asset_id"), params
        ).scalars():
            session.execute(text(f"DELETE FROM {table} WHERE rowid = :rowid"), {"rowid": rowid})
    # Without the extension the table (if any) goes stale; it is rebuilt from the chunks on its next use.
    session.execute(text(f"DELETE FROM {ROWS_TABLE} WHERE space_id = :space_id AND asset_id = :asset_id"), params)
    session.execute(text(f"DELETE FROM {CHUNKS_TABLE} WHERE space_id = :space_id AND asset_id = :asset_id"), params)


def _drop_space_rows(session: Session, space_id: str) -> None:
    params = {"space_id": space_id}
    session.execute(text(f"DELETE FROM {CHUNKS_TABLE} WHERE space_id = :space_id"), params)
    session.execute(text("DELETE FROM asset_embeddings WHERE space_id = :space_id"), params)
    session.execute(text(f"DELETE FROM {ROWS_TABLE} WHERE space_id = :space_id"), params)
    if _vec_table_exists(session, space_id):
        if _load_sqlite_vec(session):
            session.execute(text(f"DROP TABLE {vec_table_name(space_id)}"))
        else:
            # Rowids are never reused, so the orphaned table can never alias new rows; it is rebuilt if reused.
            LOGGER.info("Left a vector search table in place: sqlite-vec is not loadable here")


def _asset_spaces(session: Session, asset_id: str) -> list[str]:
    spaces: set[str] = set()
    for statement in (
        f"SELECT DISTINCT space_id FROM {CHUNKS_TABLE} WHERE asset_id = :asset_id",
        "SELECT DISTINCT space_id FROM asset_embeddings WHERE asset_id = :asset_id",
        f"SELECT DISTINCT space_id FROM {ROWS_TABLE} WHERE asset_id = :asset_id",
    ):
        spaces.update(str(value) for value in session.execute(text(statement), {"asset_id": asset_id}).scalars())
    return sorted(spaces)


def _stored_spaces(session: Session) -> list[str]:
    spaces: set[str] = set()
    for statement in (
        f"SELECT DISTINCT space_id FROM {CHUNKS_TABLE}",
        "SELECT DISTINCT space_id FROM asset_embeddings",
    ):
        spaces.update(str(value) for value in session.execute(text(statement)).scalars())
    return sorted(spaces)


def _latest_local_space(session: Session, dims: int) -> str | None:
    for value in session.execute(
        text("SELECT space_id FROM asset_embeddings WHERE dimensions = :dims ORDER BY created_at DESC, id DESC"),
        {"dims": dims},
    ).scalars():
        space = str(value)
        if not is_unknown_peer_space(space):
            return space
    return None


def _persist_metadata(session: Session, space_id: str, record: EmbeddingRecord, now: datetime) -> None:
    row_id = embedding_row_id(space_id, record.asset_id)
    session.execute(
        text(
            """
            INSERT INTO asset_embeddings (id, asset_id, provider, vector_ref, dimensions, created_at, space_id)
            VALUES (:id, :asset_id, :provider, :vector_ref, :dimensions, :created_at, :space_id)
            ON CONFLICT(id) DO UPDATE SET
                provider = excluded.provider,
                vector_ref = excluded.vector_ref,
                dimensions = excluded.dimensions,
                created_at = excluded.created_at
            """
        ).bindparams(bindparam("created_at", type_=_TIMESTAMP)),
        {
            "id": row_id,
            "asset_id": record.asset_id,
            "provider": record.provider[:128],
            "vector_ref": record.vector_ref[:256],
            "dimensions": record.dimensions,
            "created_at": now,
            "space_id": space_id,
        },
    )
    session.execute(
        text("DELETE FROM asset_embeddings WHERE space_id = :space_id AND asset_id = :asset_id AND id != :id"),
        {"space_id": space_id, "asset_id": record.asset_id, "id": row_id},
    )


def embedding_row_id(space_id: str, asset_id: str) -> str:
    """`asset_embeddings.id`: one metadata row per (space, asset)."""
    digest = hashlib.sha256(f"{space_id}\n{asset_id}".encode("utf-8")).hexdigest()
    return f"emb_{digest[:40]}"


# Search


def _sqlite_vec_distances(session: Session, space_id: str, vector: Vector, *, limit: int) -> list[tuple[str, int, float]]:
    # Each asset has at most MAX_CHUNKS_PER_ASSET chunks, so the best chunk of every top-`limit` asset is among
    # the nearest `limit * MAX_CHUNKS_PER_ASSET` chunks: the result equals the exact scan.
    k = min(limit * MAX_CHUNKS_PER_ASSET, _KNN_MAX)
    rows = session.execute(
        text(
            f"""
            WITH knn AS (
                SELECT rowid, distance FROM {vec_table_name(space_id)}
                WHERE embedding MATCH :embedding AND k = :k
            )
            SELECT r.asset_id, r.chunk_no, knn.distance
            FROM knn
            JOIN {ROWS_TABLE} AS r ON r.rowid = knn.rowid
            WHERE r.space_id = :space_id
            """
        ),
        {"embedding": pack_vector(vector), "k": k, "space_id": space_id},
    ).all()
    return [(str(asset_id), int(chunk_no), float(distance)) for asset_id, chunk_no, distance in rows]


def _fallback_distances(session: Session, space_id: str, vector: Vector) -> list[tuple[str, int, float]]:
    query = unpack_vector(pack_vector(vector))  # compare at float32 precision, like sqlite-vec
    size = len(vector) * 4
    distances: list[tuple[str, int, float]] = []
    for asset_id, chunk_no, raw in session.execute(
        text(f"SELECT asset_id, chunk_no, vector FROM {CHUNKS_TABLE} WHERE space_id = :space_id"),
        {"space_id": space_id},
    ):
        data = bytes(raw)
        if len(data) != size:
            continue
        distances.append((str(asset_id), int(chunk_no), _l2_distance(query, unpack_vector(data))))
    return distances


def _top_hits(
    session: Session, space_id: str, distances: Sequence[tuple[str, int, float]], *, limit: int
) -> tuple[VectorSearchHit, ...]:
    best = best_chunk_scores((asset_id, -distance) for asset_id, _, distance in distances)
    best_chunk: dict[str, int] = {}
    for asset_id, chunk_no, distance in distances:
        if -distance == best[asset_id] and asset_id not in best_chunk:
            best_chunk[asset_id] = chunk_no
    ranked = sorted(best.items(), key=lambda item: (-item[1], item[0]))[:limit]
    if not ranked:
        return ()
    metadata = {
        str(row["asset_id"]): (str(row["id"]), str(row["provider"]))
        for row in session.execute(
            text(
                "SELECT asset_id, id, provider FROM asset_embeddings WHERE space_id = :space_id AND asset_id IN :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"space_id": space_id, "ids": [asset_id for asset_id, _ in ranked]},
        ).mappings()
    }
    hits: list[VectorSearchHit] = []
    for asset_id, negative_distance in ranked:
        distance = -negative_distance
        embedding_id, provider = metadata.get(asset_id, ("", ""))
        hits.append(
            VectorSearchHit(
                asset_id=asset_id,
                embedding_id=embedding_id,
                provider=provider,
                distance=distance,
                score=similarity_from_distance(distance),
                space_id=space_id,
                chunk_no=best_chunk.get(asset_id, 0),
            )
        )
    return tuple(hits)


# Vectors


def _validate_vector(vector: Sequence[float], dimensions: int) -> None:
    if len(vector) != dimensions:
        raise ValueError(f"expected {dimensions} dimensions, got {len(vector)}")
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("vector contains non-finite values")


def pack_vector(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_vector(raw: object) -> Vector:
    data = bytes(raw)  # type: ignore[call-overload]
    if len(data) % 4 != 0:
        raise ValueError("stored vector blob has an invalid length")
    return struct.unpack(f"<{len(data) // 4}f", data)


def _l2_distance(left: Vector, right: Vector) -> float:
    if len(left) != len(right):
        return float("inf")
    return math.sqrt(math.fsum((a - b) * (a - b) for a, b in zip(left, right, strict=True)))


def similarity_from_distance(distance: float) -> float:
    """The dot product of two unit vectors from their L2 distance (`1 - d²/2`), clamped to [0, 1]."""
    return min(max(1.0 - (distance * distance) / 2.0, 0.0), 1.0)
