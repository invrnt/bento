"""Sender-side size caps: `asset_index` text is cut to the sync cap, and no op larger than receivers accept is published."""

from __future__ import annotations

import json

from bento.application.sync.asset_index import MAX_INDEX_OP_BYTES, MAX_INDEX_TEXT_BYTES, fit_index_fields, ocr_fields
from bento.application.sync.batching import MAX_BATCH_BYTES, MAX_OP_BYTES, deliverable, plan_flush
from bento.application.sync.ports import AssetHoldState
from bento.domain.sync import SyncEntity, SyncOperation, SyncOpKind
from bento.domain.vault import canonical_json
from bento.ports.sync import OutboxEntry


def encoded(value: object) -> int:
    return len(canonical_json(value))


def entry(seq: int, entity: SyncEntity, entity_id: str, fields: dict[str, object]) -> OutboxEntry:
    operation = SyncOperation(
        op_id=f"op{seq}", hlc=f"{seq:016d}-000000-dev_a", device_id="dev_a",
        entity=entity, entity_id=entity_id, kind=SyncOpKind.UPSERT, fields=fields,
    )
    return OutboxEntry(seq=seq, operation=operation, size_bytes=encoded(operation.to_dict()))


def test_small_index_fields_are_kept_as_they_are() -> None:
    fields = ocr_fields(ocr_text="Total factura", pdf_pages=[(1, "Total"), (2, "factura")], language="es")
    assert fields == {
        "ocr_text": "Total factura",
        "pdf_pages": [{"page": 1, "text": "Total"}, {"page": 2, "text": "factura"}],
        "language": "es",
    }


def test_huge_ocr_text_is_cut_to_the_text_budget_keeping_page_order() -> None:
    page = "línea con \"comillas\" y saltos\n" * 12_000  # JSON escaping makes it bigger than its characters
    pages = [(number, f"p{number} {page}") for number in range(1, 9)]
    fields = ocr_fields(ocr_text="\n".join(text for _, text in pages), pdf_pages=pages, language=None)

    assert encoded(fields["ocr_text"]) <= MAX_INDEX_TEXT_BYTES
    assert fields["ocr_text"].startswith("p1 línea")
    assert encoded(fields["pdf_pages"]) <= MAX_INDEX_TEXT_BYTES
    assert [item["page"] for item in fields["pdf_pages"]] == list(range(1, len(fields["pdf_pages"]) + 1))
    kept = fields["pdf_pages"]
    assert 1 < len(kept) < len(pages)
    assert kept[0]["text"] == pages[0][1], "pages that fit are kept whole"
    last = pages[len(kept) - 1][1]
    assert last.startswith(kept[-1]["text"]) and len(kept[-1]["text"]) < len(last), "the page at the budget is cut"
    assert encoded(fields) <= MAX_INDEX_OP_BYTES + 1024
    json.loads(canonical_json(fields))  # still valid JSON after cutting inside escapes


def test_fields_without_text_keep_their_embedding() -> None:
    fields = {"embedding": {"provider": "mock", "dimensions": 2, "vector_b64_f32": "AAAAAAAAgD8"}}
    assert fit_index_fields(fields) == fields


def test_oversized_index_ops_recorded_earlier_are_cut_down_at_flush() -> None:
    raw = entry(1, SyncEntity.ASSET_INDEX, "asset_1", {"ocr_text": "x" * (3 * MAX_INDEX_OP_BYTES), "pdf_pages": []})

    published = deliverable(raw)

    assert published is not None and published.seq == 1
    assert published.size_bytes <= MAX_INDEX_OP_BYTES and published.size_bytes == encoded(published.operation.to_dict())


def test_ops_no_receiver_accepts_are_dropped_and_the_rest_split_by_size() -> None:
    huge = entry(1, SyncEntity.FOLDER, "folder_huge", {"name": "x" * (MAX_OP_BYTES + 1)})
    medium = [entry(seq, SyncEntity.FOLDER, f"folder_{seq}", {"name": "y" * 200_000}) for seq in range(2, 8)]
    index = entry(8, SyncEntity.ASSET_INDEX, "asset_1", {"ocr_text": "z" * (2 * MAX_INDEX_OP_BYTES)})

    plan = plan_flush([huge, *medium, index], {"asset_1": AssetHoldState.REMOTE})

    assert plan.oversized == (1,) and 1 in plan.dropped
    published = [item for batch in plan.batches for item in batch]
    assert [item.seq for item in published] == [2, 3, 4, 5, 6, 7, 8]
    for batch in plan.batches:
        total = sum(item.size_bytes for item in batch)
        assert total <= MAX_BATCH_BYTES or len(batch) == 1
        assert total <= MAX_OP_BYTES
