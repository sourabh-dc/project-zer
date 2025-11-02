# Database setup
from typing import Dict, Any, Optional

from fastapi import Depends
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.config import get_settings
from services.billing.utils.user_auth import get_user_context

DATABASE_URL = get_settings().DATABASE_URL

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db_with_rls(user_context: Dict[str, Any] = Depends(get_user_context)):
    """Database dependency with RLS"""
    db = SessionLocal()
    try:
        set_rls_context(db, user_context["tenant_id"], user_context["user_id"])
        yield db
    finally:
        db.close()



def set_rls_context(db, tenant_id: str, user_id: Optional[str] = None):
    """Set Row Level Security context"""
    db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    if user_id:
        db.execute(text("SET app.current_user_id = :user_id"), {"user_id": user_id})

async def get_db():
    """Database dependency"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()