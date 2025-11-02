# Database setup
from typing import Dict, Any
from fastapi import Depends
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from core.config import get_settings
from services.cv_gateway.utils.user_auth import get_user_context

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

def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def set_rls_context(db: Session, tenant_id: str, user_id: str = None):
    """Set RLS context for database session"""
    try:
        db.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        if user_id:
            db.execute(text("SET LOCAL app.current_user_id = :user_id"), {"user_id": user_id})
    except Exception as e:
        pass  # RLS not configured yet

def get_db_with_rls(user_context: Dict[str, Any] = Depends(get_user_context)):
    """Database dependency with RLS"""
    db = SessionLocal()
    try:
        set_rls_context(db, user_context["tenant_id"], user_context["user_id"])
        yield db
    finally:
        db.close()