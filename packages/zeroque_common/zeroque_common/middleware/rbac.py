# packages/zeroque_common/zeroque_common/middleware/rbac.py
from fastapi import HTTPException, Request, Depends
from typing import Optional, List, Dict, Any
from sqlalchemy import text
from zeroque_common.db.session import SessionLocal
import logging

log = logging.getLogger("rbac")

class RBACContext:
    """RBAC context for request processing"""
    def __init__(self, user_id: str, tenant_id: str, site_id: Optional[str] = None, store_id: Optional[str] = None):
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.site_id = site_id
        self.store_id = store_id
        self._permissions_cache = {}

    def has_permission(self, permission: str, resource_id: Optional[str] = None) -> bool:
        """Check if user has specific permission"""
        cache_key = f"{permission}:{resource_id or 'global'}"
        if cache_key in self._permissions_cache:
            return self._permissions_cache[cache_key]
        
        with SessionLocal() as db:
            # Check direct permissions
            has_perm = self._check_direct_permission(db, permission, resource_id)
            if not has_perm:
                # Check inherited permissions from distributor relationships
                has_perm = self._check_inherited_permission(db, permission, resource_id)
            
            self._permissions_cache[cache_key] = has_perm
            return has_perm

    def _check_direct_permission(self, db, permission: str, resource_id: Optional[str]) -> bool:
        """Check direct user permissions"""
        # Map permission to role requirements
        role_requirements = {
            "read_tenant": ["admin", "manager"],
            "write_tenant": ["admin"],
            "read_site": ["admin", "manager"],
            "write_site": ["admin", "manager"],
            "read_store": ["admin", "manager", "employee"],
            "write_store": ["admin", "manager"],
            "read_users": ["admin", "manager"],
            "write_users": ["admin"],
            "read_pricing": ["admin", "manager"],
            "write_pricing": ["admin", "manager"],
            "read_orders": ["admin", "manager", "employee"],
            "write_orders": ["admin", "manager"],
            "read_budget": ["admin", "manager"],
            "write_budget": ["admin"],
            "read_subscriptions": ["admin"],
            "write_subscriptions": ["admin"]
        }
        
        required_roles = role_requirements.get(permission, ["admin"])
        
        # Check user's roles in current context
        query = """
            SELECT r.code FROM memberships m
            JOIN roles r ON m.role_id = r.role_id
            WHERE m.user_id = :user_id AND r.code = ANY(:roles)
        """
        params = {"user_id": self.user_id, "roles": required_roles}
        
        # Add scope constraints
        if self.site_id:
            query += " AND (m.site_id = :site_id OR m.site_id IS NULL)"
            params["site_id"] = self.site_id
        else:
            query += " AND m.site_id IS NULL"
            
        if self.store_id:
            query += " AND (m.store_id = :store_id OR m.store_id IS NULL)"
            params["store_id"] = self.store_id
        else:
            query += " AND m.store_id IS NULL"
            
        query += " AND (m.tenant_id = :tenant_id OR m.tenant_id IS NULL)"
        params["tenant_id"] = self.tenant_id
        
        result = db.execute(text(query), params).first()
        return result is not None

    def get_user_roles(self) -> List[str]:
        """Get list of role codes for this user in current context"""
        with SessionLocal() as db:
            query = """
                SELECT r.code FROM memberships m
                JOIN roles r ON m.role_id = r.role_id
                WHERE m.user_id = :user_id
            """
            params = {"user_id": self.user_id}
            
            # Add scope constraints
            if self.site_id:
                query += " AND (m.site_id = :site_id OR m.site_id IS NULL)"
                params["site_id"] = self.site_id
            else:
                query += " AND m.site_id IS NULL"
                
            if self.store_id:
                query += " AND (m.store_id = :store_id OR m.store_id IS NULL)"
                params["store_id"] = self.store_id
            else:
                query += " AND m.store_id IS NULL"
                
            query += " AND (m.tenant_id = :tenant_id OR m.tenant_id IS NULL)"
            params["tenant_id"] = self.tenant_id
            
            rows = db.execute(text(query), params).all()
            return [row[0] for row in rows]

    def _check_inherited_permission(self, db, permission: str, resource_id: Optional[str]) -> bool:
        """Check permissions inherited from distributor relationships"""
        # Check if current tenant has distributor relationships
        distributor_query = """
            SELECT parent_tenant_id FROM tenant_links
            WHERE child_tenant_id = :tenant_id AND relationship = 'distributor'
        """
        distributors = db.execute(text(distributor_query), {"tenant_id": self.tenant_id}).fetchall()
        
        for (parent_tenant_id,) in distributors:
            # Check if parent tenant grants this permission
            parent_context = RBACContext(self.user_id, parent_tenant_id, self.site_id, self.store_id)
            if parent_context._check_direct_permission(db, permission, resource_id):
                return True
        
        return False

    def get_accessible_tenants(self) -> List[str]:
        """Get list of tenant IDs user can access (including distributor relationships)"""
        with SessionLocal() as db:
            # Direct tenant access
            direct_query = """
                SELECT DISTINCT m.tenant_id FROM memberships m
                WHERE m.user_id = :user_id AND m.tenant_id IS NOT NULL
            """
            direct_tenants = [row[0] for row in db.execute(text(direct_query), {"user_id": self.user_id}).fetchall()]
            
            # Distributor tenant access
            distributor_query = """
                SELECT DISTINCT tl.child_tenant_id FROM tenant_links tl
                WHERE tl.parent_tenant_id = ANY(:parent_tenants) AND tl.relationship = 'distributor'
            """
            if direct_tenants:
                distributor_tenants = [row[0] for row in db.execute(text(distributor_query), {"parent_tenants": direct_tenants}).fetchall()]
                return list(set(direct_tenants + distributor_tenants))
            
            return direct_tenants

