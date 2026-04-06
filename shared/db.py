"""
Database engine and session factory.

Usage::

    from shared.db import get_session, engine
    with get_session() as db:
        db.execute(...)
"""
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from shared.config import POSTGRES_URL

engine = create_engine(POSTGRES_URL, pool_pre_ping=True, pool_size=5)
SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def get_session() -> Session:
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
