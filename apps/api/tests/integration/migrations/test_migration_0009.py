from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from bento.domain.smart_search import legacy_space_id
from bento.infrastructure.db.engine import create_session_factory, session_scope, sqlite_url
from bento.infrastructure.db.migrate import current_revision, default_migrations_dir, head_revision, run_migrations
from bento.infrastructure.db.models import (
    AssetEmbeddingChunkModel,
    AssetEmbeddingModel,
    EmbeddingSpaceModel,
    ModelInstallModel,
    SmartSearchStatusModel,
)
from bento.infrastructure.settings import Settings
from tests.integration.db.test_migration_0004 import _columns, _config

BEFORE = "0008_android_gaps"
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
SPACE = "embeddinggemma-2-q8_0@6ea3e3a309d12a4779cfda98b8c19800d2d5da71/512"
_ASSET = (
    "INSERT INTO assets (id, kind, mode, filename, original_filename, mime_type, size_bytes, sha256, processing_state,"
    " favorite, created_at, updated_at) VALUES (?, 'pdf', 'drive', ?, ?, 'application/pdf', 10, ?, 'indexed', 0,"
    " '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
)
_EMBEDDING = (
    "INSERT INTO asset_embeddings (id, asset_id, provider, vector_ref, dimensions, created_at)"
    " VALUES (?, ?, ?, ?, ?, '2026-01-01 00:00:00')"
)
_SETTING = "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, '2026-01-01 00:00:00')"


@pytest.fixture(autouse=True)
def _no_model_path_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for alias in ("JINA_MODEL_PATH", "BENTO_EMBEDDING_MODEL_PATH"):
        monkeypatch.delenv(alias, raising=False)


def _database(tmp_path: Path) -> Path:
    """The app layout: `<data_dir>/db/bento.sqlite3`, with `data_dir = tmp_path / "data"`."""
    db_path = tmp_path / "data" / "db" / "bento.sqlite3"
    db_path.parent.mkdir(parents=True)
    return db_path


def _seed_0008(db_path: Path, *, settings: dict[str, object]) -> None:
    command.upgrade(_config(db_path), BEFORE)
    with sqlite3.connect(db_path) as connection:
        connection.execute(_ASSET, ("asset_1", "receipt.pdf", "receipt.pdf", "a" * 64))
        connection.execute(_ASSET, ("asset_2", "notes.pdf", "notes.pdf", "b" * 64))
        connection.execute(_EMBEDDING, ("emb_1", "asset_1", "jina", "vec:1", 768))
        connection.execute(_EMBEDDING, ("emb_2", "asset_2", "mock", "vec:2", 8))
        for key, value in settings.items():
            connection.execute(_SETTING, (key, json.dumps(value, separators=(",", ":"))))
        connection.execute("UPDATE settings_meta SET revision = 3 WHERE id = 1")


def _settings(db_path: Path) -> dict[str, object]:
    with sqlite3.connect(db_path) as connection:
        return {key: json.loads(value) for key, value in connection.execute("SELECT key, value FROM settings")}


def _settings_revision(db_path: Path) -> int:
    with sqlite3.connect(db_path) as connection:
        return int(connection.execute("SELECT revision FROM settings_meta WHERE id = 1").fetchone()[0])


def _model_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"GGUF")
    return path


def test_0009_backfills_legacy_spaces_and_keeps_legacy_vectors(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    _seed_0008(db_path, settings={"embeddings_provider": "mock"})

    command.upgrade(_config(db_path), "head")

    assert "space_id" in _columns(db_path, "asset_embeddings")
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT id, asset_id, provider, vector_ref, dimensions, space_id FROM asset_embeddings ORDER BY id"
        ).fetchall()
        not_null = {row[1]: row[3] for row in connection.execute("PRAGMA table_info(asset_embeddings)")}
        indexes = {row[1]: row[2] for row in connection.execute("PRAGMA index_list(asset_embeddings)")}
        index_columns = [row[2] for row in connection.execute("PRAGMA index_info(ix_asset_embeddings_space_asset)")]
        vec_tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'asset_embedding_vec%'"
        ).fetchall()
    assert rows == [
        ("emb_1", "asset_1", "jina", "vec:1", 768, "legacy:jina/768"),
        ("emb_2", "asset_2", "mock", "vec:2", 8, "legacy:mock/8"),
    ]
    assert rows[0][5] == legacy_space_id("jina", 768)
    assert not_null["space_id"] == 1
    assert {"ix_asset_embeddings_asset_id", "ix_asset_embeddings_provider", "ix_asset_embeddings_space_asset"} <= set(
        indexes
    )
    assert index_columns == ["space_id", "asset_id"]
    assert vec_tables == []  # vec0 tables are created per space at runtime


