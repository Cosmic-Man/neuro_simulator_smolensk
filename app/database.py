from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import DATABASE_ECHO, DATABASE_URL


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str = DATABASE_URL, *, echo: bool = DATABASE_ECHO) -> Engine:
    options: dict[str, object] = {
        "echo": echo,
        "pool_pre_ping": True,
    }
    if database_url in {"sqlite://", "sqlite+pysqlite:///:memory:"}:
        options.update(
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    elif database_url.startswith("sqlite"):
        options.update(connect_args={"check_same_thread": False})
    return create_engine(database_url, **options)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_schema(target_engine: Engine = engine) -> None:
    # Import registers every mapped table in Base.metadata.
    from . import db_models  # noqa: F401

    Base.metadata.create_all(target_engine)
