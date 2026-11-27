"""document text without OCR: queue a one-off text extraction for the existing library

Revision ID: 0010_text_extraction_backfill
Revises: 0009_smart_search

No schema change: extracted text lives in `asset_text` with `source = 'document'`. Assets uploaded before this
revision never had their text read, so this queues one `reindex` job with `payload.text_only`, which pages through
this device's own files (like any `reindex`) and queues `text_extract` for plain text files and PDFs. Each
extraction that finds text then queues the asset's embedding refresh. Nothing is queued on a device with no such
file. Downgrade removes the job if it has not run yet; text already extracted stays (it is ordinary index data).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0010_text_extraction_backfill"
down_revision = "0009_smart_search"
branch_labels = None
depends_on = None

BACKFILL_JOB_PREFIX = "job_textbackfill_"
# Snapshot of `domain.indexing.TEXT_EXTRACTION_MIME_TYPES` and of `JobPriority.METADATA` at this revision.
_MIME_TYPES = ("text/plain", "text/markdown", "text/csv", "application/pdf")
_REINDEX_PRIORITY = 2

_jobs = sa.table(
    "jobs",
    sa.column("id", sa.String),
    sa.column("type", sa.String),
    sa.column("status", sa.String),
    sa.column("priority", sa.Integer),
    sa.column("payload", sa.JSON),
    sa.column("attempts", sa.Integer),
    sa.column("max_attempts", sa.Integer),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    bind = op.get_bind()
    placeholders = ", ".join(f":mime{index}" for index in range(len(_MIME_TYPES)))
    # `mime_type` may carry parameters (`text/plain; charset=utf-8`): compare the part before `;`.
    eligible = bind.execute(
        sa.text(
            "SELECT 1 FROM assets WHERE deleted_at IS NULL AND origin = 'device' AND "
            "lower(trim(CASE WHEN instr(mime_type, ';') > 0 THEN substr(mime_type, 1, instr(mime_type, ';') - 1) "
            f"ELSE mime_type END)) IN ({placeholders}) LIMIT 1"
        ),
        {f"mime{index}": mime for index, mime in enumerate(_MIME_TYPES)},
    ).first()
    if eligible is None:
        return
    now = datetime.now(UTC)
    op.bulk_insert(
        _jobs,
        [
            {
                "id": f"{BACKFILL_JOB_PREFIX}{uuid.uuid4().hex}",
                "type": "reindex",
                "status": "queued",
                "priority": _REINDEX_PRIORITY,
                "payload": {"text_only": True},
                "attempts": 0,
                "max_attempts": 3,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM jobs WHERE id LIKE :prefix AND status IN ('queued', 'retrying')").bindparams(
            prefix=f"{BACKFILL_JOB_PREFIX}%"
        )
    )
