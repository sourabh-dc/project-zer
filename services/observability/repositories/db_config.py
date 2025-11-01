from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker

from core.config import get_settings

DATABASE_URL = get_settings().DATABASE_URL

# Database setup
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def set_rls_context(db, tenant_id: str):
    try:
        db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass