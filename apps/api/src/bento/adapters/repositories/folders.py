from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.repositories.batching import chunks, parent_conditions
from bento.adapters.repositories.ids import new_id
from bento.adapters.repositories.mappers import asset_from_model, folder_from_model, folder_to_model
from bento.domain.drive import DriveItem, DriveItemType, DriveSort, Folder, SortOrder, sort_drive_items
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import AssetModel, FolderModel


class SQLiteFolderRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def next_id(self) -> str:
        return new_id("folder")

    async def get(self, folder_id: str) -> Folder | None:
        with session_scope(self._session_factory) as session:
            model = session.scalar(
                select(FolderModel).where(FolderModel.id == folder_id, FolderModel.deleted_at.is_(None))
            )
            return folder_from_model(model) if model is not None else None

    async def add(self, folder: Folder) -> None:
        with session_scope(self._session_factory) as session:
            session.add(folder_to_model(folder))

    async def save(self, folder: Folder) -> None:
        with session_scope(self._session_factory) as session:
            session.merge(folder_to_model(folder))

    async def descendant_ids(self, folder_id: str) -> set[str]:
        with session_scope(self._session_factory) as session:
            descendants: set[str] = set()
            frontier = [folder_id]
            while frontier:
                children = list(
                    session.scalars(
                        select(FolderModel.id).where(
                            FolderModel.parent_id.in_(frontier),
                            FolderModel.deleted_at.is_(None),
                        )
                    )
                )
                new_children = [child_id for child_id in children if child_id not in descendants]
                descendants.update(new_children)
                frontier = new_children
            return descendants

    async def get_many(self, folder_ids: Sequence[str]) -> dict[str, Folder]:
        found: dict[str, Folder] = {}
        with session_scope(self._session_factory) as session:
            for chunk in chunks(folder_ids):
                models = session.scalars(
                    select(FolderModel).where(FolderModel.id.in_(chunk), FolderModel.deleted_at.is_(None))
                )
                found.update((model.id, folder_from_model(model)) for model in models)
        return found

    async def list_children(self, parent_ids: Sequence[str | None]) -> tuple[Folder, ...]:
        children: list[Folder] = []
        with session_scope(self._session_factory) as session:
            for condition in parent_conditions(FolderModel.parent_id, parent_ids):
                models = session.scalars(
                    select(FolderModel)
                    .where(condition, FolderModel.deleted_at.is_(None))
                    .order_by(FolderModel.parent_id, FolderModel.id)
                )
                children.extend(folder_from_model(model) for model in models)
        return tuple(children)

    async def ids_with_children(self, folder_ids: Sequence[str], *, include_assets: bool) -> set[str]:
        found: set[str] = set()
        with session_scope(self._session_factory) as session:
            for chunk in chunks(folder_ids):
                found.update(
                    parent_id
                    for parent_id in session.scalars(
                        select(FolderModel.parent_id)
                        .where(FolderModel.parent_id.in_(chunk), FolderModel.deleted_at.is_(None))
                        .distinct()
                    )
                    if parent_id is not None
                )
                if include_assets:
                    found.update(
                        folder_id
                        for folder_id in session.scalars(
                            select(AssetModel.folder_id)
                            .where(AssetModel.folder_id.in_(chunk), AssetModel.deleted_at.is_(None))
                            .distinct()
                        )
                        if folder_id is not None
                    )
        return found

    async def list_items(
        self,
        *,
        folder_id: str | None,
        cursor: str | None = None,
        limit: int = 50,
        sort: DriveSort | None = None,
        order: SortOrder | None = None,
    ) -> tuple[tuple[DriveItem, ...], str | None]:
        offset = _decode_cursor(cursor)
        with session_scope(self._session_factory) as session:
            folder_models = list(
                session.scalars(
                    select(FolderModel).where(
                        FolderModel.parent_id.is_(None) if folder_id is None else FolderModel.parent_id == folder_id,
                        FolderModel.deleted_at.is_(None),
                    )
                )
            )
            asset_models = list(
                session.scalars(
                    select(AssetModel).where(
                        AssetModel.folder_id.is_(None) if folder_id is None else AssetModel.folder_id == folder_id,
                        AssetModel.deleted_at.is_(None),
                    )
                )
            )
            counts = _child_counts(session, [model.id for model in folder_models])

        items = [
            DriveItem(
                type=DriveItemType.FOLDER,
                id=folder.id,
                name=folder.name,
                updated_at=folder.updated_at,
                folder=folder,
                item_count=counts.get(folder.id, 0),
            )
            for folder in (folder_from_model(model) for model in folder_models)
        ]
        items.extend(
            DriveItem(
                type=DriveItemType.ASSET,
                id=asset.id,
                name=asset.filename,
                updated_at=asset.updated_at,
                asset=asset,
            )
            for asset in (asset_from_model(model) for model in asset_models)
        )
        items = sort_drive_items(items, sort, order)
        visible = items[offset : offset + limit]
        next_cursor = str(offset + limit) if len(items) > offset + limit else None
        return tuple(visible), next_cursor


def _child_counts(session: Session, folder_ids: Sequence[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for chunk in chunks(folder_ids):
        for model, column in ((FolderModel, FolderModel.parent_id), (AssetModel, AssetModel.folder_id)):
            rows = session.execute(
                select(column, func.count())
                .where(column.in_(chunk), model.deleted_at.is_(None))
                .group_by(column)
            ).all()
            for parent_id, count in rows:
                counts[parent_id] = counts.get(parent_id, 0) + int(count)
    return counts


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(cursor)
    except ValueError:
        return 0
    return max(value, 0)
