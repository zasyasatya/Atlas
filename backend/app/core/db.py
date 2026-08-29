"""Database engine + session lifecycle."""
from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings

engine = create_engine(
    settings.db_url,
    echo=False,
    connect_args={"check_same_thread": False} if settings.db_url.startswith("sqlite") else {},
)


def init_db() -> None:
    import app.domain.models  # noqa: F401  (register metadata)

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def session_scope() -> Session:
    return Session(engine)
