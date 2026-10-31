"""sync trust: blob ciphertext binding and device review state

Revision ID: 0006_sync_trust
Revises: 0005_asset_origin

`blob_refs.cipher_header_sha256` (synced) is the b64url SHA-256 of a remote blob's 36-byte v2 header; downloads
and range reads verify it, so a ciphertext cannot be swapped for another file sealed with the same keys.
`devices.introduced_by`, `first_seen_at`, and `reviewed_at` are device-local: rows first seen through sync are
shown for review in Activity until acknowledged. Existing rows count as reviewed.
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_sync_trust"
down_revision = "0005_asset_origin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("blob_refs") as batch:
        batch.add_column(sa.Column("cipher_header_sha256", sa.String(length=64), nullable=True))
    with op.batch_alter_table("devices") as batch:
        batch.add_column(sa.Column("introduced_by", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE devices SET first_seen_at = added_at, reviewed_at = added_at")


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.drop_column("reviewed_at")
        batch.drop_column("first_seen_at")
        batch.drop_column("introduced_by")
    with op.batch_alter_table("blob_refs") as batch:
        batch.drop_column("cipher_header_sha256")
