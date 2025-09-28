# packages/zeroque_common/zeroque_common/middleware/rls_context.py
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text
from zeroque_common.db.session import SessionLocal
from zeroque_common.middleware.rbac import RBACContext
import logging
from typing import Optional

log = logging.getLogger("rls_context")

class RLSContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware to set Row Level Security context for database sessions.
    This ensures that all database queries are automatically filtered by tenant context.
    """
    
    def __init__(self, app):
        super().__init__(app)
        
    async def dispatch(self, request: Request, call_next):
        # Skip RLS context for health checks and public endpoints
        path = request.url.path
        if path.startswith("/health") or path.startswith("/readiness") or path.startswith("/docs"):
            return await call_next(request)
        
        # Extract tenant context from headers
        tenant_id = request.headers.get("X-Tenant-ID")
        user_id = request.headers.get("X-User-ID")
        site_id = request.headers.get("X-Site-ID")
        store_id = request.headers.get("X-Store-ID")
        
        # For development, allow requests without tenant context
        if not tenant_id:
            log.warning("No tenant context provided, skipping RLS setup for development")
            return await call_next(request)
        
        # Get user roles for RLS context
        user_roles = ""
        if user_id:
            try:
                rbac_context = RBACContext(user_id, tenant_id, site_id, store_id)
                roles = rbac_context.get_user_roles()
                user_roles = ",".join(roles) if roles else ""
            except Exception as e:
                log.warning("Could not get user roles for RLS context: %s", str(e))
        
        # Set RLS context in database session
        try:
            with SessionLocal() as db:
                # Call the set_tenant_context function
                db.execute(text("""
                    SELECT set_tenant_context(
                        :tenant_id,
                        :user_id,
                        :site_id,
                        :store_id,
                        :user_roles
                    )
                """), {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "site_id": site_id,
                    "store_id": store_id,
                    "user_roles": user_roles
                })
                db.commit()
                
                log.debug("RLS context set: tenant=%s, user=%s, site=%s, store=%s, roles=%s", 
                         tenant_id, user_id, site_id, store_id, user_roles)
                
        except Exception as e:
            log.error("Failed to set RLS context: %s", str(e))
            # Don't fail the request, just log the error
            # In production, you might want to fail here
        
        # Process the request
        response = await call_next(request)
        
        # Clear RLS context after request (optional - sessions are typically short-lived)
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT clear_tenant_context()"))
                db.commit()
        except Exception as e:
            log.error("Failed to clear RLS context: %s", str(e))
        
        return response


class RLSContextManager:
    """
    Context manager for setting RLS context in database sessions.
    Use this when you need to manually set tenant context for specific operations.
    """
    
    def __init__(self, tenant_id: str, user_id: Optional[str] = None, 
                 site_id: Optional[str] = None, store_id: Optional[str] = None,
                 user_roles: Optional[str] = None):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.site_id = site_id
        self.store_id = store_id
        self.user_roles = user_roles or ""
    
    def __enter__(self):
        with SessionLocal() as db:
            db.execute(text("""
                SELECT set_tenant_context(
                    :tenant_id,
                    :user_id,
                    :site_id,
                    :store_id,
                    :user_roles
                )
            """), {
                "tenant_id": self.tenant_id,
                "user_id": self.user_id,
                "site_id": self.site_id,
                "store_id": self.store_id,
                "user_roles": self.user_roles
            })
            db.commit()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        with SessionLocal() as db:
            db.execute(text("SELECT clear_tenant_context()"))
            db.commit()


def set_rls_context(tenant_id: str, user_id: Optional[str] = None, 
                    site_id: Optional[str] = None, store_id: Optional[str] = None,
                    user_roles: Optional[str] = None):
    """
    Convenience function to set RLS context for the current database session.
    Use this in service methods when you need to ensure tenant isolation.
    """
    with SessionLocal() as db:
        db.execute(text("""
            SELECT set_tenant_context(
                :tenant_id,
                :user_id,
                :site_id,
                :store_id,
                :user_roles
            )
        """), {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "site_id": site_id,
            "store_id": store_id,
            "user_roles": user_roles or ""
        })
        db.commit()


def clear_rls_context():
    """
    Convenience function to clear RLS context for the current database session.
    """
    with SessionLocal() as db:
        db.execute(text("SELECT clear_tenant_context()"))
        db.commit()
