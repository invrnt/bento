"""telegram-first vault, sync, devices, backup, cache, and inbox tables

Revision ID: 0004_telegram_first
Revises: 0003_versioned_settings
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_telegram_first"
down_revision = "0003_versioned_settings"
branch_labels = None
depends_on = None


def _timestamp(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    with op.batch_alter_table("blob_refs") as batch:
        batch.add_column(sa.Column("key_epoch", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("format_version", sa.Integer(), nullable=False, server_default=sa.text("1")))
        batch.add_column(_timestamp("remote_deleted_at", nullable=True))

    op.create_table(
        "blob_parts",
        sa.Column(
            "blob_ref_id",
            sa.String(length=64),
            sa.ForeignKey("blob_refs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("part_index", sa.Integer(), primary_key=True),
        sa.Column("channel_id", sa.String(length=128), nullable=False),
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
    )

    op.create_table(
        "sync_outbox",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("op_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("hlc", sa.String(length=96), nullable=False),
        sa.Column("entity", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        _timestamp("created_at"),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "sync_field_clocks",
        sa.Column("entity", sa.String(length=32), primary_key=True),
        sa.Column("entity_id", sa.String(length=160), primary_key=True),
        sa.Column("field", sa.String(length=64), primary_key=True),
        sa.Column("hlc", sa.String(length=96), nullable=False),
    )
    op.create_table(
        "sync_purged",
        sa.Column("entity", sa.String(length=32), primary_key=True),
        sa.Column("entity_id", sa.String(length=160), primary_key=True),
        sa.Column("hlc", sa.String(length=96), nullable=False),
        _timestamp("purged_at"),
    )
    op.create_table(
        "sync_applied_batches",
        sa.Column("batch_id", sa.String(length=64), primary_key=True),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        _timestamp("applied_at"),
    )
    op.create_table(
        "sync_state",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        _timestamp("updated_at"),
    )

    op.create_table(
        "devices",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("public_key", sa.String(length=128), nullable=False),
        sa.Column("telegram_auth_hash", sa.BigInteger(), nullable=True),
        _timestamp("added_at"),
        _timestamp("last_seen_at", nullable=True),
        _timestamp("removed_at", nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )

    op.create_table(
        "backup_sources",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("path", sa.String(length=4096), nullable=False, unique=True),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _timestamp("last_scan_at", nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
    )
    op.create_table(
        "backup_files",
        sa.Column(
            "source_id",
            sa.String(length=64),
            sa.ForeignKey("backup_sources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("relative_path", sa.String(length=4096), primary_key=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mtime_ns", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("asset_id", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        _timestamp("updated_at"),
    )
    op.create_index("ix_backup_files_state", "backup_files", ["state"])

    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("asset_id", sa.String(length=64), nullable=True),
        sa.Column("blob_ref_id", sa.String(length=64), nullable=True),
        sa.Column("source_path", sa.String(length=4096), nullable=False),
        sa.Column("blob_kind", sa.String(length=32), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("file_salt", sa.LargeBinary(length=16), nullable=False),
        sa.Column("nonce_prefix", sa.LargeBinary(length=7), nullable=False),
        sa.Column("segment_size", sa.Integer(), nullable=False),
        sa.Column("plaintext_size", sa.BigInteger(), nullable=False),
        sa.Column("ciphertext_size", sa.BigInteger(), nullable=False),
        sa.Column("completed_parts", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
    )

    op.create_table(
        "cache_entries",
        sa.Column("blob_ref_id", sa.String(length=64), primary_key=True),
        sa.Column("path", sa.String(length=4096), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        _timestamp("last_accessed_at"),
    )
    op.create_index("ix_cache_entries_last_accessed_at", "cache_entries", ["last_accessed_at"])

    op.create_table(
        "inbox_items",
        sa.Column("message_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("asset_id", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
    )


def downgrade() -> None:
    op.drop_table("inbox_items")
    op.drop_index("ix_cache_entries_last_accessed_at", table_name="cache_entries")
    op.drop_table("cache_entries")
    op.drop_table("upload_sessions")
    op.drop_index("ix_backup_files_state", table_name="backup_files")
    op.drop_table("backup_files")
    op.drop_table("backup_sources")
    op.drop_table("devices")
    op.drop_table("sync_state")
    op.drop_table("sync_applied_batches")
    op.drop_table("sync_purged")
    op.drop_table("sync_field_clocks")
    op.drop_table("sync_outbox")
    op.drop_table("blob_parts")
    with op.batch_alter_table("blob_refs") as batch:
        batch.drop_column("remote_deleted_at")
        batch.drop_column("format_version")
        batch.drop_column("key_epoch")
