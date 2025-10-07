# RLS Context Helper
from sqlalchemy import text
import logging

logger=logging.getLogger("provisioning.utils.helpers")


def set_rls_context(db_session, tenant_id: str = None, user_id: str = None):
    """Set Row Level Security context for database session"""
    try:
        if tenant_id:
            db_session.execute(text("SET LOCAL row_security.tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        if user_id:
            db_session.execute(text("SET LOCAL row_security.user_id = :user_id"), {"user_id": user_id})
    except Exception as e:
        logger.warning(f"Failed to set RLS context: {str(e)}")