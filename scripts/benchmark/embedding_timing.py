"""Time local embedding providers (and optionally the SQLite vector index).

Mock provider (no model):

    uv run --project apps/api python scripts/benchmark/embedding_timing.py --provider mock

llama.cpp, spawning a llama-server the way the worker does (Unix socket or loopback + per-launch key):

    uv run --project apps/api python scripts/benchmark/embedding_timing.py --provider llama-cpp \\
        --server ~/.cache/bento-spike/llama/llama-b12777/llama-server \\
        --model-path ~/.cache/bento-spike/models/embeddinggemma-2-Q8_0.gguf

or against a server you started yourself with `--endpoint-url http://127.0.0.1:8080`. Nothing leaves the
machine; request bodies are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
API_SRC = REPO_ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from bento.adapters.embeddings import LlamaCppEmbeddingProvider, MockEmbeddingProvider  # noqa: E402
from bento.adapters.runtime.llama_server_process import (  # noqa: E402
    ExternalEmbeddingServer,
    LlamaServerProcess,
    normalize_server_url,
)
from bento.adapters.search.sqlite_vec import SQLiteVecSearchIndex  # noqa: E402
from bento.domain.indexing import EmbeddingRecord  # noqa: E402
from bento.domain.smart_search import (  # noqa: E402
    ModelSpec,
    chunk_text,
    default_embedding_threads,
    parse_manifest,
)
from bento.infrastructure.db.engine import create_session_factory, sqlite_url  # noqa: E402

PACKAGED_MANIFEST = API_SRC / "bento" / "infrastructure" / "models" / "manifest.json"
TEST_MANIFEST = REPO_ROOT / "apps" / "api" / "tests" / "unit" / "smart_search" / "manifest_v1.json"

Vector = tuple[float, ...]


class BenchmarkClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


async def main() -> None:
    args = _parse_args()
    if args.provider == "mock":
        vectors = await _run_mock(args)
    else:
        vectors = await _run_llama(args)
    if args.sqlite_db is not None and vectors:
        await _time_sqlite(args, vectors)


async def _run_mock(args: argparse.Namespace) -> list[Vector]:
    provider = MockEmbeddingProvider(dimensions=args.dimensions)
    timings: list[float] = []
    vectors: list[Vector] = []
    for index in range(args.count):
        start = time.perf_counter()
        _, vector = await provider.embed_text(f"bench_asset_{index}", f"{args.text} #{index}")
        timings.append(time.perf_counter() - start)
        vectors.append(vector)
    _report("embed", timings)
    print(f"provider=mock count={len(vectors)} dimensions={args.dimensions}")
    return vectors


async def _run_llama(args: argparse.Namespace) -> list[Vector]:
    spec = _spec(args)
    space = spec.space(args.dimensions)
    external = normalize_server_url(args.endpoint_url)
    with tempfile.TemporaryDirectory(prefix="bento-bench-") as run_dir:
        if external:
            runtime: LlamaServerProcess | ExternalEmbeddingServer = ExternalEmbeddingServer(external)
            weights = Path(args.model_path or ".")
        else:
            if args.server is None or args.model_path is None:
                raise SystemExit("--server and --model-path are required unless --endpoint-url is given")
            runtime = LlamaServerProcess(run_dir=Path(run_dir), binary=args.server, threads=args.threads)
            weights = args.model_path
        start = time.perf_counter()
        endpoint = await runtime.ensure(spec, space, weights)
        print(f"server_ready_ms={(time.perf_counter() - start) * 1000:.0f} space={space.id}")
        provider = LlamaCppEmbeddingProvider(spec=spec, space=space, endpoint=lambda: endpoint)
        try:
            query_timings: list[float] = []
            for index in range(args.count):
                start = time.perf_counter()
                await provider.embed_query(f"{args.text} {index}")
                query_timings.append(time.perf_counter() - start)
            _report("query", query_timings)

            long_text = " ".join(f"{args.text} número {index}." for index in range(args.count * 40))
            chunks = [chunk.text for chunk in chunk_text(long_text, max_tokens=spec.chunk_tokens)]
            start = time.perf_counter()
            vectors = list(await provider.embed_documents(chunks, title="benchmark.txt"))
            elapsed = time.perf_counter() - start
            print(f"chunks={len(chunks)} chunk_ms_avg={elapsed * 1000 / max(1, len(chunks)):.1f} dims={space.dims}")
            return vectors
        finally:
            await runtime.stop()


def _spec(args: argparse.Namespace) -> ModelSpec:
    manifest_path = args.manifest or (PACKAGED_MANIFEST if PACKAGED_MANIFEST.is_file() else TEST_MANIFEST)
    specs, default_id = parse_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    wanted = args.model_id or default_id
    for spec in specs:
        if spec.model_id == wanted:
            return spec
    raise SystemExit(f"Model {wanted} is not in {manifest_path}")


async def _time_sqlite(args: argparse.Namespace, vectors: list[Vector]) -> None:
    dimensions = len(vectors[0])
    records = []
    for index, vector in enumerate(vectors):
        digest = hashlib.sha1(f"bench:{index}".encode("utf-8")).hexdigest()
        records.append(
            (
                EmbeddingRecord(
                    id=f"emb_{digest[:24]}",
                    asset_id=f"bench_asset_{index}",
                    provider=args.provider,
                    vector_ref=f"bench:{digest[:32]}",
                    dimensions=dimensions,
                ),
                vector,
            )
        )
    factory = create_session_factory(sqlite_url(args.sqlite_db))
    index = SQLiteVecSearchIndex(
        factory,
        BenchmarkClock(),
        dimensions=dimensions,
        prefer_sqlite_vec=not args.force_fallback,
    )
    start = time.perf_counter()
    for record, vector in records:
        await index.index_embedding_vector(record, vector)
    insert_elapsed = time.perf_counter() - start
    start = time.perf_counter()
    hits = await index.search_vectors(records[0][1], limit=min(args.limit, len(records)))
    search_elapsed = time.perf_counter() - start
    print(f"vector_insert_ms_total={insert_elapsed * 1000:.2f}")
    print(f"vector_search_ms={search_elapsed * 1000:.2f} hits={len(hits)} sqlite_vec={index.using_sqlite_vec}")


def _report(name: str, timings: list[float]) -> None:
    if not timings:
        return
    ordered = sorted(timings)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    print(
        f"{name}_ms_avg={statistics.fmean(timings) * 1000:.2f} {name}_ms_p50={statistics.median(timings) * 1000:.2f} "
        f"{name}_ms_p95={p95 * 1000:.2f} {name}_ms_max={max(timings) * 1000:.2f}"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Time local embedding providers and optional SQLite vector search.")
    parser.add_argument("--provider", choices=("mock", "llama-cpp"), default="mock")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--dimensions", type=int, default=None, help="Matryoshka dims (default: the manifest's)")
    parser.add_argument("--text", default="Contrato de arrendamiento con firma")
    parser.add_argument("--server", type=Path, help="llama-server binary to spawn")
    parser.add_argument("--model-path", type=Path, help="GGUF weights for the spawned server")
    parser.add_argument("--endpoint-url", default="", help="Use an already running server instead of spawning one")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--model-id")
    parser.add_argument("--threads", type=int, default=default_embedding_threads(_cpu_count()))
    parser.add_argument("--sqlite-db", type=Path)
    parser.add_argument("--force-fallback", action="store_true")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    if args.provider == "mock" and args.dimensions is None:
        args.dimensions = 768
    return args


def _cpu_count() -> int:
    import os

    return os.cpu_count() or 1


if __name__ == "__main__":
    asyncio.run(main())
