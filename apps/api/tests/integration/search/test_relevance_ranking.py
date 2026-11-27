"""Semantic floor and hybrid ranking with fakes: controlled cosines, no model (`product/search.md` §Scoring).

Each file's vector sits at a chosen cosine from the query vector, so a test reads like the real-model harness's
findings (`execution/evidence/smart-search-relevance-calibration-2026-11-27.md`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

from bento.adapters.repositories import SQLiteAssetRepository
from bento.adapters.search.composite import CompositeSearchIndex
from bento.adapters.search.sqlite_fts import SQLiteFTSSearchIndex
from bento.adapters.search.sqlite_vec import SQLiteVecSearchIndex
from bento.domain.assets import Asset, AssetKind, AssetMetadata, AssetMode, ProcessingState, infer_asset_kind
from bento.domain.indexing import ExtractedPage
from bento.domain.search import MatchReason, SearchQuery
from bento.domain.smart_search import EmbeddingSpace, ModelSpec, parse_manifest

from tests.integration.db.support import NOW, FixedClock, migrated_session_factory
from tests.integration.search.vector_support import record

DIMS = 768
CANONICAL = Path(__file__).parents[2] / "unit" / "smart_search" / "manifest_v1.json"


def _spec() -> ModelSpec:
    specs, default_id = parse_manifest(json.loads(CANONICAL.read_text(encoding="utf-8")))
    base = next(spec for spec in specs if spec.model_id == default_id)
    return replace(base, min_similarity=((DIMS, 0.60),), similarity_margin=0.15)


SPEC = _spec()
SPACE = SPEC.space(DIMS)


def _at_cosine(cosine: float, axis: int) -> tuple[float, ...]:
    """A unit vector whose dot product with the query vector (axis 0) is `cosine`."""
    vector = [0.0] * DIMS
    vector[0] = cosine
    vector[axis] = math.sqrt(max(1.0 - cosine * cosine, 0.0))
    return tuple(vector)


QUERY_VECTOR = _at_cosine(1.0, 1)


@dataclass
class Provider:
    """The query side of the managed provider: a spec, its space and one query vector for every query."""

    spec: ModelSpec = SPEC
    space: EmbeddingSpace = SPACE

    async def is_enabled(self) -> bool:
        return True

    async def embed_query(self, text: str) -> tuple[float, ...]:
        return QUERY_VECTOR


@dataclass(frozen=True)
class File:
    name: str
    text: str = ""
    cosine: float | None = None  # None: no vector


async def _library(tmp_path: Path, files: list[File], *, smart: bool = True) -> CompositeSearchIndex:
    directory = tmp_path / f"library-{len(list(tmp_path.iterdir()))}"
    directory.mkdir()
    factory = migrated_session_factory(directory)
    clock = FixedClock()
    fts = SQLiteFTSSearchIndex(factory, clock)
    vectors = SQLiteVecSearchIndex(factory, clock, prefer_sqlite_vec=False)
    await vectors.register_space(SPACE)
    await vectors.activate_space(SPACE.id)
    repository = SQLiteAssetRepository(factory)
    for index, file in enumerate(files):
        mime = {"pdf": "application/pdf", "png": "image/png", "txt": "text/plain"}[file.name.rsplit(".", 1)[1]]
        asset = Asset(
            id=f"asset_{index:02d}",
            kind=infer_asset_kind(mime),
            mode=AssetMode.DRIVE,
            folder_id=None,
            filename=file.name,
            metadata=AssetMetadata(
                original_filename=file.name,
                mime_type=mime,
                size_bytes=10,
                sha256=hashlib.sha256(file.name.encode()).hexdigest(),
            ),
            processing_state=ProcessingState.INDEXED,
            favorite=False,
            created_at=NOW,
            updated_at=NOW,
        )
        await repository.add(asset)
        if asset.kind is not AssetKind.IMAGE:  # OCR off: images have no text row, like production
            await fts.replace_document_text(asset.id, [ExtractedPage(text=file.text)] if file.text else [])
        if file.cosine is not None:
            await vectors.index_embedding_vector(record(asset.id, DIMS), _at_cosine(file.cosine, index + 2), space_id=SPACE.id)
    return CompositeSearchIndex(
        factory,
        clock,
        text_index=fts,
        vector_index=vectors,
        query_embedding_provider=Provider() if smart else None,
    )


def _search(tmp_path: Path, files: list[File], text: str, *, smart: bool = True) -> list[tuple[str, set[MatchReason]]]:
    async def scenario() -> list[tuple[str, set[MatchReason]]]:
        search = await _library(tmp_path, files, smart=smart)
        results = await search.search(SearchQuery(text=text, limit=10))
        return [(item.title, set(item.match_reasons)) for item in results.items]

    return asyncio.run(scenario())


def _titles(hits: list[tuple[str, set[MatchReason]]]) -> list[str]:
    return [title for title, _ in hits]


def _semantic(hits: list[tuple[str, set[MatchReason]]]) -> list[str]:
    return [title for title, reasons in hits if MatchReason.SEMANTIC in reasons]


def test_vector_hits_below_the_floor_are_not_matches(tmp_path: Path) -> None:
    files = [
        File("beach-vacation.txt", "Sun and sand.", cosine=0.78),
        File("hotel-mallorca.txt", "Room with a sea view.", cosine=0.70),
        File("phone-bill.txt", "Fibre and mobile.", cosine=0.58),  # below 0.60
        File("inventory.txt", "Boxes in the storage room.", cosine=0.45),
    ]
    hits = _search(tmp_path, files, "holiday by the sea")
    assert _titles(hits) == ["beach-vacation.txt", "hotel-mallorca.txt"]
    assert _semantic(hits) == ["beach-vacation.txt", "hotel-mallorca.txt"]


def test_hits_far_below_the_best_one_are_dropped(tmp_path: Path) -> None:
    files = [
        File("beach-vacation.txt", "Sun and sand.", cosine=0.84),
        File("weak.txt", "Something else.", cosine=0.66),  # above the floor, 0.18 below the best
    ]
    assert _semantic(_search(tmp_path, files, "holiday by the sea")) == ["beach-vacation.txt"]


def test_a_nonsense_query_returns_no_semantic_hit(tmp_path: Path) -> None:
    files = [File(f"note-{n}.txt", "Shopping list.", cosine=0.40 + n * 0.03) for n in range(6)]  # 0.40 .. 0.55
    assert _search(tmp_path, files, "zzzz quantum chromodynamics") == []


def test_stop_words_do_not_outrank_a_strong_semantic_hit(tmp_path: Path) -> None:
    files = [
        File("ideas-regalos-navidad.txt", "Un libro y una bufanda.", cosine=0.58),  # «de» in i-de-as
        File("endesa-recibo-abril.png", cosine=0.55),  # «de» in en-de-sa
        File("doc-2026-0601.pdf", "Denuncia por exceso de velocidad: 100 euros.", cosine=0.75),
    ]
    hits = _search(tmp_path, files, "multa de velocidad")
    assert _titles(hits)[0] == "doc-2026-0601.pdf"
    assert "ideas-regalos-navidad.txt" not in _titles(hits) and "endesa-recibo-abril.png" not in _titles(hits)


def test_a_short_prefix_does_not_outrank_a_strong_semantic_hit(tmp_path: Path) -> None:
    files = [
        File("receta-pasta-carbonara.pdf", "Guanciale, yemas y pecorino.", cosine=0.52),
        File("nota-taller.txt", "Cambio de pastillas de freno.", cosine=0.66),
    ]
    hits = _search(tmp_path, files, "car brakes repair")
    assert _titles(hits) == ["nota-taller.txt"]


def test_a_file_name_only_match_ranks_below_a_strong_semantic_hit(tmp_path: Path) -> None:
    files = [
        File("ticket-supermercado.png", cosine=0.59),
        File("doc-2026-0601.pdf", "Denuncia por exceso de velocidad.", cosine=0.68),
    ]
    hits = _search(tmp_path, files, "speeding ticket")
    assert _titles(hits) == ["doc-2026-0601.pdf", "ticket-supermercado.png"]
    assert hits[1][1] == {MatchReason.FILENAME, MatchReason.METADATA}  # still found by its name, not by meaning


def test_body_text_beats_the_same_words_in_a_name(tmp_path: Path) -> None:
    files = [
        File("presupuesto-reunion.txt", "Lista de la compra.", cosine=0.62),
        File("acta.txt", "Acta de la reunión de presupuesto del tercer trimestre.", cosine=0.62),
    ]
    assert _titles(_search(tmp_path, files, "reunión de presupuesto"))[0] == "acta.txt"


def test_an_exact_file_name_is_still_found_first_with_smart_search_on(tmp_path: Path) -> None:
    files = [
        File("endesa-recibo-abril.png", cosine=0.50),  # its name embeds far from the query
        File("factura-luz-enero.pdf", "Factura de electricidad.", cosine=0.66),
        File("factura-luz-febrero.pdf", "Factura de electricidad.", cosine=0.65),
    ]
    assert _titles(_search(tmp_path, files, "endesa"))[0] == "endesa-recibo-abril.png"
    assert _titles(_search(tmp_path, files, "endesa-recibo-abril.png"))[0] == "endesa-recibo-abril.png"


def test_text_only_search_ignores_stop_words_and_short_prefixes(tmp_path: Path) -> None:
    files = [
        File("ideas-regalos-navidad.txt", "Un libro y una bufanda."),
        File("receta-pasta-carbonara.pdf", "Guanciale, yemas y pecorino."),
        File("factura-luz-enero.pdf", "Compañía Eléctrica. Factura de electricidad."),
        File("apuntes.txt", "La contraseña wifi es Gaviota."),
    ]
    assert _titles(_search(tmp_path, files, "facturas de luz", smart=False)) == ["factura-luz-enero.pdf"]
    assert _search(tmp_path, files, "car", smart=False) == []
    assert _titles(_search(tmp_path, files, "carbo", smart=False)) == ["receta-pasta-carbonara.pdf"]
    # «del» is not in the text: FTS no longer requires it.
    hits = _search(tmp_path, files, "contraseña del wifi", smart=False)
    assert _titles(hits) == ["apuntes.txt"] and MatchReason.INDEXED_TEXT in hits[0][1]
    # Inside quotes the stop words count again, in order.
    assert _search(tmp_path, files, '"contraseña del wifi"', smart=False) == []
    assert _titles(_search(tmp_path, files, '"contraseña wifi"', smart=False)) == ["apuntes.txt"]
    # A query made only of stop words still searches for them.
    assert "factura-luz-enero.pdf" in _titles(_search(tmp_path, files, "de", smart=False))
