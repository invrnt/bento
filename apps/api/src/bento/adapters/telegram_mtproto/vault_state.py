"""Device-local SQLite bookkeeping of the Telegram vault features.

Backend-agnostic: the same adapters serve the MTProto client and the fake cloud. String values in `sync_state`
(`VaultStatePort`) go through `bento.adapters.sync.store.SQLiteSyncStateStore`, shared with the sync engine.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.mappers import aware, require_aware
from bento.adapters.settings import SQLiteSettingsRepository
from bento.application.inbox import InboxRecord, InboxState
from bento.domain.errors import SettingsRevisionConflictError
from bento.domain.vault import VaultUsage
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AssetModel, InboxItemModel


class SQLiteVaultUsage:
    """Library size shown as "en tu nube": every asset that is not in the trash."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def usage(self) -> VaultUsage:
        statement = select(func.count(), func.coalesce(func.sum(AssetModel.size_bytes), 0)).where(
            AssetModel.deleted_at.is_(None)
        )
        with session_scope(self._session_factory) as session:
            files, total = session.execute(statement).one()
        return VaultUsage(files=int(files), bytes=int(total))


class SQLiteStorageBackendPreference:
    """Once a vault exists, a saved "Solo este equipo" (`local`) choice becomes `telegram`."""

    def __init__(self, settings: SQLiteSettingsRepository) -> None:
        self._settings = settings

    async def prefer_telegram(self) -> None:
        for _ in range(3):
            persisted = await self._settings.load()
            raw = persisted.values.get("storage_backend")
            if raw is None or _decoded(raw) != "local":
                return
            try:
                await self._settings.compare_and_set(
                    expected_revision=persisted.revision,
                    values={"storage_backend": json.dumps("telegram")},
                    secret_references={},
                )
                return
            except SettingsRevisionConflictError:
                continue


def _decoded(raw: str) -> object:
    try:
        return json.loads(raw)
    except ValueError:
        return raw


class SQLiteInboxItems:
    """`inbox_items`: what this device did with each Inbox message (`InboxItemStorePort`)."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def get(self, message_id: int) -> InboxRecord | None:
        with session_scope(self._session_factory) as session:
            model = session.get(InboxItemModel, message_id)
            return _record(model) if model is not None else None

    async def save(self, record: InboxRecord) -> None:
        with session_scope(self._session_factory) as session:
            session.merge(
                InboxItemModel(
                    message_id=record.message_id,
                    state=record.state.value,
                    asset_id=record.asset_id,
                    error_code=record.error_code,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
            )

    async def in_state(self, state: InboxState, *, updated_before: datetime | None = None, limit: int = 100) -> tuple[InboxRecord, ...]:
        statement = select(InboxItemModel).where(InboxItemModel.state == state.value)
        if updated_before is not None:
            statement = statement.where(InboxItemModel.updated_at <= updated_before)
        statement = statement.order_by(InboxItemModel.message_id).limit(limit)
        with session_scope(self._session_factory) as session:
            return tuple(_record(model) for model in session.scalars(statement))


def _record(model: InboxItemModel) -> InboxRecord:
    return InboxRecord(
        message_id=int(model.message_id),
        state=InboxState(model.state),
        asset_id=model.asset_id,
        error_code=model.error_code,
        created_at=require_aware(model.created_at),
        updated_at=aware(model.updated_at) or require_aware(model.created_at),
    )
