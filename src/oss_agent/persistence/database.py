"""Database engine and session management.

Kept intentionally thin so the persistence backend (SQLite now, PostgreSQL later)
can change without touching the repository or the rest of the app.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from oss_agent.persistence.orm import Base


def _prepare_sqlite_path(database_url: str) -> None:
    if database_url.startswith("sqlite:///"):
        raw = database_url.replace("sqlite:///", "", 1)
        if raw and raw != ":memory:":
            parent = Path(raw).parent
            if str(parent) not in ("", "."):
                parent.mkdir(parents=True, exist_ok=True)


class Database:
    """Owns the engine + session factory and creates the schema."""

    def __init__(self, url: str = "sqlite:///.oss-agent/oss_agent.db", *, echo: bool = False) -> None:
        self.url = url
        _prepare_sqlite_path(url)
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(url, echo=echo, future=True, connect_args=connect_args)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.create_all()

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def drop_all(self) -> None:
        Base.metadata.drop_all(self.engine)

    def session(self) -> Session:
        return self._session_factory()

    def dispose(self) -> None:
        self.engine.dispose()


def in_memory_database() -> Database:
    """A throwaway SQLite database for tests."""
    return Database(url="sqlite:///:memory:")
