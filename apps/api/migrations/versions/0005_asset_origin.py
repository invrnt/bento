"""device-local asset provenance (assets.origin)

Revision ID: 0005_asset_origin
Revises: 0004_telegram_first

Telegram's API terms forbid feeding data obtained from Telegram to ML models, so OCR and embeddings must know
where an asset came from. `origin` is device-local (never synced): `device`, `telegram_inbox`, `telegram_import`,
or NULL for assets that arrived from another device (unknown provenance, never indexed locally).
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_asset_origin"
down_revision = "0004_telegram_first"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("assets") as batch:
        batch.add_column(sa.Column("origin", sa.String(length=32), nullable=True))
    # Existing libraries were built from the person's own uploads, except what the Inbox already imported.
    op.execute("UPDATE assets SET origin = 'device'")
    op.execute(
        "UPDATE assets SET origin = 'telegram_inbox' "
        "WHERE id IN (SELECT asset_id FROM inbox_items WHERE asset_id IS NOT NULL)"
    )


def downgrade() -> None:
    with op.batch_alter_table("assets") as batch:
        batch.drop_column("origin")
