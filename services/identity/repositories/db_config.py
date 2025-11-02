"""Synchronous and asynchronous DB setup
We primarily use async sessions below; keep sync engine for utility if needed.
"""
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import sessionmaker

from core.config import get_settings
from services.identity.utils.identity_logger import logger

DATABASE_URL = get_settings().DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Async engine/session for endpoints using AsyncSessionLocal
ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
async_engine = create_async_engine(ASYNC_DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

def get_engine():
    return engine

def check_db():
    """Check database connectivity"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

def set_rls_context(db, tenant_id: str, user_id: Optional[str] = None):
    """Set Row Level Security context (sync sessions)"""
    try:
        db.execute(text("SET app.tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        if user_id:
            db.execute(text("SET app.user_id = :user_id"), {"user_id": user_id})
        db.commit()
    except Exception as e:
        logger.error(f"Failed to set RLS context: {str(e)}")
        raise

async def set_rls_context_async(db: AsyncSession, tenant_id: str, user_id: Optional[str] = None):
    """Set Row Level Security context (async sessions)"""
    try:
        await db.execute(text("SET LOCAL app.tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        if user_id:
            await db.execute(text("SET LOCAL app.user_id = :user_id"), {"user_id": user_id})
    except Exception as e:
        # RLS not configured - rollback and continue without it in demo mode
        await db.rollback()
        logger.debug(f"RLS context not set (probably not configured): {str(e)}")