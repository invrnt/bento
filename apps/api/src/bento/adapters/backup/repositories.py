"""SQLite repositories for backup sources, per-file state, policy, and backup-related job queries."""

from __future__ import annotations

import json
import stat as stat_module
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from bento.adapters.backup.pipeline import ACTIVE_JOB_STATUSES, job_payload_value
from bento.adapters.repositories.mappers import aware, require_aware
from bento.adapters.settings import SQLiteSettingsRepository
from bento.domain.backup import BackupFile, BackupFileState, BackupPolicy, BackupSource
from bento.domain.errors import SettingsRevisionConflictError, SettingsSourceLockedError
from bento.domain.jobs import JobStatus, JobType
from bento.infrastructure.db.engine import session_scope
from bento.infrastructure.db.models import (
    BackupFileModel,
    BackupSourceModel,
    FolderModel,
    JobModel,
    SyncStateModel,
)
from bento.ports.repositories import ClockPort

POLICY_PAUSED_KEY = "backup.paused"
POLICY_ON_BATTERY_KEY = "backup.on_battery"
PAUSE_ON_BATTERY_SETTING = "backup_pause_on_battery"
BANDWIDTH_SETTING = "backup_bandwidth_limit_kbps"
_PENDING_STATES = (BackupFileState.PENDING.value, BackupFileState.UPLOADING.value)


class SQLiteBackupSourceRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def list(self) -> tuple[BackupSource, ...]:
        with session_scope(self._session_factory) as session:
            models = session.scalars(select(BackupSourceModel).order_by(BackupSourceModel.created_at, BackupSourceModel.id))
            return tuple(_source_from_model(model) for model in models)

    async def get(self, source_id: str) -> BackupSource | None:
        with session_scope(self._session_factory) as session:
            model = session.get(BackupSourceModel, source_id)
            return _source_from_model(model) if model is not None else None

    async def save(self, source: BackupSource) -> None:
        with session_scope(self._session_factory) as session:
            session.merge(
                BackupSourceModel(
                    id=source.id,
                    path=source.path,
                    label=source.label,
                    enabled=source.enabled,
                    created_at=source.created_at,
                    updated_at=source.updated_at,
                    last_scan_at=source.last_scan_at,
                    error_code=source.error_code,
                )
            )

    async def delete(self, source_id: str) -> None:
        with session_scope(self._session_factory) as session:
            session.execute(delete(BackupFileModel).where(BackupFileModel.source_id == source_id))
            session.execute(delete(BackupSourceModel).where(BackupSourceModel.id == source_id))


class SQLiteBackupFileRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def get(self, source_id: str, relative_path: str) -> BackupFile | None:
        with session_scope(self._session_factory) as session:
            model = session.get(BackupFileModel, (source_id, relative_path))
            return _file_from_model(model) if model is not None else None

    async def save(self, file: BackupFile) -> None:
        await self.save_many((file,))

    async def save_many(self, files: tuple[BackupFile, ...]) -> None:
        with session_scope(self._session_factory) as session:
            for file in files:
                session.merge(_file_to_model(file))

    async def pending(self, *, limit: int = 50) -> tuple[BackupFile, ...]:
        with session_scope(self._session_factory) as session:
            models = session.scalars(
                select(BackupFileModel)
                .join(BackupSourceModel, BackupSourceModel.id == BackupFileModel.source_id)
                .where(BackupFileModel.state.in_(_PENDING_STATES), BackupSourceModel.enabled.is_(True))
                .order_by(BackupFileModel.updated_at, BackupFileModel.source_id, BackupFileModel.relative_path)
                .limit(max(limit, 1))
            )
            return tuple(_file_from_model(model) for model in models)

    async def counts(self, source_id: str) -> dict[str, int]:
        with session_scope(self._session_factory) as session:
            rows = session.execute(
                select(BackupFileModel.state, func.count(), func.coalesce(func.sum(BackupFileModel.size_bytes), 0))
                .where(BackupFileModel.source_id == source_id)
                .group_by(BackupFileModel.state)
            ).all()
        result = {state.value: 0 for state in BackupFileState}
        bytes_pending = 0
        for state, count, size in rows:
            result[str(state)] = int(count)
            if state in _PENDING_STATES:
                bytes_pending += int(size)
        result["bytes_pending"] = bytes_pending
        return result

    async def snapshot(self, source_id: str) -> dict[str, BackupFile]:
        with session_scope(self._session_factory) as session:
            models = session.scalars(select(BackupFileModel).where(BackupFileModel.source_id == source_id))
            return {model.relative_path: _file_from_model(model) for model in models}

    async def delete_paths(self, source_id: str, relative_paths: tuple[str, ...], *, prefixes: tuple[str, ...] = ()) -> int:
        if not relative_paths and not prefixes:
            return 0
        conditions = [BackupFileModel.relative_path.in_(relative_paths)] if relative_paths else []
        conditions.extend(
            BackupFileModel.relative_path.startswith(f"{prefix.rstrip('/')}/", autoescape=True) for prefix in prefixes
        )
        with session_scope(self._session_factory) as session:
            result = session.execute(
                delete(BackupFileModel).where(BackupFileModel.source_id == source_id, or_(*conditions))
            )
            return int(result.rowcount or 0)