def get_rbac_context(request: Request) -> RBACContext:
    """Extract RBAC context from request headers"""
    # In a real implementation, you'd extract this from JWT token or session
    user_id = request.headers.get("X-User-ID")
    tenant_id = request.headers.get("X-Tenant-ID")
    site_id = request.headers.get("X-Site-ID")
    store_id = request.headers.get("X-Store-ID")
    
    if not user_id or not tenant_id:
        raise HTTPException(status_code=401, detail="Missing user or tenant context")
    
    return RBACContext(user_id, tenant_id, site_id, store_id)

def require_permission(permission: str, resource_id: Optional[str] = None):
    """Decorator to require specific permission"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Extract RBAC context from request
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            
            if not request:
                raise HTTPException(status_code=500, detail="Request context not found")
            
            rbac_context = get_rbac_context(request)
            if not rbac_context.has_permission(permission, resource_id):
                raise HTTPException(status_code=403, detail=f"Permission denied: {permission}")
            
            return func(*args, **kwargs)
        return wrapper
    return decorator

class RBACMiddleware:
    """Middleware to enforce RBAC on API endpoints"""
    
    def __init__(self, app):
        self.app = app
        
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)
            
            # Skip RBAC for health checks and public endpoints
            path = request.url.path
            if path.startswith("/health") or path.startswith("/readiness") or path.startswith("/docs"):
                await self.app(scope, receive, send)
                return
            
            # Extract user context
            user_id = request.headers.get("X-User-ID")
            tenant_id = request.headers.get("X-Tenant-ID")
            
            if not user_id or not tenant_id:
                # For development, allow requests without RBAC headers
                log.warning("RBAC headers missing, allowing request for development")
                await self.app(scope, receive, send)
                return
            
            # TODO: Add endpoint-specific permission checks here
            # For now, just log the request
            log.info("RBAC request user=%s tenant=%s path=%s", user_id, tenant_id, path)
        
        await self.app(scope, receive, send)
