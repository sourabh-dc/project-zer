import logging
from typing import Dict

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import get_settings
from ..models import *

DATABASE_URL = get_settings().DATABASE_URL
ALLOW_DEMO = get_settings().ALLOW_DEMO

logger = logging.getLogger(__name__)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# RLS
def set_rls_context(db, tid, uid=None):
    try:
        # Rollback any failed transaction first
        db.rollback()
        db.execute(text("SET app.current_tenant = :tid"), {"tid": tid})
        if uid:
            db.execute(text("SET app.current_user = :uid"), {"uid": uid})
    except Exception as e:
        logger.debug(f"RLS: {e}")
        # Ensure we're not in a failed transaction state
        try:
            db.rollback()
        except:
            pass

def get_db_with_rls(uctx: Dict = Depends(get_user_context)):
    db = get_db()
    try:
        # Skip RLS in demo mode to avoid transaction issues
        if not ALLOW_DEMO:
            set_rls_context(db, uctx["tenant_id"], uctx.get("user_id"))
        yield db
    finally:
        db.close()

