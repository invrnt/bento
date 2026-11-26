from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from bento.application.indexing.reindex import ReindexService
from bento.domain.assets import Asset, AssetKind, AssetMetadata, AssetMode, AssetOrigin, ProcessingState
from bento.domain.jobs import JobType
from bento.domain.smart_search import space_id_for

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
SPACE = space_id_for("model-a", "a" * 40, 512)


def _asset(asset_id: str, origin: AssetOrigin | None = AssetOrigin.DEVICE, kind: AssetKind = AssetKind.PDF) -> Asset:
    return Asset(
        id=asset_id,
        kind=kind,
        mode=AssetMode.DRIVE,
        folder_id=None,
        filename=f"{asset_id}.pdf",
        metadata=AssetMetadata(original_filename=f"{asset_id}.pdf", mime_type="application/pdf", size_bytes=1, sha256="a" * 64),
        processing_state=ProcessingState.INDEXED,
        favorite=False,
        created_at=NOW,
        updated_at=NOW,
        origin=origin,
    )


@dataclass
class Assets:
    items: list[Asset]

    async def list_live(self, *, after_id: str | None = None, limit: int = 200) -> tuple[Asset, ...]:
        ordered = sorted(self.items, key=lambda asset: asset.id)
        if after_id is not None:
            ordered = [asset for asset in ordered if asset.id > after_id]
        return tuple(ordered[:limit])


@dataclass
class Jobs:
    queued: list[tuple[JobType, dict[str, object], str | None]] = field(default_factory=list)
    busy: set[tuple[str, JobType]] = field(default_factory=set)

    async def enqueue(
        self,
        *,
        type: JobType,
        priority: int,
        payload: dict[str, object],
        asset_id: str | None = None,
        max_attempts: int = 3,
    ) -> object:
        self.queued.append((type, payload, asset_id))
        return object()

    async def has_active(self, asset_id: str, *, types: frozenset[JobType], exclude_job_id: str | None = None) -> bool:
        return any((asset_id, job_type) in self.busy for job_type in types)


@dataclass
class Spaces:
    active: str | None

    async def active_space_id(self) -> str | None:
        return self.active


@dataclass
class Vectors:
    embedded: dict[str, set[str]]

    async def assets_with_vectors(self, space_id: str, asset_ids: Sequence[str]) -> frozenset[str]:
        return frozenset(set(asset_ids) & self.embedded.get(space_id, set()))


def _library() -> list[Asset]:
    return [
        _asset("asset_1"),
        _asset("asset_2"),
        _asset("asset_3", kind=AssetKind.VIDEO),
        _asset("asset_inbox", AssetOrigin.TELEGRAM_INBOX),
        _asset("asset_peer", None),
    ]


def test_embedding_jobs_name_the_active_space() -> None:
    jobs = Jobs()
    service = ReindexService(
        assets=Assets(_library()),
        jobs=jobs,  # type: ignore[arg-type]
        active=jobs,
        ocr_enabled=False,
        embeddings_enabled=True,
        spaces=Spaces(SPACE),
        page_size=2,
    )

    assert asyncio.run(service.run()) == 3
    assert [(job_type, payload) for job_type, payload, _ in jobs.queued] == [
        (JobType.EMBEDDING, {"asset_id": "asset_1", "space_id": SPACE}),
        (JobType.EMBEDDING, {"asset_id": "asset_2", "space_id": SPACE}),
        (JobType.EMBEDDING, {"asset_id": "asset_3", "space_id": SPACE}),
    ]


def test_missing_only_skips_assets_already_in_the_space() -> None:
    jobs = Jobs()
    service = ReindexService(
        assets=Assets(_library()),
        jobs=jobs,  # type: ignore[arg-type]
        active=jobs,
        ocr_enabled=False,
        embeddings_enabled=True,
        spaces=Spaces(SPACE),
        vectors=Vectors({SPACE: {"asset_1"}}),
    )

    assert asyncio.run(service.run(missing_only=True)) == 2
    assert [asset_id for _, _, asset_id in jobs.queued] == ["asset_2", "asset_3"]


def test_without_spaces_the_payload_is_unchanged_and_ocr_still_runs() -> None:
    jobs = Jobs(busy={("asset_2", JobType.EMBEDDING)})
    service = ReindexService(
        assets=Assets(_library()),
        jobs=jobs,  # type: ignore[arg-type]
        active=jobs,
        ocr_enabled=True,
        embeddings_enabled=True,
    )

    assert asyncio.run(service.run()) == 4
    assert [(job_type, payload) for job_type, payload, _ in jobs.queued] == [
        (JobType.OCR, {"asset_id": "asset_1"}),
        (JobType.EMBEDDING, {"asset_id": "asset_1"}),
        (JobType.OCR, {"asset_id": "asset_2"}),
        (JobType.EMBEDDING, {"asset_id": "asset_3"}),
    ]
