# ==================================================================================
# PERMISSION CHECK HELPERS
# ==================================================================================
import json
import uuid
from datetime import timezone, datetime
from typing import List, Tuple, Dict, Optional, Any

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from starlette import status

from Models import Store, Site, CostCentre, Product, RoleScope, ApprovalDelegation, Tenant, UserRole, Role, ApprovalChainStep, User, UserOrgAssignment, OrgUnit
from Schemas import ResourceContext, UserContext
from core.config import SETTINGS
from core.db_config import SessionLocal
from core.user_auth import get_user_context, set_rls_context
from utils.redis_client import redis_client
from utils.logger import logger


def fetch_store_hierarchy(db: Session, store_id: uuid.UUID) -> List[Tuple[str, str]]:
    store = db.query(Store).filter(Store.store_id == store_id).first()
    if not store:
        return []
    chain = [("store", str(store.store_id))]
    if store.site_id:
        chain.append(("site", str(store.site_id)))
    if store.tenant_id:
        chain.append(("tenant", str(store.tenant_id)))
    return chain


def fetch_site_hierarchy(db: Session, site_id: uuid.UUID) -> List[Tuple[str, str]]:
    site = db.query(Site).filter(Site.site_id == site_id).first()
    if not site:
        return []
    chain = [("site", str(site.site_id))]
    if site.tenant_id:
        chain.append(("tenant", str(site.tenant_id)))
    return chain


def fetch_cost_centre_hierarchy(db: Session, cost_centre_id: uuid.UUID) -> List[Tuple[str, str]]:
    cost_centre = db.query(CostCentre).filter(CostCentre.cost_centre_id == cost_centre_id).first()
    if not cost_centre:
        return []
    chain = [("cost_centre", str(cost_centre.cost_centre_id))]
    if cost_centre.manager_user_id:
        chain.append(("user", str(cost_centre.manager_user_id)))
    if cost_centre.tenant_id:
        chain.append(("tenant", str(cost_centre.tenant_id)))
    return chain


def fetch_product_hierarchy(db: Session, product_id: uuid.UUID) -> List[Tuple[str, str]]:
    product = db.query(Product).filter(Product.product_id == product_id).first()
    if not product:
        return []
    chain = [("product", str(product.product_id))]
    if product.category_id:
        chain.append(("category", str(product.category_id)))
    if product.tenant_id:
        chain.append(("tenant", str(product.tenant_id)))
    return chain


def build_resource_chain(db: Session, resource: ResourceContext) -> List[Tuple[str, str]]:
    if resource.parent_chain:
        return resource.parent_chain

    if resource.resource_type == "store" and resource.resource_id:
        return fetch_store_hierarchy(db, uuid.UUID(resource.resource_id))
    if resource.resource_type == "site" and resource.resource_id:
        return fetch_site_hierarchy(db, uuid.UUID(resource.resource_id))
    if resource.resource_type == "cost_centre" and resource.resource_id:
        return fetch_cost_centre_hierarchy(db, uuid.UUID(resource.resource_id))
    if resource.resource_type == "product" and resource.resource_id:
        return fetch_product_hierarchy(db, uuid.UUID(resource.resource_id))
    if resource.resource_type == "tenant" and resource.resource_id:
        return [("tenant", resource.resource_id)]
    if resource.resource_type == "user" and resource.resource_id:
        return [("user", resource.resource_id)]
    return []


def permissions_for_code(ctx: UserContext, permission_code: str) -> List[Dict[str, Optional[str]]]:
    grants = ctx.permissions.get(permission_code)
    if not grants and "*" in ctx.permissions:
        grants = ctx.permissions["*"]
    return grants or []