@pytest.mark.parametrize("relative", [False, True])
def test_0009_rewrites_jina_to_custom_when_the_model_file_exists(tmp_path: Path, relative: bool) -> None:
    db_path = _database(tmp_path)
    model = _model_file(tmp_path / "data" / "models" / "mine.gguf")
    # Relative paths resolve against `data_dir.parent`, as the HTTP layer does.
    stored = "./data/models/mine.gguf" if relative else str(model)
    _seed_0008(db_path, settings={"embeddings_provider": "jina", "jina_model_path": stored, "worker_concurrency": 1})

    command.upgrade(_config(db_path), "head")

    values = _settings(db_path)
    assert values["embeddings_provider"] == "custom"
    assert values["custom_model_path"] == stored
    assert "jina_model_path" not in values
    assert values["worker_concurrency"] == 1
    assert _settings_revision(db_path) == 4


def test_0009_rewrites_jina_to_disabled_when_the_model_file_is_missing(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    missing = str(tmp_path / "data" / "models" / "gone.gguf")
    _seed_0008(db_path, settings={"embeddings_provider": "jina", "jina_model_path": missing})

    command.upgrade(_config(db_path), "head")

    values = _settings(db_path)
    assert values["embeddings_provider"] == "disabled"
    assert values["custom_model_path"] == missing
    assert "jina_model_path" not in values
    assert _settings_revision(db_path) == 4


def test_0009_uses_the_registry_default_path_when_no_path_row_exists(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    _model_file(tmp_path / "data" / "models" / "jina-v5-omni-nano.gguf")
    _seed_0008(db_path, settings={"embeddings_provider": "jina"})

    command.upgrade(_config(db_path), "head")

    values = _settings(db_path)
    assert values["embeddings_provider"] == "custom"
    assert "custom_model_path" not in values and "jina_model_path" not in values


def test_0009_honours_the_model_path_env_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _database(tmp_path)
    model = _model_file(tmp_path / "elsewhere" / "model.gguf")
    _seed_0008(db_path, settings={"embeddings_provider": "jina", "jina_model_path": str(tmp_path / "missing.gguf")})
    monkeypatch.setenv("JINA_MODEL_PATH", str(model))

    command.upgrade(_config(db_path), "head")

    assert _settings(db_path)["embeddings_provider"] == "custom"


def test_0009_leaves_other_providers_and_the_revision_alone(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    _seed_0008(db_path, settings={"embeddings_provider": "mock", "ocr_provider": "rapidocr"})

    command.upgrade(_config(db_path), "head")

    assert _settings(db_path) == {"embeddings_provider": "mock", "ocr_provider": "rapidocr"}
    assert _settings_revision(db_path) == 3


def test_0009_new_tables_accept_rows(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    _seed_0008(db_path, settings={})
    command.upgrade(_config(db_path), "head")
    factory = create_session_factory(sqlite_url(db_path))

    with session_scope(factory) as session:
        status = session.get(SmartSearchStatusModel, 1)
        assert status is not None
        assert (status.state, status.space_id, status.bytes_done, status.bytes_total) == ("off", None, 0, 0)
        assert (status.waiting_network, status.was_ready, status.error_code, status.failed_step) == (
            False,
            False,
            None,
            None,
        )
        status.state = "downloading"
        status.space_id = SPACE
        status.bytes_total = 309_855_456
        status.bytes_done = 104_857_600
        status.updated_at = NOW
        session.add(
            AssetEmbeddingChunkModel(
                space_id=SPACE, asset_id="asset_1", chunk_no=0, page=1, vector=b"\x00" * 2048, created_at=NOW
            )
        )
        session.add(
            AssetEmbeddingChunkModel(
                space_id=SPACE, asset_id="asset_1", chunk_no=1, page=None, vector=b"\x01" * 2048, created_at=NOW
            )
        )
        session.add(
            EmbeddingSpaceModel(
                id=SPACE,
                model_id="embeddinggemma-2-q8_0",
                revision="6ea3e3a309d12a4779cfda98b8c19800d2d5da71",
                dims=512,
                modalities=["text"],
                state="active",
                created_at=NOW,
                activated_at=NOW,
            )
        )
        session.add(
            ModelInstallModel(
                model_id="embeddinggemma-2-q8_0",
                revision="6ea3e3a309d12a4779cfda98b8c19800d2d5da71",
                file="embeddinggemma-2-Q8_0.gguf",
                bytes_total=309_855_456,
                sha256="c" * 64,
                state="downloading",
                updated_at=NOW,
            )
        )
        # Writers that predate spaces still get a legacy space id.
        session.add(
            AssetEmbeddingModel(
                id="emb_3", asset_id="asset_2", provider="mock", vector_ref="vec:3", dimensions=8, created_at=NOW
            )
        )

    with session_scope(factory) as session:
        chunks = session.scalars(
            select(AssetEmbeddingChunkModel).order_by(AssetEmbeddingChunkModel.chunk_no)
        ).all()
        assert [(chunk.chunk_no, chunk.page, len(chunk.vector)) for chunk in chunks] == [(0, 1, 2048), (1, None, 2048)]
        space = session.get(EmbeddingSpaceModel, SPACE)
        assert space is not None and space.modalities == ["text"] and space.state == "active"
        install = session.get(
            ModelInstallModel,
            ("embeddinggemma-2-q8_0", "6ea3e3a309d12a4779cfda98b8c19800d2d5da71", "embeddinggemma-2-Q8_0.gguf"),
        )
        assert install is not None and install.bytes_done == 0 and install.error_code is None
        status = session.get(SmartSearchStatusModel, 1)
        assert status is not None and status.state == "downloading" and status.bytes_done == 104_857_600
        legacy = session.get(AssetEmbeddingModel, "emb_3")
        assert legacy is not None and legacy.space_id == "legacy:mock/8"

    with pytest.raises(IntegrityError):  # at most one active space
        with session_scope(factory) as session:
            session.add(
                EmbeddingSpaceModel(
                    id="qwen3-embedding-0.6b-q8_0@370f27d7550e0def9b39c1f16d3fbaa13aa67728/1024",
                    model_id="qwen3-embedding-0.6b-q8_0",
                    revision="370f27d7550e0def9b39c1f16d3fbaa13aa67728",
                    dims=1024,
                    modalities=["text"],
                    state="active",
                    created_at=NOW,
                )
            )
    with session_scope(factory) as session:  # any number of building/retired spaces
        for dims, state in ((256, "building"), (128, "retired"), (768, "retired")):
            session.add(
                EmbeddingSpaceModel(
                    id=f"embeddinggemma-2-q8_0@6ea3e3a309d12a4779cfda98b8c19800d2d5da71/{dims}",
                    model_id="embeddinggemma-2-q8_0",
                    revision="6ea3e3a309d12a4779cfda98b8c19800d2d5da71",
                    dims=dims,
                    modalities=["text"],
                    state=state,
                    created_at=NOW,
                )
            )
    with pytest.raises(IntegrityError):  # chunk primary key
        with session_scope(factory) as session:
            session.add(
                AssetEmbeddingChunkModel(
                    space_id=SPACE, asset_id="asset_1", chunk_no=0, page=1, vector=b"\x02", created_at=NOW
                )
            )

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("DELETE FROM assets WHERE id = 'asset_1'")
        assert connection.execute("SELECT COUNT(*) FROM asset_embedding_chunks").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM asset_embeddings WHERE asset_id = 'asset_1'").fetchone() == (0,)


def test_0009_is_idempotent_with_the_startup_path(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    model = _model_file(tmp_path / "data" / "models" / "mine.gguf")
    _seed_0008(db_path, settings={"embeddings_provider": "jina", "jina_model_path": str(model)})
    settings = Settings(data_dir=str(tmp_path / "data"))
    head = head_revision(default_migrations_dir())

    first = run_migrations(settings)
    assert first.ran and first.from_revision == BEFORE and first.to_revision == head
    after_first = (_settings(db_path), _settings_revision(db_path))
    assert after_first == ({"embeddings_provider": "custom", "custom_model_path": str(model)}, 4)

    second = run_migrations(settings)
    assert not second.ran and second.from_revision == head
    command.upgrade(_config(db_path), "head")
    assert current_revision(db_path) == head
    assert (_settings(db_path), _settings_revision(db_path)) == after_first
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM smart_search_status").fetchone() == (1,)
        assert connection.execute("SELECT space_id FROM asset_embeddings ORDER BY id").fetchall() == [
            ("legacy:jina/768",),
            ("legacy:mock/8",),
        ]


def test_0009_downgrades_to_the_jina_names_and_upgrades_again(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    model = _model_file(tmp_path / "data" / "models" / "mine.gguf")
    _seed_0008(db_path, settings={"embeddings_provider": "jina", "jina_model_path": str(model)})
    config = _config(db_path)
    command.upgrade(config, "head")

    command.downgrade(config, BEFORE)

    assert "space_id" not in _columns(db_path, "asset_embeddings")
    with sqlite3.connect(db_path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert connection.execute("SELECT id, vector_ref FROM asset_embeddings ORDER BY id").fetchall() == [
            ("emb_1", "vec:1"),
            ("emb_2", "vec:2"),
        ]
    assert not {"asset_embedding_chunks", "embedding_spaces", "model_installs", "smart_search_status"} & tables
    assert _settings(db_path) == {"embeddings_provider": "jina", "jina_model_path": str(model)}

    command.upgrade(config, "head")

    assert _settings(db_path) == {"embeddings_provider": "custom", "custom_model_path": str(model)}
