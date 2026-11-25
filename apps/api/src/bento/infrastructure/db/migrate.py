"""Schema migrations without the desktop launcher.

`run_migrations` upgrades the catalog to head. The at-head check reads `alembic_version` with plain `sqlite3`
and the head revision from the migration files, so alembic (and mako) are imported only when an upgrade is
actually pending. `migrations_dir` may live anywhere: the source tree (`apps/api/migrations`), PyInstaller's
bundle, or a directory an embedded host extracted (Android).
"""

from __future__ import annotations

import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bento.infrastructure.settings import Settings

# Same layout `make setup` creates (see scripts/doctor), so `make doctor` accepts launcher-created data directories.
DATA_DIR_LAYOUT = ("db", "cache", "uploads", "models", "journal", "config")
_REVISION = re.compile(r"""^revision\s*(?::\s*[\w\[\], |]+)?=\s*["']([^"']+)["']""", re.MULTILINE)
_DOWN_REVISION = re.compile(r"""^down_revision\s*(?::\s*[\w\[\], |]+)?=\s*(None|["']([^"']+)["'])""", re.MULTILINE)


class MigrationLayoutError(RuntimeError):
    """The migrations directory is missing or its revision graph has no single head."""


@dataclass(frozen=True, slots=True)
class MigrationResult:
    from_revision: str | None
    to_revision: str
    ran: bool
    ms: float

    def as_dict(self) -> dict[str, object]:
        return {"from": self.from_revision, "to": self.to_revision, "ran": self.ran, "ms": self.ms}


def bundle_root() -> Path:
    """`apps/api` in a source checkout, or PyInstaller's extraction directory in a frozen build."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root is not None:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[4]


def default_migrations_dir() -> Path:
    return bundle_root() / "migrations"


def head_revision(migrations_dir: Path) -> str:
    """The single head of the revision graph, parsed from `versions/*.py` without importing alembic."""
    versions = migrations_dir / "versions"
    if not versions.is_dir():
        raise MigrationLayoutError(f"No migrations under {migrations_dir}")
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in versions.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        revision = _REVISION.search(text)
        if revision is None:
            continue
        revisions.add(revision.group(1))
        down = _DOWN_REVISION.search(text)
        if down is not None and down.group(2):
            parents.add(down.group(2))
    heads = revisions - parents
    if len(heads) != 1:
        raise MigrationLayoutError(f"Expected one migration head, found {sorted(heads)}")
    return heads.pop()


def current_revision(database_path: Path) -> str | None:
    """The catalog's `alembic_version`, or None for a new or unversioned database."""
    if not database_path.is_file():
        return None
    try:
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    return str(row[0]) if row else None


def prepare_data_dir(settings: Settings) -> Path:
    from bento.infrastructure.settings import settings_database_path

    database_path = settings_database_path(settings)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    for child in DATA_DIR_LAYOUT:
        (Path(settings.data_dir) / child).mkdir(parents=True, exist_ok=True)
    return database_path


def run_migrations(settings: Settings, *, migrations_dir: Path | None = None) -> MigrationResult:
    """Upgrade the catalog of `settings` to head; a fast no-op (no alembic import) when already there."""
    started = time.perf_counter()
    script_location = migrations_dir or default_migrations_dir()
    database_path = prepare_data_dir(settings)
    head = head_revision(script_location)
    before = current_revision(database_path)
    if before == head:
        return MigrationResult(before, head, False, _elapsed_ms(started))

    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import URL

    # Programmatic configuration: no alembic.ini (and no logging fileConfig) is needed on any platform.
    config = Config()
    config.set_main_option("script_location", str(script_location))
    config.set_main_option(
        "sqlalchemy.url",
        URL.create("sqlite+pysqlite", database=str(database_path)).render_as_string(hide_password=False),
    )
    command.upgrade(config, "head")
    after = current_revision(database_path)
    if after != head:
        raise MigrationLayoutError(f"Upgrade stopped at {after!r}, expected {head!r}")
    return MigrationResult(before, head, True, _elapsed_ms(started))


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
