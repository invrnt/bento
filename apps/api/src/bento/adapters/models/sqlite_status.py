"""SQLite persistence for the smart search status row and per-file model installs.

Tables come from migration `0009_smart_search` (`smart_search_status`, single row `id = 1`; `model_installs`,
primary key `(model_id, revision, file)`). Lightweight Core tables keep this adapter independent of the ORM
classes. The API process and the worker both write the status row, so state changes are compare-and-set on
the fields a transition changes, and progress writes only touch the counters.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, and_, column, delete, insert, select, table, update
from sqlalchemy.orm import Session, sessionmaker

from bento.application.smart_search.activation import InstallState, ModelInstallRecord
from bento.domain.smart_search import SmartSearchErrorCode, SmartSearchState, SmartSearchStatus
from bento.infrastructure.db.engine import session_scope
from bento.ports.repositories import ClockPort

STATUS_ROW_ID = 1

_status = table(
    "smart_search_status",
    column("id", Integer),
    column("state", String),
    column("space_id", String),
    column("bytes_done", BigInteger),
    column("bytes_total", BigInteger),
    column("waiting_network", Boolean),
    column("indexed_done", Integer),
    column("indexed_total", Integer),
    column("error_code", String),
    column("failed_step", String),
    column("was_ready", Boolean),
    column("updated_at", DateTime(timezone=True)),
)

_installs = table(
    "model_installs",
    column("model_id", String),
    column("revision", String),
    column("file", String),
    column("bytes_total", BigInteger),
    column("bytes_done", BigInteger),
    column("sha256", String),
    column("state", String),
    column("error_code", String),
    column("updated_at", DateTime(timezone=True)),
)

_PROGRESS_STATES = (SmartSearchState.DOWNLOADING.value, SmartSearchState.PAUSED.value)


class SQLiteSmartSearchStatusRepository:
    def __init__(self, session_factory: sessionmaker[Session], clock: ClockPort) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def load(self) -> SmartSearchStatus:
        with session_scope(self._session_factory) as session:
            row = session.execute(select(_status).where(_status.c.id == STATUS_ROW_ID)).mappings().first()
        if row is None:
            return SmartSearchStatus()
        return _status_from_row(row)

    async def replace(self, expected: SmartSearchStatus, new: SmartSearchStatus) -> bool:
        """Write `new` only if the row still has `expected`'s state, space, error and network flag."""
        values = {**_status_values(new), "updated_at": self._clock.now()}
        with session_scope(self._session_factory) as session:
            self._ensure_row(session)
            result = session.execute(
                update(_status)
                .where(
                    and_(
                        _status.c.id == STATUS_ROW_ID,
                        _status.c.state == expected.state.value,
                        _null_safe_eq(_status.c.space_id, expected.space_id),
                        _null_safe_eq(_status.c.error_code, _code(expected.error_code)),
                        _status.c.waiting_network == expected.waiting_network,
                    )
                )
                .values(**values)
            )
            return result.rowcount == 1

    async def set_download_progress(self, space_id: str, bytes_done: int) -> bool:
        with session_scope(self._session_factory) as session:
            result = session.execute(
                update(_status)
                .where(
                    and_(
                        _status.c.id == STATUS_ROW_ID,
                        _status.c.space_id == space_id,
                        _status.c.state.in_(_PROGRESS_STATES),
                    )
                )
                .values(bytes_done=max(0, bytes_done), updated_at=self._clock.now())
            )
            return result.rowcount == 1

    async def set_index_progress(self, space_id: str, done: int, total: int) -> bool:
        total = max(0, total)
        with session_scope(self._session_factory) as session:
            result = session.execute(
                update(_status)
                .where(
                    and_(
                        _status.c.id == STATUS_ROW_ID,
                        _status.c.space_id == space_id,
                        _status.c.state == SmartSearchState.INDEXING.value,
                    )
                )
                .values(indexed_done=max(0, min(done, total)), indexed_total=total, updated_at=self._clock.now())
            )
            return result.rowcount == 1

    async def save_install(self, record: ModelInstallRecord) -> None:
        values = {
            "bytes_total": record.bytes_total,
            "bytes_done": record.bytes_done,
            "sha256": record.sha256,
            "state": record.state.value,
            "error_code": record.error_code,
            "updated_at": self._clock.now(),
        }
        key = and_(
            _installs.c.model_id == record.model_id,
            _installs.c.revision == record.revision,
            _installs.c.file == record.file,
        )
        with session_scope(self._session_factory) as session:
            result = session.execute(update(_installs).where(key).values(**values))
            if result.rowcount == 0:
                session.execute(
                    insert(_installs).values(
                        model_id=record.model_id, revision=record.revision, file=record.file, **values
                    )
                )

    async def installs(self) -> tuple[ModelInstallRecord, ...]:
        with session_scope(self._session_factory) as session:
            rows = session.execute(
                select(_installs).order_by(_installs.c.model_id, _installs.c.revision, _installs.c.file)
            ).mappings()
            return tuple(_install_from_row(row) for row in rows)

    async def delete_installs(self, model_id: str, revision: str | None = None) -> None:
        condition = _installs.c.model_id == model_id
        if revision is not None:
            condition = and_(condition, _installs.c.revision == revision)
        with session_scope(self._session_factory) as session:
            session.execute(delete(_installs).where(condition))

    def _ensure_row(self, session: Session) -> None:
        exists = session.execute(select(_status.c.id).where(_status.c.id == STATUS_ROW_ID)).first()
        if exists is None:
            session.execute(
                insert(_status).values(
                    id=STATUS_ROW_ID, **_status_values(SmartSearchStatus()), updated_at=self._clock.now()
                )
            )


