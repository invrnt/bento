"""Shared setup of the opt-in `real_model` tests: a real `llama-server` and the pinned GGUF from local paths.

Nothing here downloads anything. Point `BENTO_REAL_LLAMA_SERVER` and `BENTO_REAL_EMBEDDING_MODEL` at local files;
`BENTO_REAL_MODEL_ID` picks another manifest model.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType

import pytest

from bento.adapters.embeddings import LlamaCppEmbeddingProvider
from bento.adapters.runtime.llama_server_process import LlamaServerProcess
from bento.domain.smart_search import ModelSpec, default_embedding_threads, parse_manifest

SERVER = os.environ.get("BENTO_REAL_LLAMA_SERVER", "")
MODEL = os.environ.get("BENTO_REAL_EMBEDDING_MODEL", "")
REPO_ROOT = Path(__file__).resolve().parents[5]
DATASET = REPO_ROOT / "scripts" / "spikes" / "smart-search" / "dataset.py"
MANIFEST = Path(__file__).resolve().parents[2] / "unit" / "smart_search" / "manifest_v1.json"

needs_real_model = pytest.mark.skipif(
    not (SERVER and MODEL), reason="set BENTO_REAL_LLAMA_SERVER and BENTO_REAL_EMBEDDING_MODEL"
)


def dataset() -> ModuleType:
    """The Stage 23 spike's synthetic fixture (`scripts/spikes/smart-search/dataset.py`)."""
    spec = importlib.util.spec_from_file_location("bento_spike_dataset", DATASET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def model_spec() -> ModelSpec:
    specs, default_id = parse_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))
    model_id = os.environ.get("BENTO_REAL_MODEL_ID", default_id)
    return next(s for s in specs if s.model_id == model_id)


@asynccontextmanager
async def real_provider(run_dir: Path, spec: ModelSpec, dims: int | None = None) -> AsyncIterator[LlamaCppEmbeddingProvider]:
    """A provider on a freshly started `llama-server`, stopped on exit."""
    space = spec.space(spec.native_dims if dims is None else dims)
    runtime = LlamaServerProcess(
        run_dir=run_dir,
        binary=Path(SERVER).expanduser(),
        threads=default_embedding_threads(os.cpu_count() or 1),
    )
    info = await runtime.ensure(spec, space, Path(MODEL).expanduser())
    try:
        yield LlamaCppEmbeddingProvider(spec=spec, space=space, endpoint=lambda: info)
    finally:
        await runtime.stop()


def dot(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return math.fsum(a * b for a, b in zip(left, right, strict=True))
