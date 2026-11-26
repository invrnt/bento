"""Stage 23 smart search spike: latency, RSS, throughput and retrieval quality of the
pinned GGUF embedding models on a real llama-server.

Not part of any test suite. Run from the repo root (uses the backend's pure domain
helpers for the chunker and Matryoshka truncation):

    uv run --project apps/api python scripts/spikes/smart-search/bench.py \\
        --server ~/.cache/bento-spike/llama/llama-b12777/llama-server \\
        --models ~/.cache/bento-spike/models --out /tmp/bench.json

Writes a JSON report and prints a Markdown table. No network access besides 127.0.0.1.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import socket
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from dataset import documents, queries  # noqa: E402

from bento.domain.smart_search import chunk_text, estimate_tokens, truncate_and_renormalize  # noqa: E402


@dataclass(frozen=True)
class ModelUnderTest:
    key: str
    file: str
    pooling: str
    query_template: str
    document_template: str
    dims: tuple[int, ...]


MODELS = [
    ModelUnderTest(
        key="embeddinggemma-2-q8_0",
        file="embeddinggemma-2-Q8_0.gguf",
        pooling="mean",
        query_template="task: search result | query: {q}",
        document_template="title: {title} | text: {text}",
        dims=(768, 512, 256),
    ),
    ModelUnderTest(
        key="qwen3-embedding-0.6b-q8_0",
        file="Qwen3-Embedding-0.6B-Q8_0.gguf",
        pooling="last",
        query_template="Instruct: Given a search query, retrieve relevant files\nQuery:{q}",
        document_template="{text}",
        dims=(1024,),
    ),
]

THREADS = 4
BATCH = 8


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def evict_page_cache(path: Path) -> None:
    """Drop the file's clean pages so the start is a real cold start (no root needed)."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    finally:
        os.close(fd)


