"""android gaps: album covers and persisted content imports

Revision ID: 0008_android_gaps
Revises: 0007_android_device

`albums.cover_asset_id` is the cover chosen on this device. It is device-local: the Sync protocol's `album`
entity carries `title`, `created_at`, `deleted_at` only, and peers reject ops with unknown fields, so syncing it
needs a protocol revision (`architecture/telegram-first.md`). `content_imports` / `content_import_items` keep
Android fd imports (`api/android-endpoints.md` §4) across process restarts; the fds themselves cannot survive one,
so unfinished items of an earlier process are failed with `import_interrupted`. All device-local (never synced).
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_android_gaps"
down_revision = "0007_android_device"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("albums") as batch:
        batch.add_column(sa.Column("cover_asset_id", sa.String(length=64), nullable=True))
    op.create_table(
        "content_imports",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("folder_id", sa.String(length=64), nullable=True),
        sa.Column("album_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_content_imports_finished_at", "content_imports", ["finished_at"])
    op.create_table(
        "content_import_items",
        sa.Column(
            "import_id", sa.String(length=64), sa.ForeignKey("content_imports.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("client_index", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("asset_id", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("content_import_items")
    op.drop_index("ix_content_imports_finished_at", table_name="content_imports")
    op.drop_table("content_imports")
    with op.batch_alter_table("albums") as batch:
        batch.drop_column("cover_asset_id")
