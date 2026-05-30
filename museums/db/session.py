"""Database engine and session factory."""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from museums.config import get_database_url
from museums.models.schema import Base


def build_engine(database_url: str | None = None) -> Engine:
    """Create the SQLAlchemy engine.

    Args:
        database_url: Override the connection string. Defaults to DATABASE_URL env var.
    """
    url = database_url or get_database_url()
    return create_engine(url, pool_pre_ping=True)


def init_db(database_url: str | None = None) -> None:
    """Create all tables if they do not exist.

    Args:
        database_url: Override the connection string. Defaults to DATABASE_URL env var.
    """
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)


def make_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    """Return a configured session factory.

    Args:
        database_url: Override the connection string. Defaults to DATABASE_URL env var.
    """
    engine = build_engine(database_url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@contextmanager
def get_session(database_url: str | None = None) -> Generator[Session, None, None]:
    """Context manager that yields a database session and handles commit/rollback.

    Args:
        database_url: Override the connection string. Defaults to DATABASE_URL env var.
    """
    factory = make_session_factory(database_url)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
