from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

DEFAULT_TRASH_RETENTION_DAYS = 30


class TrashItemType(StrEnum):
    ASSET = "asset"
    FOLDER = "folder"


@dataclass(frozen=True, slots=True)
class TrashItem:
    id: str
    type: TrashItemType
    name: str
    size_bytes: int
    deleted_at: datetime
    purge_at: datetime


def purge_at(deleted_at: datetime, retention_days: int = DEFAULT_TRASH_RETENTION_DAYS) -> datetime:
    return deleted_at + timedelta(days=retention_days)
