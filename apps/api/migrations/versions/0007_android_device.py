"""android device: MediaStore backup sources and offline pins

Revision ID: 0007_android_device
Revises: 0006_sync_trust

`backup_sources.kind` (`folder` | `media_store`) and `bucket_id` let a phone back up MediaStore buckets;
`backup_files.source_key` keys their files by MediaStore id. `cache_entries.pinned` keeps "offline" originals
out of LRU eviction. All device-local (never synced).
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_android_device"
down_revision = "0006_sync_trust"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("backup_sources") as batch:
        batch.add_column(sa.Column("kind", sa.String(length=16), nullable=False, server_default="folder"))
        batch.add_column(sa.Column("bucket_id", sa.String(length=64), nullable=True))
    with op.batch_alter_table("backup_files") as batch:
        batch.add_column(sa.Column("source_key", sa.String(length=64), nullable=True))
        batch.create_index("ix_backup_files_source_key", ["source_id", "source_key"])
    with op.batch_alter_table("cache_entries") as batch:
        batch.add_column(sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    with op.batch_alter_table("cache_entries") as batch:
        batch.drop_column("pinned")
    with op.batch_alter_table("backup_files") as batch:
        batch.drop_index("ix_backup_files_source_key")
        batch.drop_column("source_key")
    with op.batch_alter_table("backup_sources") as batch:
        batch.drop_column("bucket_id")
        batch.drop_column("kind")
