from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session, sessionmaker

from bento.domain.assets import Asset, AssetKind, AssetMetadata, AssetMode, ProcessingState
from bento.infrastructure.db.engine import create_session_factory, create_sqlite_engine, sqlite_url

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
SHA = "a" * 64


@dataclass
class FixedClock:
    current: datetime = NOW

    def now(self) -> datetime:
        return self.current


def migrated_session_factory(tmp_path: Path, *, session_hooks: bool = True) -> sessionmaker[Session]:
    """A migrated database. `session_hooks=False` skips process-wide factory hooks (change capture installed by
    an app created earlier in the test process), so the caller can install capture with its own clock."""
    db_path = tmp_path / "bento.sqlite3"
    api_root = Path(__file__).parents[3]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "migrations"))
    config.set_main_option("sqlalchemy.url", sqlite_url(db_path))
    command.upgrade(config, "head")
    if not session_hooks:
        return sessionmaker(bind=create_sqlite_engine(sqlite_url(db_path)), autoflush=False, expire_on_commit=False)
    return create_session_factory(sqlite_url(db_path))


def make_asset(
    asset_id: str = "asset_1",
    *,
    filename: str = "receipt.pdf",
    sha256: str = SHA,
    folder_id: str | None = None,
    kind: AssetKind = AssetKind.PDF,
    mode: AssetMode = AssetMode.DRIVE,
) -> Asset:
    return Asset(
        id=asset_id,
        kind=kind,
        mode=mode,
        folder_id=folder_id,
        filename=filename,
        metadata=AssetMetadata(
            original_filename=filename,
            mime_type="application/pdf" if kind == AssetKind.PDF else "image/jpeg",
            size_bytes=128,
            sha256=sha256,
            exif={"camera": "test"} if kind == AssetKind.IMAGE else None,
        ),
        processing_state=ProcessingState.INDEXED,
        favorite=False,
        created_at=NOW,
        updated_at=NOW,
    )
