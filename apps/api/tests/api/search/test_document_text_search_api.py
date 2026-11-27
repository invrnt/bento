"""A `.txt` and a PDF with a text layer, uploaded with OCR disabled (the desktop default), are found by their
content: by full-text search and by search by meaning (a fake, bag-of-words embedder; no model, no llama-server).

Production wiring end to end: `create_app` for upload and search, `_create_dispatcher` for the worker. Only the
embedder is swapped for the fake, on both sides.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bento.adapters.embeddings import SQLiteEmbeddingTextCatalog
from bento.adapters.search.composite import CompositeSearchIndex
from bento.adapters.search.sqlite_fts import SQLiteFTSSearchIndex
from bento.adapters.search.sqlite_vec import SQLiteVecSearchIndex
from bento.application.indexing.embedding import EmbeddingIndexingService
from bento.application.search import SearchUseCase
from bento.domain.smart_search import EmbeddingSpace, space_id_for
from bento.infrastructure.db.clock import SystemClock
from bento.infrastructure.db.engine import create_session_factory, sqlite_url
from bento.infrastructure.settings import Settings
from bento.infrastructure.storage_pipeline import reset_storage_pipeline
from bento.interfaces.http.main import create_app
from bento.interfaces.http.routes_search import SearchRouteDependencies
from bento.interfaces.worker import main as worker_main
from tests.fakes.pdf_documents import pdf_with_pages
from tests.integration.db.support import migrated_session_factory

pytest.importorskip("pypdfium2")

DIMS = 64
SPACE = EmbeddingSpace(
    id=space_id_for("fake-bow", "b" * 40, DIMS), model_id="fake-bow", revision="b" * 40, dims=DIMS
)
LEASE = "Contrato de arrendamiento del piso. La fianza es de dos mensualidades."
GROCERIES = "Lista de la compra: tomates, aceite de oliva y pan de pueblo."


def _words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode("ascii")
    return [word for word in re.findall(r"[a-z]{4,}", plain)]


def bag_of_words(text: str) -> tuple[float, ...]:
    values = [0.0] * DIMS
    for word in _words(text):
        values[int(hashlib.sha256(word.encode()).hexdigest(), 16) % DIMS] += 1.0
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        values[0], norm = 1.0, 1.0
    return tuple(value / norm for value in values)


@dataclass
class BagOfWordsEmbedder:
    """`SpaceEmbeddingProviderPort` + the query side: similar words, similar vectors."""

    documents: list[str] = field(default_factory=list)

    async def is_enabled(self) -> bool:
        return True

    @property
    def space(self) -> EmbeddingSpace:
        return SPACE

    async def embed_documents(self, texts: Sequence[str], *, title: str | None = None) -> tuple[tuple[float, ...], ...]:
        self.documents.extend(texts)
        return tuple(bag_of_words(text) for text in texts)

    async def embed_query(self, text: str) -> tuple[float, ...]:
        return bag_of_words(text)


@dataclass
class Device:
    client: TestClient
    dispatcher: Any
    embedder: BagOfWordsEmbedder
    vectors: SQLiteVecSearchIndex

    def upload(self, name: str, content: bytes, mime: str) -> str:
        response = self.client.post("/api/assets/upload", files={"file": (name, content, mime)})
        assert response.status_code == 200, response.text
        return str(response.json()["id"])

    def drain(self) -> int:
        async def loop() -> int:
            ran = 0
            while await self.dispatcher.process_one():
                ran += 1
            return ran

        return asyncio.run(loop())

    def search(self, query: str) -> list[dict[str, Any]]:
        response = self.client.get("/api/search", params={"q": query})
        assert response.status_code == 200
        return list(response.json()["items"])


@pytest.fixture
def device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Device]:
    data_dir = tmp_path / "data"
    (data_dir / "db").mkdir(parents=True)
    migrated_session_factory(data_dir / "db")
    monkeypatch.setattr(worker_main, "_WORKER_EMBEDDINGS", {})
    # `mock` makes uploads queue embedding jobs; the worker's and the API's embedder are then replaced.
    settings = Settings(data_dir=str(data_dir), storage_backend="local", ocr_provider="disabled", embeddings_provider="mock")
    client = TestClient(create_app(settings))

    factory = create_session_factory(sqlite_url(data_dir / "db" / "bento.sqlite3"))
    clock = SystemClock()
    vectors = SQLiteVecSearchIndex(factory, clock)
    asyncio.run(vectors.register_space(SPACE))
    asyncio.run(vectors.activate_space(SPACE.id))
    embedder = BagOfWordsEmbedder()

    dispatcher = worker_main._create_dispatcher("worker-test", settings)
    base = dispatcher.embedding
    dispatcher = replace(
        dispatcher,
        embedding=EmbeddingIndexingService(
            assets=base._assets,  # type: ignore[union-attr]
            blob_refs=base._blob_refs,  # type: ignore[union-attr]
            resolver=base._resolver,  # type: ignore[union-attr]
            provider=embedder,
            index=vectors,
            manifest=base._manifest,  # type: ignore[union-attr]
            clock=clock,
            text_catalog=SQLiteEmbeddingTextCatalog(factory),
        ),
    )
    client.app.state.search_route_dependencies = SearchRouteDependencies(
        search=SearchUseCase(
            index=CompositeSearchIndex(
                factory,
                clock,
                text_index=SQLiteFTSSearchIndex(factory, clock),
                vector_index=vectors,
                query_embedding_provider=embedder,
            )
        )
    )
    try:
        yield Device(client, dispatcher, embedder, vectors)
    finally:
        client.close()
        reset_storage_pipeline()


def test_text_and_pdf_content_is_searchable_without_ocr(device: Device) -> None:
    note = device.upload("nota.txt", GROCERIES.encode("utf-8"), "text/plain")
    lease = device.upload("documento.pdf", pdf_with_pages([[LEASE]]), "application/pdf")
    assert device.drain() == 5  # the PDF thumbnail, 2 × text_extract, 2 × embedding; no OCR job at all

    # Full-text search finds words that are only in the content, not in the file names.
    fianza = device.search("fianza")
    assert [item["asset_id"] for item in fianza][:1] == [lease]
    assert "indexed_text" in fianza[0]["match_reasons"]
    assert fianza[0]["snippet"] is not None and "fianza" in fianza[0]["snippet"]["text"].lower()
    assert [item["asset_id"] for item in device.search("tomates")][:1] == [note]

    # The embeddings were computed from the content, not from "nota.txt text/plain".
    assert any("tomates" in text for text in device.embedder.documents)
    assert any("arrendamiento" in text for text in device.embedder.documents)

    # Search by meaning: the closest vector is the document about the same thing.
    for query, expected in (("arrendamiento piso fianza", lease), ("compra aceite tomates", note)):
        hits = asyncio.run(device.vectors.search_vectors(bag_of_words(query), limit=2, space_id=SPACE.id))
        assert hits[0].asset_id == expected and hits[0].score > hits[-1].score
        items = device.search(query)
        assert items[0]["asset_id"] == expected and "semantic" in items[0]["match_reasons"]

    # Both files settle as indexed.
    states = {item["asset_id"]: item["processing_state"] for item in device.search("arrendamiento tomates")}
    assert states.get(lease) == "indexed" and states.get(note) == "indexed"