def check_scope(
        db: Session,
        grants: List[Dict[str, Optional[str]]],
        resource: Optional[ResourceContext],
        ctx: UserContext
) -> bool:
    if not grants:
        return False

    if not resource:
        return True

    if any(g.get("resource_type") == "*" for g in grants):
        return True

    resource_chain = build_resource_chain(db, resource)
    requested_pairs = {(resource.resource_type, resource.resource_id)} | set(resource_chain)

    for grant in grants:
        grant_type = grant.get("resource_type")
        grant_id = grant.get("resource_id")

        if grant_type == "tenant":
            if grant_id in (None, ctx.tenant_id):
                return True
            if any(pair for pair in requested_pairs if pair[0] == "tenant" and pair[1] == grant_id):
                return True
        elif grant_type and (grant_type, grant_id) in requested_pairs:
            return True
        elif grant_type == "user" and grant_id in ctx.manager_of:
            return True
    return False


def check_tenant_access(ctx: UserContext, tenant_id: uuid.UUID):
    """Check if user has access to tenant data"""
    # Allow if same tenant, or user has admin permissions ("*" or "admin")
    if str(ctx.tenant_id) != str(tenant_id):
        has_admin = "*" in ctx.permissions or "admin" in ctx.permissions
        if not has_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to tenant data")


def require_permission(permission_code: str, resource_resolver=None):
    async def dependency(
            ctx: UserContext = Depends(get_user_context)
    ):
        grants = permissions_for_code(ctx, permission_code)
        if not grants:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission")

        resource = resource_resolver(ctx) if resource_resolver else None

        if resource:
            db = SessionLocal()
            try:
                set_rls_context(db, ctx.tenant_id)
                if not check_scope(db, grants, resource, ctx):
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient scope")
            finally:
                db.close()

        return ctx

    return dependency


def resolve_resource_id_for_scope(
        request_data: Dict[str, Any],
        tenant_id: str,
        scope: str
) -> Optional[str]:
    scope = scope or ""
    if scope == "tenant":
        return tenant_id
    candidates = {
        "site": ["site_id", "siteId"],
        "store": ["store_id", "storeId"],
        "cost_centre": ["cost_centre_id", "cost_center_id", "costCentreId"],
        "cost_center": ["cost_centre_id", "cost_center_id", "costCentreId"],
        "user": ["target_user_id", "employee_user_id", "employee_id"],
        "org_unit": ["org_unit_id", "orgUnitId"]
    }
    keys = candidates.get(scope, [])
    for key in keys:
        if key in request_data and request_data[key]:
            return str(request_data[key])
    return None


