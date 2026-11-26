"""smart search: embedding spaces, chunk vectors, model installs, runtime status, settings rewrite

Revision ID: 0009_smart_search
Revises: 0008_android_gaps

Contract: `orchestration/api/smart-search-contract.md` §Migration plan. Every stored vector now carries the
embedding space it belongs to; vectors written before this revision keep their rows and become
`legacy:<provider>/<dims>` (`legacy_space_id`). `vec0` tables are not created here: their dimension is part of
the DDL, so the runtime creates `asset_embedding_vec_<sha256(space_id)[:8]>` per space.

Settings: `embeddings_provider = jina` becomes `custom` when the configured model file exists (the same path the
app would have used: env alias, then the stored row, then the registry default; relative paths are tried against
the data directory's parent, like the HTTP layer, and against the working directory, like the worker), otherwise
`disabled`. The `jina_model_path` row is renamed to `custom_model_path`. All new tables are device-local.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import sqlalchemy as sa
from alembic import op

from bento.domain.smart_search import legacy_space_id, migrate_embeddings_provider

revision = "0009_smart_search"
down_revision = "0008_android_gaps"
branch_labels = None
depends_on = None

_PROVIDER_KEY = "embeddings_provider"
_OLD_PATH_KEY = "jina_model_path"
_NEW_PATH_KEY = "custom_model_path"
# Snapshot of the 0008-era registry entry for `jina_model_path` (env aliases in precedence order, default).
_OLD_PATH_ENV_ALIASES = ("JINA_MODEL_PATH", "BENTO_EMBEDDING_MODEL_PATH")
_OLD_PATH_DEFAULT = "./data/models/jina-v5-omni-nano.gguf"
# Providers the 0008-era registry accepts, for downgrade.
_OLD_PROVIDERS = ("disabled", "mock", "jina")


def upgrade() -> None:
    bind = op.get_bind()

    with op.batch_alter_table("asset_embeddings") as batch:
        batch.add_column(sa.Column("space_id", sa.String(length=160), nullable=True))
    rows = bind.execute(sa.text("SELECT id, provider, dimensions FROM asset_embeddings")).all()
    if rows:
        bind.execute(
            sa.text("UPDATE asset_embeddings SET space_id = :space_id WHERE id = :id"),
            [{"id": row[0], "space_id": legacy_space_id(str(row[1] or ""), int(row[2]))} for row in rows],
        )
    with op.batch_alter_table("asset_embeddings") as batch:
        batch.alter_column("space_id", existing_type=sa.String(length=160), nullable=False)
    op.create_index("ix_asset_embeddings_space_asset", "asset_embeddings", ["space_id", "asset_id"])

    op.create_table(
        "asset_embedding_chunks",
        sa.Column("space_id", sa.String(length=160), primary_key=True),
        sa.Column("asset_id", sa.String(length=64), sa.ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("chunk_no", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("vector", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_asset_embedding_chunks_asset_id", "asset_embedding_chunks", ["asset_id"])

    op.create_table(
        "embedding_spaces",
        sa.Column("id", sa.String(length=160), primary_key=True),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.String(length=64), nullable=False),
        sa.Column("dims", sa.Integer(), nullable=False),
        sa.Column("modalities", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ux_embedding_spaces_active",
        "embedding_spaces",
        ["state"],
        unique=True,
        sqlite_where=sa.text("state = 'active'"),
    )

    op.create_table(
        "model_installs",
        sa.Column("model_id", sa.String(length=64), primary_key=True),
        sa.Column("revision", sa.String(length=64), primary_key=True),
        sa.Column("file", sa.String(length=255), primary_key=True),
        sa.Column("bytes_total", sa.BigInteger(), nullable=False),
        sa.Column("bytes_done", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "smart_search_status",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default=sa.text("'off'")),
        sa.Column("space_id", sa.String(length=160), nullable=True),
        sa.Column("bytes_done", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("bytes_total", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("waiting_network", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("indexed_done", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("indexed_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_code", sa.String(length=16), nullable=True),
        sa.Column("failed_step", sa.String(length=16), nullable=True),
        sa.Column("was_ready", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("INSERT INTO smart_search_status (id, state, updated_at) VALUES (1, 'off', CURRENT_TIMESTAMP)")

    _rewrite_settings_up(bind)


def downgrade() -> None:
    _rewrite_settings_down(op.get_bind())
    op.drop_table("smart_search_status")
    op.drop_table("model_installs")
    op.drop_index("ux_embedding_spaces_active", table_name="embedding_spaces")
    op.drop_table("embedding_spaces")
    op.drop_index("ix_asset_embedding_chunks_asset_id", table_name="asset_embedding_chunks")
    op.drop_table("asset_embedding_chunks")
    op.drop_index("ix_asset_embeddings_space_asset", table_name="asset_embeddings")
    with op.batch_alter_table("asset_embeddings") as batch:
        batch.drop_column("space_id")


def _rewrite_settings_up(bind: sa.engine.Connection) -> None:
    values = _settings(bind)
    changed = False
    if _OLD_PATH_KEY in values:
        if _NEW_PATH_KEY not in values:
            bind.execute(
                sa.text("UPDATE settings SET key = :new, updated_at = CURRENT_TIMESTAMP WHERE key = :old"),
                {"new": _NEW_PATH_KEY, "old": _OLD_PATH_KEY},
            )
        else:
            bind.execute(sa.text("DELETE FROM settings WHERE key = :old"), {"old": _OLD_PATH_KEY})
        changed = True
    if _PROVIDER_KEY in values:
        current = str(_decode(values[_PROVIDER_KEY]))
        stored_path = values.get(_NEW_PATH_KEY, values.get(_OLD_PATH_KEY))
        migrated = migrate_embeddings_provider(
            current, current == "jina" and _model_file_exists(bind, _configured_model_path(stored_path))
        )
        if migrated != current:
            _set(bind, _PROVIDER_KEY, migrated)
            changed = True
    if changed:
        _bump_settings_revision(bind)


def _rewrite_settings_down(bind: sa.engine.Connection) -> None:
    values = _settings(bind)
    changed = False
    if _NEW_PATH_KEY in values:
        bind.execute(sa.text("DELETE FROM settings WHERE key = :old"), {"old": _OLD_PATH_KEY})
        bind.execute(
            sa.text("UPDATE settings SET key = :old, updated_at = CURRENT_TIMESTAMP WHERE key = :new"),
            {"new": _NEW_PATH_KEY, "old": _OLD_PATH_KEY},
        )
        changed = True
    if _PROVIDER_KEY in values:
        current = str(_decode(values[_PROVIDER_KEY]))
        restored = "jina" if current == "custom" else current if current in _OLD_PROVIDERS else "disabled"
        if restored != current:
            _set(bind, _PROVIDER_KEY, restored)
            changed = True
    if changed:
        _bump_settings_revision(bind)


def _settings(bind: sa.engine.Connection) -> dict[str, str]:
    return {str(key): str(value) for key, value in bind.execute(sa.text("SELECT key, value FROM settings")).all()}


def _decode(raw: str) -> object:
    # Same encoding as `serialize_setting_value` (compact JSON), with the same raw-string fallback on read.
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _set(bind: sa.engine.Connection, key: str, value: str) -> None:
    bind.execute(
        sa.text("UPDATE settings SET value = :value, updated_at = CURRENT_TIMESTAMP WHERE key = :key"),
        {"key": key, "value": json.dumps(value, separators=(",", ":"), ensure_ascii=False)},
    )


def _bump_settings_revision(bind: sa.engine.Connection) -> None:
    # Clients holding the old revision must reload before they can save over the rewritten rows.
    bind.execute(
        sa.text("UPDATE settings_meta SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = 1")
    )


def _configured_model_path(stored: str | None) -> str:
    for alias in _OLD_PATH_ENV_ALIASES:
        raw = os.environ.get(alias, "").strip()
        if raw:
            return raw
    if stored is not None:
        value = str(_decode(stored) or "").strip()
        if value:
            return value
    return _OLD_PATH_DEFAULT


def _model_file_exists(bind: sa.engine.Connection, configured: str) -> bool:
    path = Path(configured).expanduser()
    candidates = [path]
    if not path.is_absolute():
        database = bind.engine.url.database
        if database and database != ":memory:" and not database.startswith("file:"):
            # `<data_dir>/db/bento.sqlite3`; the HTTP layer resolves relative model paths against `data_dir.parent`.
            data_dir = Path(database).resolve().parent.parent
            candidates.insert(0, data_dir.parent / path)
    try:
        return any(candidate.is_file() for candidate in candidates)
    except OSError:
        return False
