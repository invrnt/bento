from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


SessionFactoryHook = Callable[[sessionmaker[Session]], None]
_session_factory_hooks: list[SessionFactoryHook] = []


def add_session_factory_hook(hook: SessionFactoryHook) -> None:
    """Run `hook` on every session factory created afterwards in this process (sync change capture)."""
    if hook not in _session_factory_hooks:
        _session_factory_hooks.append(hook)


def remove_session_factory_hook(hook: SessionFactoryHook) -> None:
    if hook in _session_factory_hooks:
        _session_factory_hooks.remove(hook)


def sqlite_url(path: Path | str) -> str:
    resolved = Path(path).resolve()
    return f"sqlite:///{resolved.as_posix()}"


def create_sqlite_engine(database_url: str, *, echo: bool = False) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, echo=echo, future=True, connect_args=connect_args)

    if database_url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)

    return engine


def create_session_factory(database_url: str, *, echo: bool = False) -> sessionmaker[Session]:
    engine = create_sqlite_engine(database_url, echo=echo)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    for hook in tuple(_session_factory_hooks):
        hook(factory)
    return factory


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _enable_sqlite_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
    del connection_record
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()