def rss_kib(pid: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in {"VmRSS", "VmHWM", "RssAnon", "RssFile"}:
            out[key] = int(value.split()[0])
    return out


class Server:
    def __init__(self, binary: Path, model: Path, pooling: str, key_file: Path) -> None:
        self.port = free_port()
        self.key = secrets.token_urlsafe(24)
        key_file.write_text(self.key)
        key_file.chmod(0o600)
        self.argv = [
            str(binary), "-m", str(model), "--embeddings", "--pooling", pooling,
            "-c", "2048", "-ub", "2048", "-b", "2048", "-np", "1",
            "-t", str(THREADS), "-tb", str(THREADS),
            "--host", "127.0.0.1", "--port", str(self.port),
            "--api-key-file", str(key_file), "--no-ui", "--offline",
        ]
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self) -> float:
        t0 = time.perf_counter()
        self.proc = subprocess.Popen(self.argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while True:
            if self.proc.poll() is not None:
                raise RuntimeError(f"llama-server exited with {self.proc.returncode}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1) as r:
                    if r.status == 200:
                        return time.perf_counter() - t0
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass
            time.sleep(0.02)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def post(self, path: str, body: dict[str, Any]) -> Any:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"},
        )
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read())

    def embed(self, texts: list[str]) -> list[list[float]]:
        data = self.post("/v1/embeddings", {"input": texts})["data"]
        return [row["embedding"] for row in sorted(data, key=lambda r: r["index"])]

    def tokens(self, text: str) -> int:
        return len(self.post("/tokenize", {"content": text, "add_special": True})["tokens"])


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def dot(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.fsum(x * y for x, y in zip(a, b, strict=True))


def throughput_chunks() -> list[str]:
    corpus = " ".join(d["text"] for d in documents())
    long_text = " ".join([corpus] * 3)
    return [c.text for c in chunk_text(long_text, max_tokens=512, max_chunks=32)]


def score(rankings: dict[str, list[str]], qs: list[dict[str, Any]]) -> dict[str, Any]:
    per_lang: dict[str, list[tuple[float, float]]] = {}
    rows = []
    for q in qs:
        ranked = rankings[q["id"]]
        relevant = set(q["relevant"])
        hits5 = len(relevant & set(ranked[:5]))
        recall5 = hits5 / min(len(relevant), 5)
        first = next((i for i, d in enumerate(ranked) if d in relevant), None)
        rr = 0.0 if first is None else 1.0 / (first + 1)
        rows.append({"id": q["id"], "recall5": recall5, "rr": rr, "top3": ranked[:3]})
        per_lang.setdefault(q["lang"], []).append((recall5, rr))
        per_lang.setdefault("all", []).append((recall5, rr))
    summary = {
        lang: {"recall5": statistics.fmean(v[0] for v in vals), "mrr": statistics.fmean(v[1] for v in vals), "n": len(vals)}
        for lang, vals in per_lang.items()
    }
    return {"summary": summary, "queries": rows}


def run_model(m: ModelUnderTest, binary: Path, models_dir: Path, work: Path) -> dict[str, Any]:
    path = models_dir / m.file
    docs, qs = documents(), queries()
    result: dict[str, Any] = {"model": m.key, "file": m.file, "bytes": path.stat().st_size}

    # Cold start (page cache evicted) then one warm start.
    starts = []
    for cold in (True, False):
        if cold:
            evict_page_cache(path)
        srv = Server(binary, path, m.pooling, work / "key")
        try:
            starts.append(srv.start())
            if cold:
                t0 = time.perf_counter()
                srv.embed([m.query_template.replace("{q}", "hola")])
                result["first_query_after_cold_s"] = time.perf_counter() - t0
        finally:
            srv.stop()
    result["cold_start_s"], result["warm_start_s"] = starts

    srv = Server(binary, path, m.pooling, work / "key")
    srv.start()
    assert srv.proc is not None
    try:
        srv.embed(["warmup"])
        result["rss_idle_kib"] = rss_kib(srv.proc.pid)

        # Token estimator vs the real tokenizer.
        ratios = [estimate_tokens(d["text"]) / max(1, srv.tokens(d["text"])) for d in docs]
        chunks = throughput_chunks()
        chunk_tokens = [srv.tokens(m.document_template.replace("{title}", "none").replace("{text}", c)) for c in chunks]
        result["estimator"] = {
            "docs_ratio_min": min(ratios),
            "docs_ratio_median": statistics.median(ratios),
            "chunk_real_tokens_mean": statistics.fmean(chunk_tokens),
            "chunk_real_tokens_max": max(chunk_tokens),
        }

        # Query latency: each query alone, three rounds.
        lat = []
        for _ in range(3):
            for q in qs:
                t0 = time.perf_counter()
                srv.embed([m.query_template.replace("{q}", str(q["q"]))])
                lat.append((time.perf_counter() - t0) * 1000)
        result["query_ms"] = {"p50": pct(lat, 0.5), "p95": pct(lat, 0.95), "n": len(lat)}

        # Throughput at the program's chunk size (~512 tokens), batches of 8.
        texts = [m.document_template.replace("{title}", "none").replace("{text}", c) for c in chunks]
        t0 = time.perf_counter()
        for i in range(0, len(texts), BATCH):
            srv.embed(texts[i : i + BATCH])
        elapsed = time.perf_counter() - t0
        result["throughput"] = {"chunks": len(texts), "seconds": elapsed, "chunks_per_s": len(texts) / elapsed}

        # Retrieval.
        doc_texts = [m.document_template.replace("{title}", d["title"]).replace("{text}", d["text"]) for d in docs]
        t0 = time.perf_counter()
        doc_vecs: list[list[float]] = []
        for i in range(0, len(doc_texts), BATCH):
            doc_vecs.extend(srv.embed(doc_texts[i : i + BATCH]))
        result["short_docs_per_s"] = len(doc_texts) / (time.perf_counter() - t0)
        q_vecs = srv.embed([m.query_template.replace("{q}", str(q["q"])) for q in qs])
        result["rss_after_kib"] = rss_kib(srv.proc.pid)
        result["native_dims"] = len(doc_vecs[0])
        assert all(math.isfinite(v) for vec in doc_vecs for v in vec), "non-finite embedding"

        result["retrieval"] = {}
        for dims in m.dims:
            dv = [truncate_and_renormalize(v, dims) for v in doc_vecs]
            rankings = {}
            for q, qv in zip(qs, q_vecs, strict=True):
                tq = truncate_and_renormalize(qv, dims)
                order = sorted(range(len(docs)), key=lambda i: -dot(tq, dv[i]))
                rankings[str(q["id"])] = [docs[i]["id"] for i in order]
            result["retrieval"][str(dims)] = score(rankings, qs)

        # Qwen3 last-token pooling needs EOS; record what the server appends itself.
        result["special_tokens_hola"] = srv.post("/tokenize", {"content": "hola", "add_special": True})["tokens"]
    finally:
        srv.stop()
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", type=Path, required=True)
    ap.add_argument("--models", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", default=None)
    args = ap.parse_args()
    work = args.out.parent
    version = subprocess.run([str(args.server), "--version"], capture_output=True, text=True).stderr.strip()
    report: dict[str, Any] = {"llama_server_version": version, "threads": THREADS, "results": []}
    for m in MODELS:
        if args.only and m.key != args.only:
            continue
        print(f"== {m.key}", file=sys.stderr)
        report["results"].append(run_model(m, args.server.expanduser(), args.models.expanduser(), work))
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    for r in report["results"]:
        for dims, ret in r["retrieval"].items():
            s = ret["summary"]
            langs = " ".join(f"{k}:{v['recall5']:.3f}/{v['mrr']:.3f}" for k, v in sorted(s.items()) if k != "all")
            print(f"| {r['model']} | {dims} | {s['all']['recall5']:.3f} | {s['all']['mrr']:.3f} | {langs} |")
        print(
            f"  cold {r['cold_start_s']:.2f}s warm {r['warm_start_s']:.2f}s first-q {r['first_query_after_cold_s']*1000:.0f}ms "
            f"rss idle {r['rss_idle_kib']['VmRSS']/1024:.0f}MiB after {r['rss_after_kib']['VmRSS']/1024:.0f}MiB hwm {r['rss_after_kib']['VmHWM']/1024:.0f}MiB "
            f"q p50 {r['query_ms']['p50']:.1f}ms p95 {r['query_ms']['p95']:.1f}ms thr {r['throughput']['chunks_per_s']:.2f} ch/s "
            f"est {r['estimator']}"
        )


if __name__ == "__main__":
    main()
