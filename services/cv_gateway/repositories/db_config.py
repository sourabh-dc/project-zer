# Database setup
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.config import get_settings

DATABASE_URL = get_settings().DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Minimal helper stubs to prevent runtime NameErrors in this standalone service
def get_engine():
    return engine

def check_db():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False