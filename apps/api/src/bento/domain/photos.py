from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime

from bento.domain.errors import ValidationFailedError


@dataclass(frozen=True, slots=True)
class Album:
    id: str
    title: str
    asset_ids: frozenset[str]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    cover_asset_id: str | None = None
    """Chosen on this device (not synced); always a member, `None` lets clients pick one."""

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValidationFailedError("Album id is required")
        if not self.title.strip():
            raise ValidationFailedError("Album title is required")

    def rename(self, title: str, at: datetime) -> Album:
        if not title.strip():
            raise ValidationFailedError("Album title is required")
        return replace(self, title=title, updated_at=at)

    def add_asset(self, asset_id: str, at: datetime) -> Album:
        if not asset_id.strip():
            raise ValidationFailedError("Asset id is required")
        return replace(self, asset_ids=self.asset_ids | {asset_id}, updated_at=at)

    def remove_asset(self, asset_id: str, at: datetime) -> Album:
        cover = None if self.cover_asset_id == asset_id else self.cover_asset_id
        return replace(self, asset_ids=self.asset_ids - {asset_id}, cover_asset_id=cover, updated_at=at)

    def with_cover(self, asset_id: str | None, at: datetime) -> Album:
        if asset_id is not None and asset_id not in self.asset_ids:
            raise ValidationFailedError("The cover must be a photo of the album", {"asset_id": asset_id})
        return replace(self, cover_asset_id=asset_id, updated_at=at)

    def mark_deleted(self, at: datetime) -> Album:
        return replace(self, deleted_at=at, updated_at=at)


@dataclass(frozen=True, slots=True)
class TimelineGroup:
    day: date
    asset_ids: tuple[str, ...]
