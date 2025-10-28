from typing import Optional, Dict
from fastapi import Depends
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.config import get_settings
from services.usage.utils.user_auth import get_user_context, ALLOW_DEMO
from ..models import Base
from ..utils.usage_logger import logger

# Configuration
DATABASE_URL = get_settings().DATABASE_URL

# Database setup
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

try:
    Base.metadata.create_all(engine)
except:
    pass

def set_rls_context(db, tenant_id: str, user_id: Optional[str] = None):
    """Set RLS context for database session"""
    try:
        db.rollback()
        db.execute(text("SET app.current_tenant = :tid"), {"tid": tenant_id})
        if user_id:
            db.execute(text("SET app.current_user = :uid"), {"uid": user_id})
    except Exception as e:
        logger.warning(f"Failed to set RLS context: {e}")
        db.rollback()

def get_db_with_rls(uctx: Dict = Depends(get_user_context)):
    """Database dependency with RLS"""
    db = SessionLocal()
    try:
        if not ALLOW_DEMO:
            set_rls_context(db, uctx["tenant_id"], uctx.get("user_id"))
        yield db
    finally:
        db.close()