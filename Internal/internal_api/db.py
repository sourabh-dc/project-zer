from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from internal_api.config import SETTINGS

engine = create_engine(
    SETTINGS.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=getattr(SETTINGS, "CONNECTION_POOL_SIZE", 20),
    max_overflow=getattr(SETTINGS, "MAX_OVERFLOW", 10),
    pool_timeout=getattr(SETTINGS, "POOL_TIMEOUT", 30),
    pool_recycle=3600,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

