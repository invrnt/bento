"""`TextExtractionService` and the domain rules it applies, with fakes only (no SQLite, OCR, PDF library, model)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from bento.application.indexing import OCRIndexingService
from bento.application.indexing.text import TextExtractionService
from bento.application.work_budget import WorkBudgetExceeded, work_deadline
from bento.domain.assets import Asset, AssetKind, AssetMetadata, AssetMode, AssetOrigin, ProcessingState
from bento.domain.errors import ValidationFailedError
from bento.domain.indexing import (
    ExtractedPage,
    ExtractedText,
    OCRBlock,
    cap_extracted_pages,
    supports_text_extraction,
    usable_text_layer,
)
from bento.domain.jobs import JobType
from bento.domain.storage import BlobKind, BlobRef, StorageBackend

NOW = datetime(2026, 11, 27, tzinfo=UTC)
SHA = "a" * 64
LONG_PAGE = "Factura de la luz de enero, consumo 245 kWh, importe 45,20 EUR."


def make_asset(
    kind: AssetKind = AssetKind.DOCUMENT,
    *,
    mime: str = "text/plain",
    origin: AssetOrigin | None = AssetOrigin.DEVICE,
    state: ProcessingState = ProcessingState.BLOB_STORED,
) -> Asset:
    name = "nota.pdf" if kind == AssetKind.PDF else "nota.txt"
    return Asset(
        id="asset_1",
        kind=kind,
        mode=AssetMode.DRIVE,
        folder_id=None,
        filename=name,
        metadata=AssetMetadata(original_filename=name, mime_type=mime, size_bytes=10, sha256=SHA),
        processing_state=state,
        favorite=False,
        created_at=NOW,
        updated_at=NOW,
        origin=origin,
    )


class FakeAssets:
    def __init__(self, asset: Asset) -> None:
        self.asset = asset
        self.saved: list[Asset] = []

    async def get(self, asset_id: str) -> Asset | None:
        return self.asset if asset_id == self.asset.id else None

    async def save(self, asset: Asset) -> None:
        self.asset = asset
        self.saved.append(asset)


class FakeBlobRefs:
    def __init__(self, ref: BlobRef | None) -> None:
        self.ref = ref

    async def latest_for_asset(self, asset_id: str, kind: BlobKind) -> BlobRef | None:
        return self.ref if kind == BlobKind.ORIGINAL else None


class FakeResolver:
    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve(self, blob_ref: BlobRef) -> Path:
        return self.root / blob_ref.object_key


@dataclass
class FakeExtractor:
    result: ExtractedText | Exception
    mime_types: frozenset[str] = frozenset({"text/plain", "application/pdf"})
    calls: list[tuple[Path, str]] = field(default_factory=list)
    checkpoints: list[Callable[[], None] | None] = field(default_factory=list)

    def supports(self, mime_type: str) -> bool:
        return mime_type.split(";")[0].strip().lower() in self.mime_types

    async def extract(self, source_path: Path, mime_type: str, *, checkpoint: Callable[[], None] | None = None) -> ExtractedText:
        self.calls.append((source_path, mime_type))
        self.checkpoints.append(checkpoint)
        if checkpoint is not None:
            checkpoint()
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@dataclass
class FakeStore:
    pages: dict[str, tuple[ExtractedPage, ...]] = field(default_factory=dict)
    writes: int = 0

    async def replace_document_text(self, asset_id: str, pages: Sequence[ExtractedPage]) -> None:
        self.writes += 1
        if pages:
            self.pages[asset_id] = tuple(pages)
        else:
            self.pages.pop(asset_id, None)

    async def has_document_text(self, asset_id: str) -> bool:
        return asset_id in self.pages


@dataclass
class FakeJobs:
    queued: list[tuple[JobType, dict[str, object], str | None]] = field(default_factory=list)
    busy: set[JobType] = field(default_factory=set)

    async def enqueue(self, *, type: JobType, priority: int, payload: dict[str, object], asset_id: str | None = None, max_attempts: int = 3) -> object:
        self.queued.append((type, payload, asset_id))
        return object()

    async def has_active(self, asset_id: str, *, types: frozenset[JobType], exclude_job_id: str | None = None) -> bool:
        return bool(self.busy & types)


@dataclass
class FakePages:
    saved: list[tuple[str, int, str]] = field(default_factory=list)

    async def save_page_text(self, *, asset_id: str, page_number: int, text: str) -> None:
        self.saved.append((asset_id, page_number, text))


@dataclass
class FakeRecorder:
    ocr: list[tuple[str, str, tuple[tuple[int, str], ...]]] = field(default_factory=list)

    async def record_ocr(self, asset_id: str, *, ocr_text: str, pdf_pages: Sequence[tuple[int, str]], language: str | None = None) -> None:
        self.ocr.append((asset_id, ocr_text, tuple(pdf_pages)))


@dataclass
class Kit:
    service: TextExtractionService
    extractor: FakeExtractor
    store: FakeStore
    jobs: FakeJobs
    pages: FakePages
    recorder: FakeRecorder


def kit_for(
    tmp_path: Path,
    asset: Asset,
    result: ExtractedText | Exception,
    *,
    ocr: bool = False,
    embeddings: bool = False,
    busy: set[JobType] | None = None,
    write_original: bool = True,
) -> Kit:
    source = tmp_path / "original.bin"
    if write_original:
        source.write_bytes(b"x")
    ref = BlobRef(
        id="blob_1",
        asset_id=asset.id,
        backend=StorageBackend.LOCAL,
        kind=BlobKind.ORIGINAL,
        object_key=source.name,
        size_bytes=1,
        sha256=SHA,
    )
    extractor = FakeExtractor(result)
    store, jobs, pages, recorder = FakeStore(), FakeJobs(busy=busy or set()), FakePages(), FakeRecorder()
    service = TextExtractionService(
        assets=FakeAssets(asset),
        blob_refs=FakeBlobRefs(ref),
        resolver=FakeResolver(tmp_path),
        extractor=extractor,
        store=store,
        ocr_enabled=lambda: ocr,
        embeddings_enabled=lambda: embeddings,
        jobs=jobs,
        active=jobs,
        pdf_pages=pages,
        index_recorder=recorder,  # type: ignore[arg-type]
    )
    return Kit(service, extractor, store, jobs, pages, recorder)


def text(*pages: str | None, pages_read: int | None = None) -> ExtractedText:
    kept = tuple(
        ExtractedPage(text=value, page_number=index + 1) for index, value in enumerate(pages) if value is not None
    )
    return ExtractedText(pages=kept, pages_read=pages_read if pages_read is not None else len(pages))


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


# Domain ---------------------------------------------------------------------------------------------------------


def test_text_extraction_types_ignore_mime_parameters_and_case() -> None:
    assert supports_text_extraction("Text/Plain; charset=ISO-8859-1")
    assert supports_text_extraction("text/markdown") and supports_text_extraction("text/csv")
    assert supports_text_extraction("application/pdf")
    assert not supports_text_extraction("image/png") and not supports_text_extraction("text/html")


def test_a_text_layer_is_usable_only_with_real_text_per_page() -> None:
    assert usable_text_layer(text(LONG_PAGE))
    assert not usable_text_layer(text())  # no text at all
    # A 10-page scan whose only text is a page number on each page.
    assert not usable_text_layer(ExtractedText(pages=tuple(ExtractedPage(f"- {n} -", n) for n in range(1, 11)), pages_read=10))
    assert usable_text_layer(text(LONG_PAGE, None, LONG_PAGE))  # mostly text with one blank page


def test_extracted_pages_are_capped_in_order() -> None:
    pages = [ExtractedPage("a" * 6, 1), ExtractedPage("b" * 6, 2), ExtractedPage("c" * 6, 3)]

    kept, cut = cap_extracted_pages(pages, max_chars=9)

    assert [page.text for page in kept] == ["a" * 6, "b" * 3] and cut
    assert cap_extracted_pages(pages, max_chars=18) == (tuple(pages), False)


def test_a_file_without_thumbnails_can_go_straight_to_embedding_or_ocr() -> None:
    """Regression (the `.txt` bug): text files stay in `blob_stored` until their first indexing step."""
    asset = make_asset()

    assert asset.transition_to(ProcessingState.EMBEDDING_PENDING, NOW).processing_state is ProcessingState.EMBEDDING_PENDING
    assert asset.transition_to(ProcessingState.OCR_PENDING, NOW).processing_state is ProcessingState.OCR_PENDING
    waiting_thumbnail = make_asset(state=ProcessingState.THUMBNAIL_PENDING)
    assert waiting_thumbnail.transition_to(ProcessingState.EMBEDDING_PENDING, NOW).processing_state is ProcessingState.EMBEDDING_PENDING


# Service --------------------------------------------------------------------------------------------------------


def test_plain_text_is_stored_published_and_its_embedding_refreshed(tmp_path: Path) -> None:
    kit = kit_for(tmp_path, make_asset(), ExtractedText(pages=(ExtractedPage("hola mundo"),), pages_read=1), embeddings=True)

    stored = run(kit.service.process_asset_text("asset_1"))

    assert stored is not None and stored.text == "hola mundo"
    assert kit.store.pages["asset_1"] == (ExtractedPage("hola mundo"),)
    assert kit.recorder.ocr == [("asset_1", "hola mundo", ())]
    assert kit.pages.saved == []  # not a PDF
    assert kit.jobs.queued == [(JobType.EMBEDDING, {"asset_id": "asset_1"}, "asset_1")]


def test_no_second_embedding_job_while_one_waits_and_none_with_embeddings_off(tmp_path: Path) -> None:
    waiting = kit_for(tmp_path, make_asset(), text("hola"), embeddings=True, busy={JobType.EMBEDDING})
    run(waiting.service.process_asset_text("asset_1"))
    assert waiting.jobs.queued == []

    off = kit_for(tmp_path, make_asset(), text("hola"), embeddings=False)
    run(off.service.process_asset_text("asset_1"))
    assert off.jobs.queued == [] and off.store.pages


@pytest.mark.parametrize("origin", [AssetOrigin.TELEGRAM_INBOX, AssetOrigin.TELEGRAM_IMPORT, None])
def test_telegram_and_peer_assets_are_never_read(tmp_path: Path, origin: AssetOrigin | None) -> None:
    kit = kit_for(tmp_path, make_asset(origin=origin), text("secreto"), embeddings=True)

    assert run(kit.service.process_asset_text("asset_1")) is None
    assert kit.extractor.calls == [] and kit.store.writes == 0 and kit.jobs.queued == []


def test_unsupported_types_and_missing_originals_are_skipped(tmp_path: Path) -> None:
    image = kit_for(tmp_path, make_asset(AssetKind.IMAGE, mime="image/png"), text("x"))
    assert run(image.service.process_asset_text("asset_1")) is None and image.extractor.calls == []

    evicted = kit_for(tmp_path / "nowhere", make_asset(), text("x"), write_original=False)
    assert run(evicted.service.process_asset_text("asset_1")) is None and evicted.extractor.calls == []


def test_a_pdf_text_layer_is_stored_per_page_and_preferred(tmp_path: Path) -> None:
    pdf = make_asset(AssetKind.PDF, mime="application/pdf", state=ProcessingState.THUMBNAIL_READY)
    kit = kit_for(tmp_path, pdf, text(LONG_PAGE, None, "Página tres: total"), ocr=True)

    stored = run(kit.service.process_asset_text("asset_1"))

    assert stored is not None and [page.page_number for page in stored.pages] == [1, 3]
    assert kit.pages.saved == [("asset_1", 1, LONG_PAGE), ("asset_1", 3, "Página tres: total")]
    assert kit.recorder.ocr == [("asset_1", f"{LONG_PAGE}\nPágina tres: total", ((1, LONG_PAGE), (3, "Página tres: total")))]


def test_a_near_empty_text_layer_is_left_to_ocr_when_ocr_is_on(tmp_path: Path) -> None:
    pdf = make_asset(AssetKind.PDF, mime="application/pdf")
    scan = text("1", "2", "3")

    with_ocr = kit_for(tmp_path, pdf, scan, ocr=True, embeddings=True)
    stored = run(with_ocr.service.process_asset_text("asset_1"))
    assert stored is not None and stored.empty
    assert with_ocr.store.pages == {} and with_ocr.store.writes == 1  # an older text layer would be cleared
    assert with_ocr.recorder.ocr == [] and with_ocr.jobs.queued == []

    # Without OCR, whatever text there is beats the filename.
    without_ocr = kit_for(tmp_path, pdf, scan, ocr=False)
    run(without_ocr.service.process_asset_text("asset_1"))
    assert [page.text for page in without_ocr.store.pages["asset_1"]] == ["1", "2", "3"]


def test_an_unreadable_file_fails_the_job_without_storing_anything(tmp_path: Path) -> None:
    kit = kit_for(tmp_path, make_asset(AssetKind.PDF, mime="application/pdf"), ValidationFailedError("The PDF could not be read"))

    with pytest.raises(ValidationFailedError, match="could not be read"):
        run(kit.service.process_asset_text("asset_1"))
    assert kit.store.writes == 0 and kit.recorder.ocr == [] and kit.jobs.queued == []


def test_bounded_runs_stop_at_the_extractor_checkpoints(tmp_path: Path) -> None:
    kit = kit_for(tmp_path, make_asset(), text("hola"))

    async def bounded() -> None:
        with work_deadline(0.0, clock=lambda: 1.0):  # already past
            await kit.service.process_asset_text("asset_1")

    with pytest.raises(WorkBudgetExceeded):
        run(bounded())
    assert kit.store.writes == 0


# OCR prefers the text layer -------------------------------------------------------------------------------------


class _Provider:
    def __init__(self) -> None:
        self.calls = 0

    async def is_enabled(self) -> bool:
        return True

    async def extract_text(self, asset_id: str, source_ref: str) -> tuple[OCRBlock, ...]:
        self.calls += 1
        return (OCRBlock(id="ocr_1", asset_id=asset_id, text="ocr"),)


class _NoIndex:
    async def index_ocr(self, block: OCRBlock) -> None:
        raise AssertionError("OCR must not run")


class _Manifest:
    async def append(self, **_: Any) -> None:
        raise AssertionError("OCR must not run")


class _Clock:
    def now(self) -> datetime:
        return NOW


def test_ocr_skips_a_pdf_that_has_a_text_layer(tmp_path: Path) -> None:
    pdf = make_asset(AssetKind.PDF, mime="application/pdf", state=ProcessingState.THUMBNAIL_READY)
    assets = FakeAssets(pdf)
    store = FakeStore(pages={pdf.id: (ExtractedPage(LONG_PAGE, 1),)})
    provider = _Provider()
    service = OCRIndexingService(
        assets=assets,
        blob_refs=FakeBlobRefs(None),
        resolver=FakeResolver(tmp_path),
        provider=provider,
        index=_NoIndex(),  # type: ignore[arg-type]
        manifest=_Manifest(),  # type: ignore[arg-type]
        clock=_Clock(),
        document_text=store,
    )

    assert run(service.process_asset_ocr(pdf.id)) == ()
    assert provider.calls == 0
    assert assets.asset.processing_state is ProcessingState.OCR_READY

    # An image is never skipped because of document text.
    image = replace(pdf, kind=AssetKind.IMAGE)
    assert run(
        OCRIndexingService(
            assets=FakeAssets(image),
            blob_refs=FakeBlobRefs(None),
            resolver=FakeResolver(tmp_path),
            provider=provider,
            index=_NoIndex(),  # type: ignore[arg-type]
            manifest=_Manifest(),  # type: ignore[arg-type]
            clock=_Clock(),
            document_text=store,
        )._has_text_layer(image)
    ) is False
