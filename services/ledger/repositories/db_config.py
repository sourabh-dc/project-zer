# Database setup
from typing import Dict, Any

from fastapi import Depends
from sqlalchemy import text, create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import get_settings
from services.ledger.utils.user_auth import get_user_context

DATABASE_URL = get_settings().DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def set_rls_context(db: Session, tenant_id: str):
    """Set RLS context for database session"""
    db.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})

def get_db_with_rls(user_context: Dict[str, Any] = Depends(get_user_context)):
    """Database dependency with RLS"""
    db = SessionLocal()
    try:
        set_rls_context(db, user_context["tenant_id"], user_context["user_id"])
        yield db
    finally:
        db.close()

def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()