import os
from typing import Dict

from fastapi import Depends
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.config import get_settings
from ..utils.pricing_logger import logger
from ..utils.user_auth import get_user_context

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

def set_rls_context(db, tenant_id: str):
    """Set RLS context for database session"""
    try:
        db.execute(text("SELECT set_config('app.current_tenant_id', :tenant_id, false)"), {"tenant_id": str(tenant_id)})
    except Exception as e:
        logger.warning(f"RLS context set failed: {e}")

def get_db_with_rls(uctx: Dict = Depends(get_user_context)):
    """Database dependency with RLS"""
    db = SessionLocal()
    try:
        # Skip RLS in demo mode to avoid transaction issues
        allow_demo_mode = os.getenv("ALLOW_DEMO", "false").lower() == "true"
        if not allow_demo_mode:
            set_rls_context(db, uctx["tenant_id"])
        yield db
    finally:
        db.close()

    """Best-effort RLS context setter. Tenant-aware DBs may ignore this."""
    try:
        db.execute(text("SET app.current_tenant = :tid"), {"tid": uctx["tenant_id"]})
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
