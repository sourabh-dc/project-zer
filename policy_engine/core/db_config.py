"""
Policy Engine Database Configuration
SQLAlchemy engine and session management
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Generator

from policy_engine.core.config import SETTINGS
from policy_engine.utils.logger import logger


# Create engine with connection pooling
engine = create_engine(
    SETTINGS.DATABASE_URL,
    pool_size=SETTINGS.CONNECTION_POOL_SIZE,
    max_overflow=SETTINGS.MAX_OVERFLOW,
    pool_timeout=SETTINGS.POOL_TIMEOUT,
    pool_recycle=SETTINGS.POOL_RECYCLE,
    pool_pre_ping=True,  # Verify connections before use
    echo=False  # Set to True for SQL debugging
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency for database sessions.
    Yields a session and ensures cleanup.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database session error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """
    Context manager for database sessions (for non-FastAPI use).
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database session error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """
    Initialize database tables.
    Called on startup to ensure tables exist.
    """
    from policy_engine.Models import Base
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Policy Engine database tables initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize database tables: {e}")
        raise