class SQLiteBackupPolicyRepository:
    """Policy = device state (`paused`, `on_battery` in `sync_state`) + live settings
    (`backup_pause_on_battery`, `backup_bandwidth_limit_kbps`), read on every call.

    `locked` holds values forced by the environment or policy; changing them raises `SettingsSourceLockedError`.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        clock: ClockPort,
        *,
        locked: Mapping[str, object] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._settings = SQLiteSettingsRepository(session_factory, clock)
        self._locked = dict(locked or {})

    async def get(self) -> BackupPolicy:
        persisted = await self._settings.load()
        with session_scope(self._session_factory) as session:
            state = {
                row.key: row.value
                for row in session.scalars(
                    select(SyncStateModel).where(SyncStateModel.key.in_((POLICY_PAUSED_KEY, POLICY_ON_BATTERY_KEY)))
                )
            }
        return BackupPolicy(
            paused=state.get(POLICY_PAUSED_KEY) == "1",
            pause_on_battery=_as_bool(self._setting(persisted.values, PAUSE_ON_BATTERY_SETTING), default=True),
            bandwidth_limit_kbps=_as_int(self._setting(persisted.values, BANDWIDTH_SETTING), default=0),
            on_battery=state.get(POLICY_ON_BATTERY_KEY) == "1",
        )

    async def save(self, policy: BackupPolicy) -> None:
        current = await self.get()
        wanted = {
            PAUSE_ON_BATTERY_SETTING: policy.pause_on_battery,
            BANDWIDTH_SETTING: policy.bandwidth_limit_kbps,
        }
        current_values = {
            PAUSE_ON_BATTERY_SETTING: current.pause_on_battery,
            BANDWIDTH_SETTING: current.bandwidth_limit_kbps,
        }
        changed = {key: value for key, value in wanted.items() if value != current_values[key]}
        locked = sorted(key for key in changed if key in self._locked)
        if locked:
            raise SettingsSourceLockedError(locked)
        if changed:
            await self._write_settings(changed)
        now = self._clock.now()
        with session_scope(self._session_factory) as session:
            for key, value in ((POLICY_PAUSED_KEY, policy.paused), (POLICY_ON_BATTERY_KEY, policy.on_battery)):
                session.merge(SyncStateModel(key=key, value="1" if value else "0", updated_at=now))

    def _setting(self, saved: Mapping[str, str], key: str) -> object:
        if key in self._locked:
            return self._locked[key]
        raw = saved.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    async def _write_settings(self, values: dict[str, object]) -> None:
        serialized = {key: json.dumps(value, separators=(",", ":")) for key, value in values.items()}
        for _ in range(3):
            revision = (await self._settings.load()).revision
            try:
                await self._settings.compare_and_set(expected_revision=revision, values=serialized, secret_references={})
                return
            except SettingsRevisionConflictError:
                continue
        raise SettingsRevisionConflictError(expected_revision=revision, current_revision=revision + 1)


class SQLiteBackupJobs:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def has_waiting(self, type: JobType, *, source_id: str | None = None) -> bool:
        statement = (
            select(func.count())
            .select_from(JobModel)
            .where(
                JobModel.type == type.value,
                JobModel.status.in_((JobStatus.QUEUED.value, JobStatus.RETRYING.value)),
            )
        )
        if source_id is not None:
            statement = statement.where(job_payload_value("source_id") == source_id)
        with session_scope(self._session_factory) as session:
            return bool(session.scalar(statement))

    async def has_parked_retry(self, source_id: str) -> bool:
        statement = (
            select(func.count())
            .select_from(JobModel)
            .where(
                JobModel.type == JobType.BACKUP_SCAN.value,
                JobModel.status == JobStatus.FAILED.value,
                JobModel.attempts < JobModel.max_attempts,
                job_payload_value("source_id") == source_id,
            )
        )
        with session_scope(self._session_factory) as session:
            return bool(session.scalar(statement))

    async def scanning_source_ids(self) -> set[str]:
        with session_scope(self._session_factory) as session:
            values = session.scalars(
                select(job_payload_value("source_id")).where(
                    JobModel.type == JobType.BACKUP_SCAN.value,
                    JobModel.status.in_(ACTIVE_JOB_STATUSES),
                )
            )
            return {str(value) for value in values if value}


class SQLiteFolderLookup:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def find_child(self, parent_id: str | None, name: str) -> str | None:
        with session_scope(self._session_factory) as session:
            return session.scalar(
                select(FolderModel.id)
                .where(
                    FolderModel.parent_id.is_(None) if parent_id is None else FolderModel.parent_id == parent_id,
                    FolderModel.name == name,
                    FolderModel.deleted_at.is_(None),
                )
                .order_by(FolderModel.created_at, FolderModel.id)
                .limit(1)
            )


class SQLiteBackupSourceLocator:
    """Finds the user's original file for a backed-up asset when it is unchanged since the backup."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def find_source(self, asset_id: str, size_bytes: int) -> Path | None:
        return self.find_sync(asset_id, size_bytes)

    def find_sync(self, asset_id: str, size_bytes: int) -> Path | None:
        with session_scope(self._session_factory) as session:
            rows = session.execute(
                select(BackupSourceModel.path, BackupFileModel.relative_path, BackupFileModel.size_bytes, BackupFileModel.mtime_ns)
                .join(BackupSourceModel, BackupSourceModel.id == BackupFileModel.source_id)
                .where(BackupFileModel.asset_id == asset_id, BackupFileModel.state == BackupFileState.DONE.value)
            ).all()
        for root, relative, recorded_size, recorded_mtime in rows:
            if recorded_size != size_bytes:
                continue
            candidate = _inside(Path(root), relative)
            if candidate is None:
                continue
            try:
                info = candidate.lstat()
            except OSError:
                continue
            if stat_module.S_ISREG(info.st_mode) and info.st_size == recorded_size and info.st_mtime_ns == recorded_mtime:
                return candidate
        return None


