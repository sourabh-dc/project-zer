from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from core.config import get_settings
from services.orders.models import Base
from ..utils.orders_logger import logger

DATABASE_URL = get_settings().DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

try:
    # Create tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized")
except Exception as e:
    logger.warning(f"Table initialization failed: {e}")

def get_db():
    """Database dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

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