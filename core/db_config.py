# Database setup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.config import SETTINGS

engine = create_engine(
    SETTINGS.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=SETTINGS.CONNECTION_POOL_SIZE,
    max_overflow=SETTINGS.MAX_OVERFLOW,
    pool_timeout=SETTINGS.POOL_TIMEOUT,
    pool_recycle=3600,
    isolation_level="READ COMMITTED"
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)