def _inside(root: Path, relative: str) -> Path | None:
    parts = PurePosixPath(relative).parts
    if not parts or any(part in {"", ".", ".."} for part in parts) or PurePosixPath(relative).is_absolute():
        return None
    return root.joinpath(*parts)


def _source_from_model(model: BackupSourceModel) -> BackupSource:
    return BackupSource(
        id=model.id,
        path=model.path,
        label=model.label,
        enabled=model.enabled,
        created_at=require_aware(model.created_at),
        updated_at=require_aware(model.updated_at),
        last_scan_at=aware(model.last_scan_at),
        error_code=model.error_code,
    )


def _file_from_model(model: BackupFileModel) -> BackupFile:
    return BackupFile(
        source_id=model.source_id,
        relative_path=model.relative_path,
        size_bytes=model.size_bytes,
        mtime_ns=model.mtime_ns,
        state=BackupFileState(model.state),
        updated_at=require_aware(model.updated_at),
        sha256=model.sha256,
        asset_id=model.asset_id,
        error_code=model.error_code,
    )


def _file_to_model(file: BackupFile) -> BackupFileModel:
    return BackupFileModel(
        source_id=file.source_id,
        relative_path=file.relative_path,
        size_bytes=file.size_bytes,
        mtime_ns=file.mtime_ns,
        sha256=file.sha256,
        asset_id=file.asset_id,
        state=file.state.value,
        error_code=file.error_code,
        updated_at=file.updated_at,
    )


def _as_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _as_int(value: object, *, default: int) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return max(int(float(str(value))), 0)
    except ValueError:
        return default
