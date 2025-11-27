# Database setup
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from core.config import SETTINGS

db_url = make_url(SETTINGS.DATABASE_URL)

if db_url.get_backend_name().startswith("sqlite"):
    engine = create_engine(
        SETTINGS.DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
        isolation_level="SERIALIZABLE"
    )
else:
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

def get_db():
    """Get database session without RLS (for tenant creation)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()