def _null_safe_eq(col: object, value: object) -> object:
    return col.is_(None) if value is None else col == value  # type: ignore[attr-defined]


def _code(value: SmartSearchErrorCode | None) -> str | None:
    return value.value if value is not None else None


def _status_values(status: SmartSearchStatus) -> dict[str, object]:
    return {
        "state": status.state.value,
        "space_id": status.space_id,
        "bytes_done": status.bytes_done,
        "bytes_total": status.bytes_total,
        "waiting_network": status.waiting_network,
        "indexed_done": status.indexed_done,
        "indexed_total": status.indexed_total,
        "error_code": _code(status.error_code),
        "failed_step": status.failed_step.value if status.failed_step is not None else None,
        "was_ready": status.was_ready,
    }


def _status_from_row(row: object) -> SmartSearchStatus:
    data = dict(row)  # type: ignore[call-overload]
    try:
        state = SmartSearchState(data["state"])
        error_code = SmartSearchErrorCode(data["error_code"]) if data.get("error_code") else None
        failed_step = SmartSearchState(data["failed_step"]) if data.get("failed_step") else None
        return SmartSearchStatus(
            state=state,
            space_id=data.get("space_id"),
            bytes_done=int(data.get("bytes_done") or 0),
            bytes_total=int(data.get("bytes_total") or 0),
            waiting_network=bool(data.get("waiting_network")) and state is SmartSearchState.DOWNLOADING,
            indexed_done=int(data.get("indexed_done") or 0),
            indexed_total=int(data.get("indexed_total") or 0),
            error_code=error_code if state is SmartSearchState.ERROR else None,
            failed_step=failed_step,
            was_ready=bool(data.get("was_ready")),
        )
    except Exception:  # noqa: BLE001 - a corrupt row reads as `off`, never as a crash
        return SmartSearchStatus()


def _install_from_row(row: object) -> ModelInstallRecord:
    data = dict(row)  # type: ignore[call-overload]
    try:
        state = InstallState(data["state"])
    except ValueError:
        state = InstallState.ERROR
    return ModelInstallRecord(
        model_id=str(data["model_id"]),
        revision=str(data["revision"]),
        file=str(data["file"]),
        bytes_total=int(data["bytes_total"] or 0),
        bytes_done=int(data["bytes_done"] or 0),
        sha256=str(data["sha256"]),
        state=state,
        error_code=data.get("error_code"),
    )