def resolve_approvers_for_step(
        db: Session,
        step: ApprovalChainStep,
        tenant_id: str,
        request_data: Dict[str, Any]
) -> List[str]:
    # Find role for this tenant (tenant-scoped)
    role = db.query(Role).filter(
        Role.code == step.approver_role,
        Role.tenant_id == uuid.UUID(tenant_id)
    ).first()
    if not role:
        logger.warning(f"⚠️ Role '{step.approver_role}' not found for tenant {tenant_id}")
        return []

    user_roles = db.query(UserRole).filter(UserRole.role_id == role.role_id).all()
    if not user_roles:
        return []
    
    # Filter users by tenant
    tenant_uuid = uuid.UUID(tenant_id)
    valid_user_roles = []
    for ur in user_roles:
        user = db.query(User).filter(
            User.user_id == ur.user_id,
            User.tenant_id == tenant_uuid,
            User.active == True
        ).first()
        if user:
            valid_user_roles.append(ur)
    user_roles = valid_user_roles

    target_resource_id = resolve_resource_id_for_scope(request_data, tenant_id, step.approver_scope)
    
    # SPECIAL CASE: If approver_scope is "user" and we have a user_id in request_data,
    # find the manager of that user (manager hierarchy)
    if step.approver_scope == "user" and target_resource_id:
        # Find managers of the target user
        user_assignments = db.query(UserOrgAssignment).filter(
            UserOrgAssignment.user_id == uuid.UUID(target_resource_id)
        ).all()
        
        manager_user_ids = set()
        for assignment in user_assignments:
            # Find users in same org unit with manager role
            manager_role = db.query(Role).filter(
                Role.code == step.approver_role,
                Role.tenant_id == uuid.UUID(tenant_id)
            ).first()
            if manager_role:
                # FIXED: Query without join to avoid issues, then filter users
                manager_assignments = db.query(UserOrgAssignment).filter(
                    UserOrgAssignment.org_unit_id == assignment.org_unit_id,
                    UserOrgAssignment.user_id != uuid.UUID(target_resource_id),
                    UserOrgAssignment.role_id == manager_role.role_id
                ).all()
                
                for mgr_assignment in manager_assignments:
                    # Verify user exists and is active
                    manager_user = db.query(User).filter(
                        User.user_id == mgr_assignment.user_id,
                        User.tenant_id == uuid.UUID(tenant_id),
                        User.active == True
                    ).first()
                    if manager_user:
                        manager_user_ids.add(str(manager_user.user_id))
        
        if manager_user_ids:
            result.extend(list(manager_user_ids))
            # Deduplicate and return early if we found managers
            deduped = list(dict.fromkeys(result))
            return deduped
    
    # If approver_scope is "tenant", find all users with the role (no scope filtering needed)
    if step.approver_scope == "tenant":
        for assignment in user_roles:
            result.append(str(assignment.user_id))
        # Deduplicate
        deduped = list(dict.fromkeys(result))
        return deduped if deduped else []
    
    scopes = db.query(RoleScope).filter(RoleScope.role_id == role.role_id).all()
    scope_map = scopes or []

    for assignment in user_roles:
        user_id_str = str(assignment.user_id)
        if not scope_map:
            # No scopes defined - all users with this role are approvers
            result.append(user_id_str)
            continue
        
        # Check if user matches any scope
        user_matches = False
        for scope in scope_map:
            if scope.grant_type != "include":
                continue
            
            # For tenant scope: match if resource_id is None (all tenants) or matches tenant_id
            if scope.resource_type == "tenant":
                if scope.resource_id is None or str(scope.resource_id) == tenant_id:
                    user_matches = True
                    break
            
            # For other scopes: match if resource_type matches and resource_id matches or is None
            elif scope.resource_type in (step.approver_scope, step.approver_scope.replace("_", " ")):
                if target_resource_id is None:
                    # No target resource - match if scope.resource_id is None
                    if scope.resource_id is None:
                        user_matches = True
                        break
                else:
                    # Target resource specified - match if scope.resource_id matches or is None
                    if scope.resource_id is None or str(scope.resource_id) == target_resource_id:
                        user_matches = True
                        break
        
        if user_matches:
            result.append(user_id_str)

    # Include valid delegations
    if result:
        now = datetime.now(timezone.utc)
        delegations = db.query(ApprovalDelegation).filter(
            ApprovalDelegation.delegator_user_id.in_([uuid.UUID(uid) for uid in result])
        ).all()
        for delegation in delegations:
            if delegation.valid_from and delegation.valid_from > now:
                continue
            if delegation.valid_to and delegation.valid_to < now:
                continue
            if delegation.resource_type and delegation.resource_type != step.approver_scope:
                continue
            if delegation.resource_id and target_resource_id and str(delegation.resource_id) != target_resource_id:
                continue
            result.append(str(delegation.delegate_user_id))

    # Deduplicate
    deduped = list(dict.fromkeys(result))
    return deduped


def get_tenant_from_cache(tenant_id: str, db: Session) -> Optional[Tenant]:
    """Get tenant with Redis caching"""
    cache_key = f"tenant:{tenant_id}"

    # Try cache first
    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                data = json.loads(cached)
                tenant = Tenant()
                tenant.tenant_id = uuid.UUID(data["tenant_id"])
                tenant.name = data["name"]
                tenant.tenant_type = data["type"]
                tenant.active = data["active"]
                return tenant
        except Exception as e:
            logger.warning(f"Tenant cache read failed: {e}")

    # Query database
    tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
    if tenant and redis_client:
        try:
            data = {
                "tenant_id": str(tenant.tenant_id),
                "name": tenant.name,
                "type": tenant.tenant_type,
                "active": tenant.active
            }
            redis_client.setex(cache_key, SETTINGS.CACHE_TTL_SECONDS, json.dumps(data))
        except Exception as e:
            logger.warning(f"Tenant cache write failed: {e}")

    return tenant