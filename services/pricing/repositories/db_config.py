from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.config import get_settings

DATABASE_URL = get_settings().DATABASE_URL

# Database setup
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """Database dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()