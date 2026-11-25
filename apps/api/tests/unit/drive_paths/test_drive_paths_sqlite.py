"""Drive path use cases on the SQLite repositories: batch queries and sync change capture of `ensure`."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from bento.adapters.repositories import SQLiteAssetRepository, SQLiteFolderRepository
from bento.adapters.sync import install_change_capture
from bento.application.drive import DriveUseCases
from bento.application.drive_paths import DrivePathUseCases
from bento.domain.drive import Folder
from bento.domain.drive_paths import parse_drive_path
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import SyncOutboxModel, SyncStateModel
from tests.integration.db.support import NOW, FixedClock, make_asset, migrated_session_factory


class NullManifest:
    async def append(self, **_: Any) -> None:
        return None


def _use_cases(factory: Any) -> tuple[DrivePathUseCases, SQLiteFolderRepository, SQLiteAssetRepository]:
    folders = SQLiteFolderRepository(factory)
    assets = SQLiteAssetRepository(factory)
    drive = DriveUseCases(assets=assets, folders=folders, manifest=NullManifest(), clock=FixedClock())  # type: ignore[arg-type]
    return DrivePathUseCases(folders=folders, assets=assets, drive=drive), folders, assets


def test_folders_created_by_ensure_are_captured_for_sync(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path, session_hooks=False)
    ticks = iter(range(1_000, 10_000_000, 10))
    install_change_capture(factory, now_ms=lambda: next(ticks), now=lambda: NOW)
    with session_scope(factory) as session:
        session.add(
            SyncStateModel(key="capture", value=json.dumps({"vault_id": "vlt_t", "device_id": "dev_1"}), updated_at=NOW)
        )
    paths, _, _ = _use_cases(factory)

    result = asyncio.run(paths.ensure_folder(parse_drive_path("/Viajes/Lima")))

    with session_scope(factory) as session:
        rows = [
            (row.entity, row.entity_id, row.kind, row.fields_json.get("name"))
            for row in session.scalars(select(SyncOutboxModel).order_by(SyncOutboxModel.seq))
        ]
    assert len(result.created) == 2
    assert rows == [
        ("folder", result.created[0], "upsert", "Viajes"),
        ("folder", result.created[1], "upsert", "Lima"),
    ]


def test_batch_queries(tmp_path: Path) -> None:
    factory = migrated_session_factory(tmp_path)
    paths, folders, assets = _use_cases(factory)

    async def scenario() -> None:
        await folders.add(Folder(id="folder_a", name="A", parent_id=None, created_at=NOW, updated_at=NOW))
        await folders.add(Folder(id="folder_b", name="B", parent_id="folder_a", created_at=NOW, updated_at=NOW))
        await folders.add(
            Folder(id="folder_gone", name="G", parent_id="folder_a", created_at=NOW, updated_at=NOW, deleted_at=NOW)
        )
        await assets.add(make_asset("asset_root", filename="r.pdf", sha256="1" * 64))
        await assets.add(make_asset("asset_b2", filename="z.pdf", sha256="2" * 64, folder_id="folder_b"))
        await assets.add(make_asset("asset_b1", filename="a.pdf", sha256="2" * 64, folder_id="folder_b"))

        assert set(await folders.get_many(["folder_a", "folder_gone", "nope", "folder_a"])) == {"folder_a"}
        assert [f.id for f in await folders.list_children([None])] == ["folder_a"]
        assert {f.id for f in await folders.list_children([None, "folder_a"])} == {"folder_a", "folder_b"}
        assert await folders.ids_with_children(["folder_a", "folder_b"], include_assets=False) == {"folder_a"}
        assert await folders.ids_with_children(["folder_a", "folder_b"], include_assets=True) == {"folder_a", "folder_b"}
        listed = await assets.list_in_folders([None, "folder_b"])
        assert [a.id for a in listed] == ["asset_root", "asset_b1", "asset_b2"]  # root first, then filename
        capped = await assets.list_in_folders(["folder_b", None], limit=2)
        assert [a.id for a in capped] == ["asset_root", "asset_b1"]
        assert set(await assets.get_many(["asset_b1", "nope"])) == {"asset_b1"}
        assert set(await assets.get_many_by_sha256(["2" * 64, "1" * 64])) == {"1" * 64, "2" * 64}

        many = [f"folder_x{index:04d}" for index in range(1_200)]  # more than one IN chunk
        assert await folders.get_many(many) == {}
        assert [f.id for f in await folders.list_children([*many, None])] == ["folder_a"]
        assert await folders.ids_with_children([*many, "folder_a"], include_assets=True) == {"folder_a"}

        result = await paths.paths_for_ids(["asset_b1", "folder_gone"])
        assert result.paths == {"asset_b1": "/A/B/a.pdf"} and result.missing == ("folder_gone",)

    asyncio.run(scenario())
