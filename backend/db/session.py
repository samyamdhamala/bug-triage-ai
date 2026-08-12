import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@lru_cache(maxsize=1)
def get_engine():
    database_url = os.environ["DATABASE_URL"]
    return create_engine(database_url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db():
    """FastAPI dependency: yields a request-scoped session, always closed after."""
    db: Session = _session_factory()()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_session() -> Iterator[Session]:
    """Context-managed session for non-FastAPI call sites (scripts, the Slack bot)."""
    db: Session = _session_factory()()
    try:
        yield db
    finally:
        db.close()
