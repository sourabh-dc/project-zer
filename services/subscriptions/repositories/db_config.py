from sqlalchemy import create_engine, text
from sqlalchemy.orm.session import sessionmaker

from core.config import get_settings

DATABASE_URL = get_settings().DATABASE_URL

# DB
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def set_rls_context(db, tenant_id: str):
    """Set RLS context for database session"""
    try:
        db.execute(text("SET app.current_tenant = :tid"), {"tid": tenant_id})
    except Exception:
        pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()