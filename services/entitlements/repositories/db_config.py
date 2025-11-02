from typing import Any, Dict

from fastapi import Depends
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.config import get_settings
from services.entry.utils.user_auth import get_user_context

DATABASE_URL = get_settings().DATABASE_URL
ALLOW_DEMO = get_settings().ALLOW_DEMO

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def set_rls_context(db, tenant_id: str):
    try:
        db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    except Exception:
        pass

def get_db(user_context: Dict[str, Any] = Depends(get_user_context)):
    db = SessionLocal()
    try:
        set_rls_context(db, user_context["tenant_id"])
        yield db
    finally:
        db.close()

def get_db_with_rls(uctx: Dict = Depends(get_user_context)):
    """Database dependency with RLS"""
    db = SessionLocal()
    try:
        # Skip RLS in demo mode to avoid transaction issues
        if not ALLOW_DEMO:
            set_rls_context(db, uctx["tenant_id"])
        yield db
    finally:
        db.close()