"""Database engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_settings = get_settings()

connect_args = {"check_same_thread": False} if _settings.resolved_database_url.startswith(
    "sqlite"
) else {}

engine: Engine = create_engine(
    _settings.resolved_database_url,
    echo=False,
    connect_args=connect_args,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    # WAL improves concurrency between web + worker processes on SQLite.
    if _settings.resolved_database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def init_db() -> None:
    import app.models  # noqa: F401  ensure tables are registered

    SQLModel.metadata.create_all(engine)
    _ensure_columns()


# Columns added after the initial schema; create_all won't ALTER existing tables,
# so add them idempotently for SQLite databases created before the feature landed.
_ADDED_COLUMNS = {
    "item": {
        "is_favorite": "BOOLEAN NOT NULL DEFAULT 0",
        "is_archived": "BOOLEAN NOT NULL DEFAULT 0",
        "media_bytes": "INTEGER NOT NULL DEFAULT 0",
        "audio_duration_s": "FLOAT",
        "view_count": "INTEGER",
        "like_count": "INTEGER",
        "dislike_count": "INTEGER",
    },
}


def _ensure_columns() -> None:
    if not _settings.resolved_database_url.startswith("sqlite"):
        return
    from sqlalchemy import text

    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {
                row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))
            }
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
