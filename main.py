"""
ZeroQue Provisioning Service - Simplified Production Version

A clean, powerful API for multi-tenant provisioning with PostgreSQL RLS.
"""

import os
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Tuple
import httpx
from jose import jwt, JWTError
from fastapi import FastAPI, HTTPException, Query, Depends, Header, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
import redis
import bcrypt

from utils.logger import logger
from Models import *
from Schemas import *
from core.config import SETTINGS, SERVICE_NAME, SERVICE_VERSION
from core.db_config import engine, SessionLocal

DEFAULT_PERMISSIONS: List[Tuple[str, str]] = [
    ("tenants.create", "Create and manage tenants"),
    ("sites.manage", "Manage sites for a tenant"),
    ("stores.manage", "Manage stores for a site"),
    ("users.manage", "Manage tenant users"),
    ("roles.assign", "Assign and remove roles for users"),
    ("vendors.manage", "Manage vendors for a tenant"),
    ("cost_centres.manage", "Manage cost centres for a tenant"),
    ("catalog.categories.manage", "Manage catalog categories"),
    ("catalog.products.manage", "Create and update catalog products"),
    ("catalog.products.view", "View catalog products"),
    ("catalog.variants.manage", "Manage catalog variants"),
    ("subscriptions.plans.manage", "Manage subscription plans"),
    ("subscriptions.features.manage", "Manage subscription features"),
    ("subscriptions.tenant.manage", "Manage tenant subscriptions"),
    ("entitlements.check", "Check entitlements for tenants"),
    ("entitlements.usage.record", "Record entitlement usage"),
    ("approvals.chains.manage", "Manage approval chains and steps"),
    ("approvals.requests.create", "Create approval requests"),
    ("approvals.requests.view", "View approval requests"),
    ("approvals.requests.respond", "Respond to approval requests"),
    ("budget.approve", "Approve budget requests"),
    ("costcentre.manage", "Manage cost centre budgets"),
    ("admin.permissions.manage", "Manage permission catalog"),
    ("admin.roles.manage", "Manage roles and assignments"),
    ("admin.scopes.manage", "Manage role scopes"),
]

# Redis setup
try:
    redis_client = redis.Redis.from_url(SETTINGS.REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info("✅ Redis connected")
except Exception as e:
    redis_client = None
    logger.warning(f"⚠️  Redis unavailable: {e}, caching disabled")

# FastAPI app
app = FastAPI(
    title="ZeroQue Provisioning API",
    version=SERVICE_VERSION,
    description="Simple, powerful provisioning service with PostgreSQL RLS"
)

# CORS - configure via environment
allow_origins = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Metrics
req_total = Counter('prov_requests_total', 'Total requests', ['operation', 'status'])
req_duration = Histogram('prov_duration_seconds', 'Request duration', ['operation'])

# ==================================================================================
# AUTHENTICATION & AUTHORIZATION
# ==================================================================================

def generate_api_key() -> str:
    """Generate a secure API key (for service-to-service usage)"""
    return f"zq_{secrets.token_urlsafe(32)}"

JWKS_CACHE: Dict[str, Any] = {}
JWKS_CACHE_EXPIRES_AT: float = 0.0


async def fetch_jwks() -> Optional[Dict[str, Any]]:
    global JWKS_CACHE_EXPIRES_AT
    if not SETTINGS.JWT_JWKS_URL:
        return None

    now_ts = datetime.utcnow().timestamp()
    if JWKS_CACHE and JWKS_CACHE_EXPIRES_AT > now_ts:
        return JWKS_CACHE

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(SETTINGS.JWT_JWKS_URL)
        resp.raise_for_status()
        JWKS_CACHE.clear()
        JWKS_CACHE.update(resp.json())
        JWKS_CACHE_EXPIRES_AT = now_ts + SETTINGS.JWT_CACHE_SECONDS
        return JWKS_CACHE


async def decode_jwt_token(token: str) -> Dict[str, Any]:
    try:
        if SETTINGS.JWT_ALGORITHM.upper().startswith("HS"):
            if not SETTINGS.JWT_SECRET:
                raise RuntimeError("JWT_SECRET must be configured for HS algorithms")
            return jwt.decode(
                token,
                SETTINGS.JWT_SECRET,
                algorithms=[SETTINGS.JWT_ALGORITHM],
                audience=SETTINGS.JWT_AUDIENCE,
                issuer=SETTINGS.JWT_ISSUER,
            )

        jwks = await fetch_jwks()
        if not jwks:
            raise RuntimeError("JWKS URL must be configured for asymmetric algorithms")
        return jwt.decode(
            token,
            jwks,
            algorithms=[SETTINGS.JWT_ALGORITHM],
            audience=SETTINGS.JWT_AUDIENCE,
            issuer=SETTINGS.JWT_ISSUER,
        )
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def verify_api_key(api_key: str, db: Session) -> Optional[User]:
    try:
        user = db.query(User).filter(
            User.api_key == api_key,
            User.active.is_(True)
        ).first()
        if not user:
            return None
        if user.api_key_expires_at and datetime.now(timezone.utc) > user.api_key_expires_at:
            logger.warning("Expired API key used")
            return None
        return user
    except Exception as exc:
        logger.error(f"API key verification failed: {exc}")
        return None


def fetch_manager_relationships(db: Session, user_id: uuid.UUID) -> List[str]:
    assignments = db.query(UserOrgAssignment).filter(
        UserOrgAssignment.user_id == user_id
    ).all()
    if not assignments:
        return []

    org_unit_ids = [assignment.org_unit_id for assignment in assignments]
    subordinate_assignments = db.query(UserOrgAssignment).filter(
        UserOrgAssignment.org_unit_id.in_(org_unit_ids)
    ).all()

    subordinate_ids = {
        str(a.user_id)
        for a in subordinate_assignments
        if a.user_id and a.user_id != user_id
    }
    return list(subordinate_ids)


def build_permission_map(
    db: Session,
    role_ids: List[uuid.UUID],
    tenant_id: uuid.UUID
) -> Dict[str, List[Dict[str, Optional[str]]]]:
    if not role_ids:
        return {}

    permission_rows = db.query(
        RolePermission.role_id,
        Permission.code
    ).join(
        Permission, RolePermission.permission_id == Permission.permission_id
    ).filter(
        RolePermission.role_id.in_(role_ids)
    ).all()

    scope_rows = db.query(RoleScope).filter(
        RoleScope.role_id.in_(role_ids)
    ).all()

    scope_map: Dict[uuid.UUID, List[RoleScope]] = {}
    for scope in scope_rows:
        scope_map.setdefault(scope.role_id, []).append(scope)

    permission_map: Dict[str, List[Dict[str, Optional[str]]]] = {}
    for role_id, permission_code in permission_rows:
        scopes = scope_map.get(role_id)
        if not scopes:
            permission_map.setdefault(permission_code, []).append({
                "resource_type": "tenant",
                "resource_id": str(tenant_id)
            })
            continue
        entries = []
        for scope in scopes:
            entries.append({
                "resource_type": scope.resource_type,
                "resource_id": str(scope.resource_id) if scope.resource_id else None
            })
        permission_map.setdefault(permission_code, []).extend(entries)
    return permission_map


def cache_user_context(ctx: UserContext):
    if not redis_client:
        return
    cache_key = f"userctx:{ctx.user_id}:{ctx.tenant_id}"
    try:
        redis_client.setex(cache_key, SETTINGS.CACHE_TTL_SECONDS, ctx.model_dump_json())
    except Exception as exc:
        logger.warning(f"User context cache set failed: {exc}")


def invalidate_user_context(user_id: str, tenant_id: str):
    if not redis_client:
        return
    cache_key = f"userctx:{user_id}:{tenant_id}"
    try:
        redis_client.delete(cache_key)
    except Exception as exc:
        logger.warning(f"User context cache delete failed: {exc}")


def load_cached_user_context(user_id: str, tenant_id: str) -> Optional[UserContext]:
    if not redis_client:
        return None
    cache_key = f"userctx:{user_id}:{tenant_id}"
    try:
        cached = redis_client.get(cache_key)
        if cached:
            return UserContext.model_validate_json(cached)
    except Exception as exc:
        logger.warning(f"User context cache read failed: {exc}")
    return None


def seed_default_permissions():
    try:
        with SessionLocal() as db:
            existing_codes = {code for (code,) in db.query(Permission.code).all()}
            new_permissions = [
                Permission(permission_id=uuid.uuid4(), code=code, description=description)
                for code, description in DEFAULT_PERMISSIONS
                if code not in existing_codes
            ]
            if new_permissions:
                db.add_all(new_permissions)
                db.commit()
                logger.info(f"✅ Seeded {len(new_permissions)} permissions")
    except Exception as exc:
        logger.warning(f"⚠️  Permission seeding skipped: {exc}")


def ensure_bootstrap_admin():
    try:
        with SessionLocal() as db:
            tenant = db.query(Tenant).filter(
                func.lower(Tenant.name) == SETTINGS.BOOTSTRAP_TENANT_NAME.lower()
            ).first()
            if not tenant:
                tenant = Tenant(
                    tenant_id=uuid.uuid4(),
                    name=SETTINGS.BOOTSTRAP_TENANT_NAME,
                    type="customer",
                    active=True
                )
                db.add(tenant)
                db.commit()
                db.refresh(tenant)
                logger.info("✅ Bootstrap tenant created")

            user = db.query(User).filter(
                func.lower(User.email) == SETTINGS.BOOTSTRAP_ADMIN_EMAIL.lower()
            ).first()
            if not user:
                password_hash = bcrypt.hashpw("ChangeMe123!".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                user = User(
                    user_id=uuid.uuid4(),
                    tenant_id=tenant.tenant_id,
                    email=SETTINGS.BOOTSTRAP_ADMIN_EMAIL.lower(),
                    display_name="Bootstrap Admin",
                    password_hash=password_hash,
                    active=True,
                    api_key=SETTINGS.BOOTSTRAP_ADMIN_API_KEY,
                    api_key_created_at=datetime.now(timezone.utc),
                    api_key_expires_at=datetime.now(timezone.utc) + timedelta(days=3650)
                )
                db.add(user)
                db.commit()
                logger.info("✅ Bootstrap admin user created")
            else:
                if user.api_key != SETTINGS.BOOTSTRAP_ADMIN_API_KEY:
                    user.api_key = SETTINGS.BOOTSTRAP_ADMIN_API_KEY
                    user.api_key_created_at = datetime.now(timezone.utc)
                    user.api_key_expires_at = datetime.now(timezone.utc) + timedelta(days=3650)
                    db.commit()
            logger.info("🔑 Bootstrap admin API key ready")
    except Exception as exc:
        logger.warning(f"⚠️  Bootstrap admin setup skipped: {exc}")


def build_user_context(
    db: Session,
    user: User,
    claims: Optional[Dict[str, Any]] = None
) -> UserContext:
    claims = claims or {}
    roles = db.query(Role).join(
        UserRole, UserRole.role_id == Role.role_id
    ).filter(
        UserRole.user_id == user.user_id
    ).all()

    role_ids = [role.role_id for role in roles]
    permission_map = {}

    claim_permissions = claims.get("permissions")
    if isinstance(claim_permissions, list):
        if "*" in claim_permissions:
            permission_map = {
                "*": [{"resource_type": "tenant", "resource_id": str(user.tenant_id)}]
            }
        else:
            permission_map = {
                perm: [{"resource_type": "tenant", "resource_id": str(user.tenant_id)}]
                for perm in claim_permissions
            }
    else:
        permission_map = build_permission_map(db, role_ids, user.tenant_id)

    manager_of = fetch_manager_relationships(db, user.user_id)

    ctx = UserContext(
        user_id=str(user.user_id),
        tenant_id=str(user.tenant_id),
        roles=[role.code or str(role.role_id) for role in roles],
        permissions=permission_map,
        manager_of=manager_of,
        raw_claims=claims
    )
    return ctx


async def resolve_user_context_from_token(token: str) -> UserContext:
    claims = await decode_jwt_token(token)
    user_id = claims.get("sub")
    tenant_id = claims.get("tenant_id")
    if not user_id or not tenant_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid JWT claims")

    cached = load_cached_user_context(user_id, tenant_id)
    if cached:
        return cached

    with SessionLocal() as db:
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        ctx = build_user_context(db, user, claims)
        cache_user_context(ctx)
        return ctx


async def resolve_user_context_from_api_key(api_key: str) -> UserContext:
    with SessionLocal() as db:
        user = verify_api_key(api_key, db)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired API key")
        ctx = build_user_context(db, user, claims={"permissions": ["*"]})
        cache_user_context(ctx)
        return ctx


async def get_user_context(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")
) -> UserContext:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
        return await resolve_user_context_from_token(token)

    if x_api_key:
        ctx = await resolve_user_context_from_api_key(x_api_key)
        return ctx

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


def set_rls_context(db: Session, tenant_id: str):
    """Set Row Level Security context for tenant isolation"""
    try:
        db.execute(text("SET app.current_tenant = :tid"), {"tid": tenant_id})
    except Exception as exc:
        logger.error(f"RLS setup failed: {exc}")
        raise HTTPException(status_code=500, detail="Security context setup failed")


def get_db_with_rls(uctx: UserContext = Depends(get_user_context)):
    """Get database session with RLS enabled"""
    db = SessionLocal()
    try:
        set_rls_context(db, uctx.tenant_id)
        yield db
    finally:
        db.close()


# ==================================================================================
# PERMISSION CHECK HELPERS
# ==================================================================================

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
    role = db.query(Role).filter(Role.code == step.approver_role).first()
    if not role:
        return []

    user_roles = db.query(UserRole).filter(UserRole.role_id == role.role_id).all()
    if not user_roles:
        return []

    target_resource_id = resolve_resource_id_for_scope(request_data, tenant_id, step.approver_scope)
    scopes = db.query(RoleScope).filter(RoleScope.role_id == role.role_id).all()
    scope_map = scopes or []

    result: List[str] = []
    for assignment in user_roles:
        user_id_str = str(assignment.user_id)
        if not scope_map:
            result.append(user_id_str)
            continue
        for scope in scope_map:
            if scope.grant_type != "include":
                continue
            if scope.resource_type == "tenant" and str(scope.resource_id or tenant_id) == tenant_id:
                result.append(user_id_str)
                break
            if scope.resource_type in (step.approver_scope, step.approver_scope.replace("_", " ")) and (
                target_resource_id is None or str(scope.resource_id) == target_resource_id or scope.resource_id is None
            ):
                result.append(user_id_str)
                break

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


def get_db():
    """Get database session without RLS (for tenant creation)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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


# ==================================================================================
# API ENDPOINTS
# ==================================================================================

@app.get("/health")
async def health():
    """Health check endpoint"""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "healthy", "service": SERVICE_NAME, "version": SERVICE_VERSION}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/tenants", status_code=201)
async def create_tenant(
    req: TenantRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("tenants.create"))
):
    """Create a new tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_tenant", status="start").inc()
        
        # Check if tenant exists
        existing = db.query(Tenant).filter(Tenant.name == req.name).first()
        if existing:
            raise HTTPException(status_code=409, detail="Tenant name already exists")
        
        # Create tenant
        tenant = Tenant(
            tenant_id=uuid.uuid4(),
            name=req.name,
            tenant_type=req.type,
            active=True
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        
        req_total.labels(operation="create_tenant", status="success").inc()
        req_duration.labels(operation="create_tenant").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created tenant: {tenant.tenant_id} ({tenant.name})")
        
        return {
            "tenant_id": str(tenant.tenant_id),
            "name": tenant.name,
            "type": tenant.tenant_type,
            "created_at": tenant.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_tenant", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_tenant", status="error").inc()
        raise HTTPException(status_code=409, detail="Tenant already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_tenant", status="error").inc()
        logger.error(f"❌ Tenant creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/tenants")
async def list_tenants(
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(require_permission("tenants.create"))
):
    """List all tenants with pagination"""
    total = db.query(Tenant).filter(Tenant.active == True).count()
    tenants = (
        db.query(Tenant)
        .filter(Tenant.active == True)
        .order_by(Tenant.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    
    return {
        "tenants": [
            {
                "tenant_id": str(t.tenant_id),
                "name": t.name,
                "type": t.tenant_type,
                "created_at": t.created_at.isoformat()
            }
            for t in tenants
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.get("/v1/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific tenant by ID"""
    try:
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        return {
            "tenant_id": str(tenant.tenant_id),
            "name": tenant.name,
            "type": tenant.tenant_type,
            "active": tenant.active,
            "created_at": tenant.created_at.isoformat(),
            "updated_at": tenant.updated_at.isoformat() if tenant.updated_at else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get tenant failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.put("/v1/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    name: Optional[str] = Query(None, description="New tenant name"),
    db: Session = Depends(get_db)
):
    """Update a tenant's information"""
    start = datetime.now()
    try:
        req_total.labels(operation="update_tenant", status="start").inc()
        
        # Find tenant
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Update fields
        if name:
            # Check if new name conflicts
            existing = db.query(Tenant).filter(
                Tenant.name == name,
                Tenant.tenant_id != uuid.UUID(tenant_id)
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail="Tenant name already exists")
            tenant.name = name
        
        tenant.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(tenant)
        
        # Clear cache
        if redis_client:
            try:
                redis_client.delete(f"tenant:{tenant_id}")
            except Exception as e:
                logger.warning(f"Cache clear failed: {e}")
        
        req_total.labels(operation="update_tenant", status="success").inc()
        req_duration.labels(operation="update_tenant").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Updated tenant: {tenant.tenant_id}")
        
        return {
            "tenant_id": str(tenant.tenant_id),
            "name": tenant.name,
            "type": tenant.tenant_type,
            "active": tenant.active,
            "updated_at": tenant.updated_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="update_tenant", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        req_total.labels(operation="update_tenant", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="update_tenant", status="error").inc()
        logger.error(f"❌ Update tenant failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/sites", status_code=201)
async def create_site(
    req: SiteRequest,
    tenant_id: str = Query(..., description="Tenant ID"),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("sites.manage"))
):
    """Create a new site under a tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_site", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Create site
        site = Site(
            site_id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id),
            name=req.name,
            site_type=req.type,
            geo=req.geo
        )
        db.add(site)
        db.commit()
        db.refresh(site)
        
        req_total.labels(operation="create_site", status="success").inc()
        req_duration.labels(operation="create_site").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created site: {site.site_id} ({site.name})")
        
        return {
            "site_id": str(site.site_id),
            "tenant_id": str(site.tenant_id),
            "name": site.name,
            "site_type": site.site_type,
            "created_at": site.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_site", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        req_total.labels(operation="create_site", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_site", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant reference")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_site", status="error").inc()
        logger.error(f"❌ Site creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/sites")
async def list_sites(
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("sites.manage"))
):
    """List sites with optional tenant filtering"""
    try:
        q = db.query(Site)
        if tenant_id:
            q = q.filter(Site.tenant_id == uuid.UUID(tenant_id))
        
        total = q.count()
        sites = q.order_by(Site.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "sites": [
                {
                    "site_id": str(s.site_id),
                    "tenant_id": str(s.tenant_id),
                    "name": s.name,
                    "site_type": s.site_type,
                    "created_at": s.created_at.isoformat()
                }
                for s in sites
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except Exception as e:
        logger.error(f"❌ List sites failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/stores", status_code=201)
async def create_store(
    req: StoreRequest,
    site_id: str = Query(..., description="Site ID"),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("stores.manage"))
):
    """Create a new store under a site"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_store", status="start").inc()
        
        # Verify site exists and get tenant_id
        site = db.query(Site).filter(Site.site_id == uuid.UUID(site_id)).first()
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")
        
        # Create store (tenant_id auto-mapped from site)
        store = Store(
            store_id=uuid.uuid4(),
            site_id=uuid.UUID(site_id),
            tenant_id=site.tenant_id,
            name=req.name,
            store_type=req.type,
            geo=req.geo
        )
        db.add(store)
        db.commit()
        db.refresh(store)
        
        req_total.labels(operation="create_store", status="success").inc()
        req_duration.labels(operation="create_store").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created store: {store.store_id} ({store.name})")
        
        return {
            "store_id": str(store.store_id),
            "site_id": str(store.site_id),
            "tenant_id": str(store.tenant_id),
            "name": store.name,
            "store_type": store.store_type,
            "created_at": store.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_store", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid site ID format")
    except HTTPException:
        req_total.labels(operation="create_store", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_store", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid site reference")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_store", status="error").inc()
        logger.error(f"❌ Store creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/stores")
async def list_stores(
    site_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("stores.manage"))
):
    """List stores with optional site filtering"""
    try:
        q = db.query(Store)
        if site_id:
            q = q.filter(Store.site_id == uuid.UUID(site_id))
        
        total = q.count()
        stores = q.order_by(Store.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "stores": [
                {
                    "store_id": str(s.store_id),
                    "site_id": str(s.site_id),
                    "name": s.name,
                    "store_type": s.store_type,
                    "created_at": s.created_at.isoformat()
                }
                for s in stores
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid site ID format")
    except Exception as e:
        logger.error(f"❌ List stores failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/users", status_code=201)
async def create_user(
    req: UserRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "users.manage",
            None
        )
    )
):
    """Create a new user"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_user", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Check if email exists
        existing = db.query(User).filter(func.lower(User.email) == req.email.lower()).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already exists")
        
        # Hash password
        password_hash = bcrypt.hashpw(req.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Generate API key
        api_key = generate_api_key()
        api_key_expires_at = datetime.now(timezone.utc) + timedelta(days=SETTINGS.API_KEY_EXPIRY_DAYS)
        
        # Create user
        user = User(
            user_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            email=req.email.lower(),
            display_name=req.display_name,
            password_hash=password_hash,
            active=True,
            api_key=api_key,
            api_key_created_at=datetime.now(timezone.utc),
            api_key_expires_at=api_key_expires_at
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
        req_total.labels(operation="create_user", status="success").inc()
        req_duration.labels(operation="create_user").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created user: {user.user_id} ({user.email})")
        
        return {
            "user_id": str(user.user_id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
            "display_name": user.display_name,
            "api_key": api_key,
            "api_key_expires_at": api_key_expires_at.isoformat(),
            "created_at": user.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_user", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        req_total.labels(operation="create_user", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_user", status="error").inc()
        raise HTTPException(status_code=409, detail="Email already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_user", status="error").inc()
        logger.error(f"❌ User creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/users")
async def list_users(
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("users.manage"))
):
    """List users with optional tenant filtering"""
    try:
        q = db.query(User).filter(User.active == True)
        if tenant_id:
            q = q.filter(User.tenant_id == uuid.UUID(tenant_id))
        
        total = q.count()
        users = q.order_by(User.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "users": [
                {
                    "user_id": str(u.user_id),
                    "tenant_id": str(u.tenant_id),
                    "email": u.email,
                    "display_name": u.display_name,
                    "created_at": u.created_at.isoformat()
                }
                for u in users
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except Exception as e:
        logger.error(f"❌ List users failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/users/bulk-import", status_code=201)
async def bulk_import_users(
    req: BulkUserRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "users.manage",
            None
        )
    )
):
    """Bulk import users"""
    start = datetime.now()
    try:
        req_total.labels(operation="bulk_import_users", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        results = {"success": [], "failed": []}
        tenant_uuid = uuid.UUID(req.tenant_id)
        
        for user_data in req.users:
            try:
                email = user_data.get("email")
                display_name = user_data.get("display_name", email)
                
                if not email:
                    results["failed"].append({"error": "Missing email", "data": user_data})
                    continue
                
                # Check if email exists
                if db.query(User).filter(func.lower(User.email) == email.lower()).first():
                    results["failed"].append({"email": email, "error": "Email already exists"})
                    continue
                
                # Generate random password
                temp_password = f"temp_{secrets.token_urlsafe(16)}"
                password_hash = bcrypt.hashpw(temp_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                
                # Generate API key
                api_key = generate_api_key()
                api_key_expires_at = datetime.now(timezone.utc) + timedelta(days=SETTINGS.API_KEY_EXPIRY_DAYS)
                
                # Create user
                user = User(
                    user_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    email=email.lower(),
                    display_name=display_name,
                    password_hash=password_hash,
                    active=True,
                    api_key=api_key,
                    api_key_created_at=datetime.now(timezone.utc),
                    api_key_expires_at=api_key_expires_at
                )
                db.add(user)
                db.flush()
                
                results["success"].append({
                    "user_id": str(user.user_id),
                    "email": email,
                    "api_key": api_key,
                    "temporary_password": temp_password
                })
            except Exception as e:
                results["failed"].append({"email": user_data.get("email", "unknown"), "error": str(e)})
        
        db.commit()
        
        req_total.labels(operation="bulk_import_users", status="success").inc()
        req_duration.labels(operation="bulk_import_users").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Bulk import: {len(results['success'])}/{len(req.users)} succeeded")
        
        return {
            "tenant_id": req.tenant_id,
            "total_requested": len(req.users),
            "success_count": len(results["success"]),
            "failed_count": len(results["failed"]),
            "results": results
        }
    except HTTPException:
        req_total.labels(operation="bulk_import_users", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="bulk_import_users", status="error").inc()
        logger.error(f"❌ Bulk import failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/roles", status_code=201)
async def create_role(
    req: RoleRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("admin.roles.manage"))
):
    """Create a new role"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_role", status="start").inc()
        
        # Check if code exists (if provided)
        if req.code:
            existing = db.query(Role).filter(Role.code == req.code).first()
            if existing:
                raise HTTPException(status_code=409, detail="Role code already exists")
        
        # Create role
        role = Role(
            role_id=uuid.uuid4(),
            code=req.code,
            description=req.description or ""
        )
        db.add(role)
        db.commit()
        db.refresh(role)
        
        req_total.labels(operation="create_role", status="success").inc()
        req_duration.labels(operation="create_role").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created role: {role.role_id} ({role.code})")
        
        return {
            "role_id": str(role.role_id),
            "name": role.code,
            "code": role.code,
            "description": role.description,
            "created_at": role.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_role", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_role", status="error").inc()
        raise HTTPException(status_code=409, detail="Role code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_role", status="error").inc()
        logger.error(f"❌ Role creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/roles")
async def list_roles(
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(require_permission("admin.roles.manage"))
):
    """List all roles"""
    total = db.query(Role).count()
    roles = db.query(Role).order_by(Role.created_at.desc()).limit(limit).offset(offset).all()
    
    return {
        "roles": [
            {
                "role_id": str(r.role_id),
                "name": r.code,
                "code": r.code,
                "description": r.description,
                "created_at": r.created_at.isoformat()
            }
            for r in roles
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.post("/v1/users/{user_id}/roles", status_code=201)
async def assign_role_to_user(
    user_id: str,
    req: AssignRoleRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "roles.assign",
            None
        )
    )
):
    """Assign a role to a user"""
    start = datetime.now()
    try:
        req_total.labels(operation="assign_role", status="start").inc()
        
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Verify role exists
        role = db.query(Role).filter(Role.role_id == uuid.UUID(req.role_id)).first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        
        # Check if assignment already exists
        existing = db.query(UserRole).filter(
            UserRole.user_id == uuid.UUID(user_id),
            UserRole.role_id == uuid.UUID(req.role_id)
        ).first()
        
        if existing:
            raise HTTPException(status_code=409, detail="Role already assigned to user")
        
        # Create assignment
        user_role = UserRole(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            role_id=uuid.UUID(req.role_id)
        )
        db.add(user_role)
        db.commit()
        db.refresh(user_role)
        
        req_total.labels(operation="assign_role", status="success").inc()
        req_duration.labels(operation="assign_role").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Assigned role {req.role_id} to user {user_id}")
        invalidate_user_context(str(user.user_id), str(user.tenant_id))
        
        return {
            "user_id": user_id,
            "role_id": req.role_id,
            "role_name": role.code,
            "assigned": True,
            "created_at": user_role.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="assign_role", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid user ID or role ID format")
    except HTTPException:
        req_total.labels(operation="assign_role", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="assign_role", status="error").inc()
        raise HTTPException(status_code=409, detail="Role assignment already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="assign_role", status="error").inc()
        logger.error(f"❌ Assign role failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/users/{user_id}/roles")
async def get_user_roles(
    user_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "roles.assign",
            None
        )
    )
):
    """Get all roles assigned to a user"""
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get user roles
        user_roles = (
            db.query(UserRole, Role)
            .join(Role, UserRole.role_id == Role.role_id)
            .filter(UserRole.user_id == uuid.UUID(user_id))
            .all()
        )
        
        return {
            "user_id": user_id,
            "email": user.email,
            "display_name": user.display_name,
            "roles": [
                {
                    "role_id": str(r.role_id),
                    "role_code": r.code,
                    "role_name": r.code,
                    "assigned_at": ur.created_at.isoformat()
                }
                for ur, r in user_roles
            ],
            "total": len(user_roles)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get user roles failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/v1/users/{user_id}/roles/{role_id}")
async def remove_role_from_user(
    user_id: str,
    role_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "roles.assign",
            None
        )
    )
):
    """Remove a role from a user"""
    start = datetime.now()
    try:
        req_total.labels(operation="remove_role", status="start").inc()
        
        # Find user role assignment
        user_role = db.query(UserRole).filter(
            UserRole.user_id == uuid.UUID(user_id),
            UserRole.role_id == uuid.UUID(role_id)
        ).first()
        
        if not user_role:
            raise HTTPException(status_code=404, detail="Role assignment not found")
        
        user = db.query(User).filter(User.user_id == user_role.user_id).first()
        db.delete(user_role)
        db.commit()
        
        req_total.labels(operation="remove_role", status="success").inc()
        req_duration.labels(operation="remove_role").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Removed role {role_id} from user {user_id}")
        if user:
            invalidate_user_context(str(user.user_id), str(user.tenant_id))
        
        return {
            "user_id": user_id,
            "role_id": role_id,
            "removed": True
        }
    except ValueError:
        req_total.labels(operation="remove_role", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid user ID or role ID format")
    except HTTPException:
        req_total.labels(operation="remove_role", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="remove_role", status="error").inc()
        logger.error(f"❌ Remove role failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/vendors", status_code=201)
async def create_vendor(
    req: VendorRequest,
    tenant_id: str = Query(..., description="Tenant ID"),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("vendors.manage"))
):
    """Create a new vendor"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_vendor", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Create vendor
        vendor = Vendor(
            vendor_id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id),
            name=req.name,
            contact_email=req.contact_email,
            description=req.description,
            status="active"
        )
        db.add(vendor)
        db.commit()
        db.refresh(vendor)
        
        req_total.labels(operation="create_vendor", status="success").inc()
        req_duration.labels(operation="create_vendor").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created vendor: {vendor.vendor_id} ({vendor.name})")
        
        return {
            "vendor_id": str(vendor.vendor_id),
            "tenant_id": str(vendor.tenant_id),
            "name": vendor.name,
            "contact_email": vendor.contact_email,
            "status": vendor.status,
            "created_at": vendor.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_vendor", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_vendor", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant reference")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_vendor", status="error").inc()
        logger.error(f"❌ Vendor creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/vendors")
async def list_vendors(
    tenant_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(
        require_permission(
            "vendors.manage",
            None
        )
    )
):
    """List vendors with optional tenant filtering"""
    q = db.query(Vendor)
    if tenant_id:
        q = q.filter(Vendor.tenant_id == uuid.UUID(tenant_id))
    
    total = q.count()
    vendors = q.order_by(Vendor.created_at.desc()).limit(limit).offset(offset).all()
    
    return {
        "vendors": [
            {
                "vendor_id": str(v.vendor_id),
                "tenant_id": str(v.tenant_id),
                "name": v.name,
                "status": v.status,
                "created_at": v.created_at.isoformat()
            }
            for v in vendors
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.post("/v1/cost-centres", status_code=201)
async def create_cost_centre(
    req: CostCentreRequest,
    tenant_id: str = Query(..., description="Tenant ID"),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("cost_centres.manage"))
):
    """Create a new cost centre"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_cost_centre", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Verify manager user exists (if provided)
        manager_user_uuid = None
        if req.manager_user_id:
            manager = db.query(User).filter(User.user_id == uuid.UUID(req.manager_user_id)).first()
            if not manager:
                raise HTTPException(status_code=404, detail="Manager user not found")
            manager_user_uuid = uuid.UUID(req.manager_user_id)
        
        # Create cost centre
        cc = CostCentre(
            cost_centre_id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id),
            name=req.name,
            manager_user_id=manager_user_uuid,
            budget_minor=req.budget_minor,
            spent_minor=0,
            currency_code=req.currency,
            status="active"
        )
        db.add(cc)
        db.commit()
        db.refresh(cc)
        
        req_total.labels(operation="create_cost_centre", status="success").inc()
        req_duration.labels(operation="create_cost_centre").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created cost centre: {cc.cost_centre_id} ({cc.name})")
        
        return {
            "cost_centre_id": str(cc.cost_centre_id),
            "tenant_id": str(cc.tenant_id),
            "name": cc.name,
            "budget_minor": cc.budget_minor,
            "spent_minor": cc.spent_minor,
            "manager_user_id": str(cc.manager_user_id) if cc.manager_user_id else None,
            "status": cc.status,
            "created_at": cc.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_cost_centre", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_cost_centre", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant reference")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_cost_centre", status="error").inc()
        logger.error(f"❌ Cost centre creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/cost-centres")
async def list_cost_centres(
    tenant_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(
        require_permission(
            "cost_centres.manage",
            None
        )
    )
):
    """List cost centres with optional tenant filtering"""
    q = db.query(CostCentre).filter(CostCentre.status == "active")
    if tenant_id:
        q = q.filter(CostCentre.tenant_id == uuid.UUID(tenant_id))
    
    total = q.count()
    ccs = q.order_by(CostCentre.created_at.desc()).limit(limit).offset(offset).all()
    
    return {
        "cost_centres": [
            {
                "cost_centre_id": str(cc.cost_centre_id),
                "tenant_id": str(cc.tenant_id),
                "name": cc.name,
                "budget_minor": cc.budget_minor,
                "spent_minor": cc.spent_minor,
                "manager_user_id": str(cc.manager_user_id) if cc.manager_user_id else None,
                "status": cc.status,
                "created_at": cc.created_at.isoformat()
            }
            for cc in ccs
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


# ==================================================================================
# CATALOG MANAGEMENT ENDPOINTS
# ==================================================================================

@app.post("/v1/catalog/categories", status_code=201)
async def create_category(
    req: CategoryRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.categories.manage",
            None
        )
    )
):
    """Create a new product category"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_category", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Verify parent category if provided
        parent_category_uuid = None
        if req.parent_category_id:
            parent = db.query(Category).filter(Category.category_id == uuid.UUID(req.parent_category_id)).first()
            if not parent:
                raise HTTPException(status_code=404, detail="Parent category not found")
            parent_category_uuid = uuid.UUID(req.parent_category_id)
        
        # Create category
        category = Category(
            category_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            code=req.code,
            description=req.description,
            parent_category_id=parent_category_uuid,
            active=True
        )
        db.add(category)
        db.commit()
        db.refresh(category)
        
        req_total.labels(operation="create_category", status="success").inc()
        req_duration.labels(operation="create_category").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created category: {category.category_id} ({category.name})")
        
        return {
            "category_id": str(category.category_id),
            "tenant_id": str(category.tenant_id),
            "name": category.name,
            "code": category.code,
            "parent_category_id": str(category.parent_category_id) if category.parent_category_id else None,
            "created_at": category.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_category", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID or parent category ID format")
    except HTTPException:
        req_total.labels(operation="create_category", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_category", status="error").inc()
        raise HTTPException(status_code=400, detail="Category code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_category", status="error").inc()
        logger.error(f"❌ Category creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/categories")
async def list_categories(
    tenant_id: Optional[str] = Query(None),
    active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.categories.manage",
            None
        )
    )
):
    """List categories"""
    try:
        q = db.query(Category)
        if tenant_id:
            q = q.filter(Category.tenant_id == uuid.UUID(tenant_id))
        if active is not None:
            q = q.filter(Category.active == active)
        
        total = q.count()
        categories = q.order_by(Category.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "categories": [
                {
                    "category_id": str(c.category_id),
                    "tenant_id": str(c.tenant_id),
                    "name": c.name,
                    "code": c.code,
                    "description": c.description,
                    "parent_category_id": str(c.parent_category_id) if c.parent_category_id else None,
                    "active": c.active,
                    "created_at": c.created_at.isoformat()
                }
                for c in categories
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except Exception as e:
        logger.error(f"❌ List categories failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/catalog/products", status_code=201)
async def create_product(
    req: ProductRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.products.manage",
            None
        )
    )
):
    """Create a new product"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_product", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Verify category if provided
        category_uuid = None
        if req.category_id:
            category = db.query(Category).filter(Category.category_id == uuid.UUID(req.category_id)).first()
            if not category:
                raise HTTPException(status_code=404, detail="Category not found")
            category_uuid = uuid.UUID(req.category_id)
        
        # Create product
        product = Product(
            product_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            category_id=category_uuid,
            sku=req.sku,
            name=req.name,
            description=req.description,
            brand=req.brand,
            manufacturer=req.manufacturer,
            base_price_minor=req.base_price_minor,
            currency=req.currency,
            tax_rate=req.tax_rate,
            product_type=req.product_type,
            active=True,
            product_metadata=req.product_metadata
        )
        db.add(product)
        db.commit()
        db.refresh(product)
        
        req_total.labels(operation="create_product", status="success").inc()
        req_duration.labels(operation="create_product").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created product: {product.product_id} ({product.name})")
        
        return {
            "product_id": str(product.product_id),
            "tenant_id": str(product.tenant_id),
            "category_id": str(product.category_id) if product.category_id else None,
            "sku": product.sku,
            "name": product.name,
            "base_price_minor": product.base_price_minor,
            "currency": product.currency,
            "created_at": product.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_product", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID or category ID format")
    except HTTPException:
        req_total.labels(operation="create_product", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_product", status="error").inc()
        raise HTTPException(status_code=400, detail="Product SKU already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_product", status="error").inc()
        logger.error(f"❌ Product creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products")
async def list_products(
    tenant_id: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.products.view",
            None
        )
    )
):
    """List products"""
    try:
        q = db.query(Product)
        if tenant_id:
            q = q.filter(Product.tenant_id == uuid.UUID(tenant_id))
        if category_id:
            q = q.filter(Product.category_id == uuid.UUID(category_id))
        if active is not None:
            q = q.filter(Product.active == active)
        
        total = q.count()
        products = q.order_by(Product.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "products": [
                {
                    "product_id": str(p.product_id),
                    "tenant_id": str(p.tenant_id),
                    "category_id": str(p.category_id) if p.category_id else None,
                    "sku": p.sku,
                    "name": p.name,
                    "description": p.description,
                    "brand": p.brand,
                    "base_price_minor": p.base_price_minor,
                    "currency": p.currency,
                    "active": p.active,
                    "created_at": p.created_at.isoformat()
                }
                for p in products
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"❌ List products failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/catalog/variants", status_code=201)
async def create_variant(
    req: VariantRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.variants.manage",
            None
        )
    )
):
    """Create a new product variant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_variant", status="start").inc()
        
        # Verify product exists and get tenant_id
        product = db.query(Product).filter(Product.product_id == uuid.UUID(req.product_id)).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Create variant
        variant = Variant(
            variant_id=uuid.uuid4(),
            product_id=uuid.UUID(req.product_id),
            tenant_id=product.tenant_id,
            sku=req.sku,
            name=req.name,
            attributes=req.attributes,
            price_minor=req.price_minor,
            currency=req.currency,
            stock_quantity=req.stock_quantity,
            low_stock_threshold=req.low_stock_threshold,
            active=True
        )
        db.add(variant)
        db.commit()
        db.refresh(variant)
        
        req_total.labels(operation="create_variant", status="success").inc()
        req_duration.labels(operation="create_variant").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created variant: {variant.variant_id} ({variant.name})")
        
        return {
            "variant_id": str(variant.variant_id),
            "product_id": str(variant.product_id),
            "tenant_id": str(variant.tenant_id),
            "sku": variant.sku,
            "name": variant.name,
            "attributes": variant.attributes,
            "price_minor": variant.price_minor,
            "currency": variant.currency,
            "stock_quantity": variant.stock_quantity,
            "created_at": variant.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_variant", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        req_total.labels(operation="create_variant", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_variant", status="error").inc()
        raise HTTPException(status_code=400, detail="Variant SKU already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_variant", status="error").inc()
        logger.error(f"❌ Variant creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products/{product_id}")
async def get_product(
    product_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.products.view",
            None
        )
    )
):
    """Get a specific product by ID"""
    try:
        product = db.query(Product).filter(Product.product_id == uuid.UUID(product_id)).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Get category details if exists
        category = None
        if product.category_id:
            category = db.query(Category).filter(Category.category_id == product.category_id).first()
        
        return {
            "product_id": str(product.product_id),
            "tenant_id": str(product.tenant_id),
            "category_id": str(product.category_id) if product.category_id else None,
            "category_name": category.name if category else None,
            "sku": product.sku,
            "name": product.name,
            "description": product.description,
            "brand": product.brand,
            "manufacturer": product.manufacturer,
            "base_price_minor": product.base_price_minor,
            "currency": product.currency,
            "tax_rate": product.tax_rate,
            "product_type": product.product_type,
            "active": product.active,
            "product_metadata": product.product_metadata,
            "created_at": product.created_at.isoformat(),
            "updated_at": product.updated_at.isoformat() if product.updated_at else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get product failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products/{product_id}/variants")
async def get_product_variants(
    product_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.products.view",
            None
        )
    )
):
    """Get all variants for a specific product"""
    try:
        # Verify product exists
        product = db.query(Product).filter(Product.product_id == uuid.UUID(product_id)).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Get variants
        variants = db.query(Variant).filter(
            Variant.product_id == uuid.UUID(product_id)
        ).order_by(Variant.created_at.desc()).all()
        
        return {
            "product_id": product_id,
            "product_name": product.name,
            "product_sku": product.sku,
            "variants": [
                {
                    "variant_id": str(v.variant_id),
                    "sku": v.sku,
                    "name": v.name,
                    "attributes": v.attributes,
                    "price_minor": v.price_minor,
                    "currency": v.currency,
                    "stock_quantity": v.stock_quantity,
                    "low_stock_threshold": v.low_stock_threshold,
                    "active": v.active,
                    "created_at": v.created_at.isoformat()
                }
                for v in variants
            ],
            "total": len(variants)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get product variants failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products/{product_id}/category")
async def get_product_category(
    product_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.products.view",
            None
        )
    )
):
    """Get category for a specific product"""
    try:
        # Get product
        product = db.query(Product).filter(Product.product_id == uuid.UUID(product_id)).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Get category
        if not product.category_id:
            return {
                "product_id": product_id,
                "product_name": product.name,
                "category": None,
                "message": "No category assigned to this product"
            }
        
        category = db.query(Category).filter(Category.category_id == product.category_id).first()
        
        return {
            "product_id": product_id,
            "product_name": product.name,
            "category": {
                "category_id": str(category.category_id),
                "name": category.name,
                "code": category.code,
                "description": category.description,
                "parent_category_id": str(category.parent_category_id) if category.parent_category_id else None,
                "active": category.active
            } if category else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get product category failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/variants")
async def list_variants(
    product_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.products.view",
            None
        )
    )
):
    """List product variants"""
    try:
        q = db.query(Variant)
        if product_id:
            q = q.filter(Variant.product_id == uuid.UUID(product_id))
        
        total = q.count()
        variants = q.order_by(Variant.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "variants": [
                {
                    "variant_id": str(v.variant_id),
                    "product_id": str(v.product_id),
                    "sku": v.sku,
                    "name": v.name,
                    "attributes": v.attributes,
                    "price_minor": v.price_minor,
                    "currency": v.currency,
                    "stock_quantity": v.stock_quantity,
                    "low_stock_threshold": v.low_stock_threshold,
                    "active": v.active,
                    "created_at": v.created_at.isoformat()
                }
                for v in variants
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except Exception as e:
        logger.error(f"❌ List variants failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/variants/{variant_id}")
async def get_variant(
    variant_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.products.view",
            None
        )
    )
):
    """Get a specific variant by ID"""
    try:
        variant = db.query(Variant).filter(Variant.variant_id == uuid.UUID(variant_id)).first()
        if not variant:
            raise HTTPException(status_code=404, detail="Variant not found")
        
        # Get product details
        product = db.query(Product).filter(Product.product_id == variant.product_id).first()
        
        return {
            "variant_id": str(variant.variant_id),
            "product_id": str(variant.product_id),
            "product_name": product.name if product else None,
            "product_sku": product.sku if product else None,
            "tenant_id": str(variant.tenant_id),
            "sku": variant.sku,
            "name": variant.name,
            "attributes": variant.attributes,
            "price_minor": variant.price_minor,
            "currency": variant.currency,
            "stock_quantity": variant.stock_quantity,
            "low_stock_threshold": variant.low_stock_threshold,
            "active": variant.active,
            "created_at": variant.created_at.isoformat(),
            "updated_at": variant.updated_at.isoformat() if variant.updated_at else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid variant ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get variant failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/categories/{category_id}")
async def get_category(
    category_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "catalog.categories.manage",
            None
        )
    )
):
    """Get a specific category by ID"""
    try:
        category = db.query(Category).filter(Category.category_id == uuid.UUID(category_id)).first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        
        # Get parent category if exists
        parent = None
        if category.parent_category_id:
            parent = db.query(Category).filter(Category.category_id == category.parent_category_id).first()
        
        # Get product count in this category
        product_count = db.query(Product).filter(Product.category_id == uuid.UUID(category_id)).count()
        
        return {
            "category_id": str(category.category_id),
            "tenant_id": str(category.tenant_id),
            "name": category.name,
            "code": category.code,
            "description": category.description,
            "parent_category_id": str(category.parent_category_id) if category.parent_category_id else None,
            "parent_category_name": parent.name if parent else None,
            "active": category.active,
            "product_count": product_count,
            "created_at": category.created_at.isoformat(),
            "updated_at": category.updated_at.isoformat() if category.updated_at else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid category ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get category failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# SUBSCRIPTION MANAGEMENT ENDPOINTS
# ==================================================================================

@app.post("/v1/subscriptions/plans", status_code=201)
async def create_subscription_plan(
    req: SubscriptionPlanRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """Create a new subscription plan"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_plan", status="start").inc()
        
        # Check if plan code exists
        existing = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == req.code).first()
        if existing:
            raise HTTPException(status_code=409, detail="Plan code already exists")
        
        # Create plan
        plan = SubscriptionPlan(
            code=req.code,
            name=req.name,
            description=req.description,
            price_yearly_minor=req.price_yearly_minor,
            currency=req.currency,
            active=True
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
        
        req_total.labels(operation="create_plan", status="success").inc()
        req_duration.labels(operation="create_plan").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created subscription plan: {plan.id} ({plan.code})")
        
        return {
            "plan_id": plan.id,
            "code": plan.code,
            "name": plan.name,
            "price_yearly_minor": plan.price_yearly_minor,
            "currency": plan.currency,
            "created_at": plan.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_plan", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_plan", status="error").inc()
        raise HTTPException(status_code=409, detail="Plan code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_plan", status="error").inc()
        logger.error(f"❌ Plan creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/subscriptions/plans")
async def list_subscription_plans(
    active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """List subscription plans"""
    q = db.query(SubscriptionPlan)
    if active is not None:
        q = q.filter(SubscriptionPlan.active == active)
    
    total = q.count()
    plans = q.order_by(SubscriptionPlan.created_at.desc()).limit(limit).offset(offset).all()
    
    return {
        "plans": [
            {
                "plan_id": p.id,
                "code": p.code,
                "name": p.name,
                "description": p.description,
                "price_yearly_minor": p.price_yearly_minor,
                "currency": p.currency,
                "active": p.active,
                "created_at": p.created_at.isoformat()
            }
            for p in plans
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.post("/v1/subscriptions/features", status_code=201)
async def create_feature(
    req: FeatureRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.features.manage"))
):
    """Create a new feature"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_feature", status="start").inc()
        
        # Check if feature code exists
        existing = db.query(Feature).filter(Feature.code == req.code).first()
        if existing:
            raise HTTPException(status_code=409, detail="Feature code already exists")
        
        # Create feature
        feature = Feature(
            id=uuid.uuid4(),
            code=req.code,
            name=req.name,
            description=req.description,
            category=req.category,
            active=True
        )
        db.add(feature)
        db.commit()
        db.refresh(feature)
        
        req_total.labels(operation="create_feature", status="success").inc()
        req_duration.labels(operation="create_feature").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created feature: {feature.id} ({feature.code})")
        
        return {
            "feature_id": str(feature.id),
            "code": feature.code,
            "name": feature.name,
            "category": feature.category,
            "created_at": feature.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_feature", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_feature", status="error").inc()
        raise HTTPException(status_code=409, detail="Feature code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_feature", status="error").inc()
        logger.error(f"❌ Feature creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/subscriptions/features")
async def list_features(
    active: Optional[bool] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(require_permission("subscriptions.features.manage"))
):
    """List features"""
    q = db.query(Feature)
    if active is not None:
        q = q.filter(Feature.active == active)
    if category:
        q = q.filter(Feature.category == category)
    
    total = q.count()
    features = q.order_by(Feature.created_at.desc()).limit(limit).offset(offset).all()
    
    return {
        "features": [
            {
                "feature_id": str(f.id),
                "code": f.code,
                "name": f.name,
                "description": f.description,
                "category": f.category,
                "active": f.active,
                "created_at": f.created_at.isoformat()
            }
            for f in features
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.put("/v1/subscriptions/plans/{plan_code}/features/{feature_code}", status_code=201)
async def add_feature_to_plan(
    plan_code: str,
    feature_code: str,
    req: PlanFeatureRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """Add a feature to a plan with optional limits"""
    start = datetime.now()
    try:
        req_total.labels(operation="add_plan_feature", status="start").inc()
        
        # Verify plan exists
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == plan_code).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Verify feature exists
        feature = db.query(Feature).filter(Feature.code == feature_code).first()
        if not feature:
            raise HTTPException(status_code=404, detail="Feature not found")
        
        # Check if association exists
        existing = db.query(PlanFeature).filter(
            PlanFeature.plan_code == plan_code,
            PlanFeature.feature_code == feature_code
        ).first()
        
        if existing:
            # Update existing
            existing.enabled = True
            existing.limits = req.limits or {}
            db.commit()
            action = "updated"
        else:
            # Create new
            plan_feature = PlanFeature(
                id=uuid.uuid4(),
                plan_code=plan_code,
                feature_code=feature_code,
                enabled=True,
                limits=req.limits or {}
            )
            db.add(plan_feature)
            db.commit()
            action = "added"
        
        req_total.labels(operation="add_plan_feature", status="success").inc()
        req_duration.labels(operation="add_plan_feature").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ {action.capitalize()} feature {feature_code} to plan {plan_code}")
        
        return {
            "plan_code": plan_code,
            "feature_code": feature_code,
            "enabled": True,
            "limits": req.limits or {},
            "action": action
        }
    except HTTPException:
        req_total.labels(operation="add_plan_feature", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="add_plan_feature", status="error").inc()
        logger.error(f"❌ Add feature to plan failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/subscriptions/plans/{plan_code}/features")
async def get_plan_features(
    plan_code: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """Get all features for a plan"""
    try:
        # Verify plan exists
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == plan_code).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Get plan features with feature details
        features = (
            db.query(PlanFeature, Feature)
            .join(Feature, PlanFeature.feature_code == Feature.code)
            .filter(PlanFeature.plan_code == plan_code, PlanFeature.enabled == True)
            .all()
        )
        
        return {
            "plan_code": plan_code,
            "plan_name": plan.name,
            "features": [
                {
                    "feature_code": pf.feature_code,
                    "feature_name": f.name,
                    "category": f.category,
                    "enabled": pf.enabled,
                    "limits": pf.limits or {}
                }
                for pf, f in features
            ],
            "total": len(features)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get plan features failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/v1/subscriptions/plans/{plan_code}/features/{feature_code}")
async def remove_feature_from_plan(
    plan_code: str,
    feature_code: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("subscriptions.plans.manage"))
):
    """Remove a feature from a plan"""
    start = datetime.now()
    try:
        req_total.labels(operation="remove_plan_feature", status="start").inc()
        
        # Find plan feature association
        plan_feature = db.query(PlanFeature).filter(
            PlanFeature.plan_code == plan_code,
            PlanFeature.feature_code == feature_code
        ).first()
        
        if not plan_feature:
            raise HTTPException(status_code=404, detail="Feature not associated with plan")
        
        # Disable the feature
        plan_feature.enabled = False
        db.commit()
        
        req_total.labels(operation="remove_plan_feature", status="success").inc()
        req_duration.labels(operation="remove_plan_feature").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Removed feature {feature_code} from plan {plan_code}")
        
        return {
            "plan_code": plan_code,
            "feature_code": feature_code,
            "removed": True
        }
    except HTTPException:
        req_total.labels(operation="remove_plan_feature", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="remove_plan_feature", status="error").inc()
        logger.error(f"❌ Remove feature from plan failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/subscriptions/subscriptions", status_code=201)
async def create_subscription(
    req: TenantSubscriptionRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "subscriptions.tenant.manage",
            None
        )
    )
):
    """Create a subscription for a tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_subscription", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Verify plan exists
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == req.plan_code).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Check if subscription already exists
        existing = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(req.tenant_id)
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Subscription already exists for tenant")
        
        # Calculate subscription periods
        now = datetime.now(timezone.utc)
        period_days = 365 if req.billing_cycle == "yearly" else 30
        
        # Create subscription
        subscription = TenantSubscription(
            tenant_id=uuid.UUID(req.tenant_id),
            plan_code=req.plan_code,
            payment_method=req.payment_method,
            status="active",
            external_id=f"sub_{req.tenant_id}_{int(now.timestamp())}",
            current_period_start=now,
            current_period_end=now + timedelta(days=period_days)
        )
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
        
        req_total.labels(operation="create_subscription", status="success").inc()
        req_duration.labels(operation="create_subscription").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created subscription: {subscription.id} for tenant {req.tenant_id}")
        
        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "plan_code": subscription.plan_code,
            "status": subscription.status,
            "payment_method": subscription.payment_method,
            "current_period_start": subscription.current_period_start.isoformat(),
            "current_period_end": subscription.current_period_end.isoformat(),
            "created_at": subscription.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_subscription", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_subscription", status="error").inc()
        raise HTTPException(status_code=409, detail="Subscription already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_subscription", status="error").inc()
        logger.error(f"❌ Subscription creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/subscriptions/subscriptions/{tenant_id}")
async def get_subscription(
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "subscriptions.tenant.manage",
            None
        )
    )
):
    """Get subscription details for a tenant"""
    try:
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(tenant_id)
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        # Get plan details
        plan = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.code == subscription.plan_code
        ).first()
        
        # Get plan features
        features = (
            db.query(PlanFeature, Feature)
            .join(Feature, PlanFeature.feature_code == Feature.code)
            .filter(PlanFeature.plan_code == subscription.plan_code, PlanFeature.enabled == True)
            .all()
        )
        
        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "plan_code": subscription.plan_code,
            "plan_name": plan.name if plan else None,
            "status": subscription.status,
            "payment_method": subscription.payment_method,
            "current_period_start": subscription.current_period_start.isoformat() if subscription.current_period_start else None,
            "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
            "features": [
                {
                    "feature_code": pf.feature_code,
                    "feature_name": f.name,
                    "limits": pf.limits or {}
                }
                for pf, f in features
            ],
            "created_at": subscription.created_at.isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get subscription failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/subscriptions/subscriptions/{tenant_id}/renew")
async def renew_subscription(
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "subscriptions.tenant.manage",
            None
        )
    )
):
    """Renew a subscription"""
    start = datetime.now()
    try:
        req_total.labels(operation="renew_subscription", status="start").inc()
        
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(tenant_id)
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        # Extend subscription by 1 year
        if subscription.current_period_end:
            subscription.current_period_end = subscription.current_period_end + timedelta(days=365)
        else:
            subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=365)
        
        subscription.status = "active"
        subscription.canceled_at = None
        subscription.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        req_total.labels(operation="renew_subscription", status="success").inc()
        req_duration.labels(operation="renew_subscription").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Renewed subscription for tenant {tenant_id}")
        
        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "status": subscription.status,
            "new_period_end": subscription.current_period_end.isoformat(),
            "renewed": True
        }
    except HTTPException:
        req_total.labels(operation="renew_subscription", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="renew_subscription", status="error").inc()
        logger.error(f"❌ Renew subscription failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/subscriptions/subscriptions/{tenant_id}/cancel")
async def cancel_subscription(
    tenant_id: str,
    cancel_at_period_end: bool = Query(True),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "subscriptions.tenant.manage",
            None
        )
    )
):
    """Cancel a subscription"""
    start = datetime.now()
    try:
        req_total.labels(operation="cancel_subscription", status="start").inc()
        
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(tenant_id)
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        now = datetime.now(timezone.utc)
        subscription.canceled_at = now
        
        if cancel_at_period_end:
            subscription.status = "canceling"  # Will be canceled at period end
        else:
            subscription.status = "canceled"
        
        subscription.updated_at = now
        db.commit()
        
        req_total.labels(operation="cancel_subscription", status="success").inc()
        req_duration.labels(operation="cancel_subscription").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Canceled subscription for tenant {tenant_id}")
        
        return {
            "subscription_id": subscription.id,
            "tenant_id": str(subscription.tenant_id),
            "status": subscription.status,
            "canceled_at": subscription.canceled_at.isoformat(),
            "canceled": True
        }
    except HTTPException:
        req_total.labels(operation="cancel_subscription", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="cancel_subscription", status="error").inc()
        logger.error(f"❌ Cancel subscription failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# ENTITLEMENTS & USAGE TRACKING ENDPOINTS
# ==================================================================================

@app.post("/v1/entitlements/check")
async def check_entitlement(
    req: CheckEntitlementRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "entitlements.check",
            None
        )
    )
):
    """Check if tenant has access to a feature"""
    try:
        # Get tenant subscription
        subscription = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == uuid.UUID(req.tenant_id),
            TenantSubscription.status == "active"
        ).first()
        
        if not subscription:
            return {
                "allowed": False,
                "reason": "No active subscription found",
                "tenant_id": req.tenant_id,
                "feature_code": req.feature_code
            }
        
        # Check if feature is in plan
        plan_feature = db.query(PlanFeature).filter(
            PlanFeature.plan_code == subscription.plan_code,
            PlanFeature.feature_code == req.feature_code,
            PlanFeature.enabled == True
        ).first()
        
        if not plan_feature:
            return {
                "allowed": False,
                "reason": "Feature not available in subscription plan",
                "tenant_id": req.tenant_id,
                "feature_code": req.feature_code,
                "plan_code": subscription.plan_code
            }
        
        # Check usage limits (if any)
        limits = plan_feature.limits or {}
        rate_limit = limits.get("rate_limit")
        
        if rate_limit:
            # Get current period usage
            now = datetime.now(timezone.utc)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            usage = db.query(SubscriptionUsage).filter(
                SubscriptionUsage.tenant_id == uuid.UUID(req.tenant_id),
                SubscriptionUsage.feature_code == req.feature_code,
                SubscriptionUsage.period_start >= month_start
            ).first()
            
            usage_count = usage.usage_count if usage else 0
            
            if usage_count >= rate_limit:
                return {
                    "allowed": False,
                    "reason": "Usage limit exceeded",
                    "tenant_id": req.tenant_id,
                    "feature_code": req.feature_code,
                    "usage": usage_count,
                    "limit": rate_limit,
                    "remaining": 0
                }
            
            return {
                "allowed": True,
                "tenant_id": req.tenant_id,
                "feature_code": req.feature_code,
                "usage": usage_count,
                "limit": rate_limit,
                "remaining": rate_limit - usage_count
            }
        
        # No limits, access allowed
        return {
            "allowed": True,
            "tenant_id": req.tenant_id,
            "feature_code": req.feature_code,
            "limits": limits
        }
    except Exception as e:
        logger.error(f"❌ Check entitlement failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/entitlements/usage/record", status_code=201)
async def record_usage(
    req: RecordUsageRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "entitlements.usage.record",
            None
        )
    )
):
    """Record feature usage for a tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="record_usage", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Verify feature exists
        feature = db.query(Feature).filter(Feature.code == req.feature_code).first()
        if not feature:
            raise HTTPException(status_code=404, detail="Feature not found")
        
        # Calculate current period
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Calculate month end
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1, day=1) - timedelta(days=1)
        
        # Find or create usage record
        usage = db.query(SubscriptionUsage).filter(
            SubscriptionUsage.tenant_id == uuid.UUID(req.tenant_id),
            SubscriptionUsage.feature_code == req.feature_code,
            SubscriptionUsage.usage_type == req.usage_type,
            SubscriptionUsage.period_start >= month_start,
            SubscriptionUsage.period_start < month_end
        ).first()
        
        if usage:
            # Update existing
            usage.usage_count += req.count
            usage.updated_at = now
        else:
            # Create new
            usage = SubscriptionUsage(
                id=uuid.uuid4(),
                tenant_id=uuid.UUID(req.tenant_id),
                feature_code=req.feature_code,
                usage_type=req.usage_type,
                usage_count=req.count,
                period_start=month_start,
                period_end=month_end
            )
            db.add(usage)
        
        db.commit()
        db.refresh(usage)
        
        req_total.labels(operation="record_usage", status="success").inc()
        req_duration.labels(operation="record_usage").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Recorded usage: {req.count} for feature {req.feature_code}, tenant {req.tenant_id}")
        
        return {
            "tenant_id": req.tenant_id,
            "feature_code": req.feature_code,
            "usage_type": req.usage_type,
            "count": req.count,
            "total_usage": usage.usage_count,
            "period_start": usage.period_start.isoformat(),
            "period_end": usage.period_end.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="record_usage", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="record_usage", status="error").inc()
        logger.error(f"❌ Record usage failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/entitlements/usage/{tenant_id}")
async def get_usage_summary(
    tenant_id: str,
    feature_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "entitlements.usage.record",
            None
        )
    )
):
    """Get usage summary for a tenant"""
    try:
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Build query
        q = db.query(SubscriptionUsage).filter(SubscriptionUsage.tenant_id == uuid.UUID(tenant_id))
        if feature_code:
            q = q.filter(SubscriptionUsage.feature_code == feature_code)
        
        # Get current period usage
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_usage = q.filter(SubscriptionUsage.period_start >= month_start).all()
        
        return {
            "tenant_id": tenant_id,
            "current_period": {
                "start": month_start.isoformat(),
                "usage": [
                    {
                        "feature_code": u.feature_code,
                        "usage_type": u.usage_type,
                        "count": u.usage_count,
                        "period_start": u.period_start.isoformat(),
                        "period_end": u.period_end.isoformat()
                    }
                    for u in current_usage
                ]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get usage summary failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# APPROVALS MANAGEMENT ENDPOINTS
# ==================================================================================

@app.post("/v1/approvals/chains", status_code=201)
async def create_approval_chain(
    req: ApprovalChainRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.chains.manage",
            None
        )
    )
):
    """Create a new approval chain"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_approval_chain", status="start").inc()
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Create approval chain
        chain = ApprovalChain(
            chain_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            description=req.description,
            chain_type=req.chain_type,
            is_active=req.is_active
        )
        db.add(chain)
        db.commit()
        db.refresh(chain)
        
        req_total.labels(operation="create_approval_chain", status="success").inc()
        req_duration.labels(operation="create_approval_chain").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created approval chain: {chain.chain_id} ({chain.name})")
        
        return {
            "chain_id": str(chain.chain_id),
            "tenant_id": str(chain.tenant_id),
            "name": chain.name,
            "description": chain.description,
            "chain_type": chain.chain_type,
            "is_active": chain.is_active,
            "created_at": chain.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_approval_chain", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        req_total.labels(operation="create_approval_chain", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_approval_chain", status="error").inc()
        logger.error(f"❌ Approval chain creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/approvals/chains")
async def list_approval_chains(
    tenant_id: Optional[str] = Query(None),
    chain_type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.chains.manage",
            None
        )
    )
):
    """List approval chains"""
    try:
        q = db.query(ApprovalChain)
        if tenant_id:
            q = q.filter(ApprovalChain.tenant_id == uuid.UUID(tenant_id))
        if chain_type:
            q = q.filter(ApprovalChain.chain_type == chain_type)
        if is_active is not None:
            q = q.filter(ApprovalChain.is_active == is_active)
        
        total = q.count()
        chains = q.order_by(ApprovalChain.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "chains": [
                {
                    "chain_id": str(c.chain_id),
                    "tenant_id": str(c.tenant_id),
                    "name": c.name,
                    "description": c.description,
                    "chain_type": c.chain_type,
                    "is_active": c.is_active,
                    "created_at": c.created_at.isoformat()
                }
                for c in chains
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except Exception as e:
        logger.error(f"❌ List approval chains failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/approvals/chains/steps", status_code=201)
async def create_approval_chain_step(
    req: ApprovalChainStepRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.chains.manage",
            None
        )
    )
):
    """Create a new approval chain step"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_chain_step", status="start").inc()
        
        # Verify chain exists
        chain = db.query(ApprovalChain).filter(
            ApprovalChain.chain_id == uuid.UUID(req.approval_chain_id)
        ).first()
        if not chain:
            raise HTTPException(status_code=404, detail="Approval chain not found")
        
        # Create step
        step = ApprovalChainStep(
            id=uuid.uuid4(),
            approval_chain_id=uuid.UUID(req.approval_chain_id),
            step_number=req.step_number,
            approver_role=req.approver_role,
            approver_scope=req.approver_scope,
            escalation_after_hours=req.escalation_after_hours,
            is_required=req.is_required
        )
        db.add(step)
        db.commit()
        db.refresh(step)
        
        req_total.labels(operation="create_chain_step", status="success").inc()
        req_duration.labels(operation="create_chain_step").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created approval chain step: {step.id}")
        
        return {
            "id": str(step.id),
            "approval_chain_id": str(step.approval_chain_id),
            "step_number": step.step_number,
            "approver_role": step.approver_role,
            "approver_scope": step.approver_scope,
            "escalation_after_hours": step.escalation_after_hours,
            "is_required": step.is_required,
            "created_at": step.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_chain_step", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid approval chain ID format")
    except HTTPException:
        req_total.labels(operation="create_chain_step", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_chain_step", status="error").inc()
        logger.error(f"❌ Chain step creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/approvals/chains/{chain_id}/steps")
async def list_chain_steps(
    chain_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.chains.manage",
            None
        )
    )
):
    """List steps for an approval chain"""
    try:
        # Verify chain exists
        chain = db.query(ApprovalChain).filter(ApprovalChain.chain_id == uuid.UUID(chain_id)).first()
        if not chain:
            raise HTTPException(status_code=404, detail="Approval chain not found")
        
        steps = db.query(ApprovalChainStep).filter(
            ApprovalChainStep.approval_chain_id == uuid.UUID(chain_id)
        ).order_by(ApprovalChainStep.step_number).all()
        
        return {
            "chain_id": chain_id,
            "chain_name": chain.name,
            "steps": [
                {
                    "id": str(s.id),
                    "step_number": s.step_number,
                    "approver_role": s.approver_role,
                    "approver_scope": s.approver_scope,
                    "escalation_after_hours": s.escalation_after_hours,
                    "is_required": s.is_required,
                    "created_at": s.created_at.isoformat()
                }
                for s in steps
            ],
            "total": len(steps)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chain ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ List chain steps failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/approvals/requests", status_code=201)
async def create_approval_request(
    req: ApprovalRequestRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.requests.create",
            None
        )
    )
):
    """Create a new approval request"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_approval_request", status="start").inc()
        
        # Verify tenant, chain, and user exist
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        chain = db.query(ApprovalChain).filter(ApprovalChain.chain_id == uuid.UUID(req.chain_id)).first()
        if not chain:
            raise HTTPException(status_code=404, detail="Approval chain not found")
        
        user = db.query(User).filter(User.user_id == uuid.UUID(req.requested_by)).first()
        if not user:
            raise HTTPException(status_code=404, detail="Requester user not found")
        
        # Generate request number
        request_number = f"REQ-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        
        # Create approval request
        approval_request = ApprovalRequest(
            request_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            chain_id=uuid.UUID(req.chain_id),
            request_number=request_number,
            request_type=req.request_type,
            request_data=req.request_data,
            requested_by=uuid.UUID(req.requested_by),
            request_status="pending",
            current_step_number=1,
            total_amount_minor=req.total_amount_minor,
            currency=req.currency,
            due_date=req.due_date
        )
        db.add(approval_request)
        db.flush()  # Get the request_id
        
        # Get chain steps and create approver assignments
        steps = db.query(ApprovalChainStep).filter(
            ApprovalChainStep.approval_chain_id == uuid.UUID(req.chain_id)
        ).order_by(ApprovalChainStep.step_number).all()
        
        for step in steps:
            approver_user_ids = resolve_approvers_for_step(
                db,
                step,
                req.tenant_id,
                req.request_data
            )
            if not approver_user_ids:
                logger.warning(
                    "No approvers resolved for step %s in chain %s; falling back to requester",
                    step.step_number,
                    req.chain_id
                )
                approver_user_ids = [req.requested_by]

            for approver_user_id in approver_user_ids:
                approver = ApprovalRequestApprover(
                    id=uuid.uuid4(),
                    request_id=approval_request.request_id,
                    approver_user_id=uuid.UUID(approver_user_id),
                    approver_role=step.approver_role,
                    step_number=step.step_number,
                    status="pending"
                )
                db.add(approver)
        
        db.commit()
        db.refresh(approval_request)
        
        req_total.labels(operation="create_approval_request", status="success").inc()
        req_duration.labels(operation="create_approval_request").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created approval request: {approval_request.request_id}")
        
        return {
            "request_id": str(approval_request.request_id),
            "request_number": approval_request.request_number,
            "tenant_id": str(approval_request.tenant_id),
            "chain_id": str(approval_request.chain_id),
            "request_type": approval_request.request_type,
            "requested_by": str(approval_request.requested_by),
            "request_status": approval_request.request_status,
            "total_amount_minor": approval_request.total_amount_minor,
            "currency": approval_request.currency,
            "due_date": approval_request.due_date.isoformat() if approval_request.due_date else None,
            "created_at": approval_request.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_approval_request", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="create_approval_request", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_approval_request", status="error").inc()
        logger.error(f"❌ Approval request creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/approvals/requests")
async def list_approval_requests(
    tenant_id: Optional[str] = Query(None),
    request_type: Optional[str] = Query(None),
    request_status: Optional[str] = Query(None),
    requested_by: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.requests.view",
            None
        )
    )
):
    """List approval requests"""
    try:
        q = db.query(ApprovalRequest)
        if tenant_id:
            q = q.filter(ApprovalRequest.tenant_id == uuid.UUID(tenant_id))
        if request_type:
            q = q.filter(ApprovalRequest.request_type == request_type)
        if request_status:
            q = q.filter(ApprovalRequest.request_status == request_status)
        if requested_by:
            q = q.filter(ApprovalRequest.requested_by == uuid.UUID(requested_by))
        
        total = q.count()
        requests = q.order_by(ApprovalRequest.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "requests": [
                {
                    "request_id": str(r.request_id),
                    "request_number": r.request_number,
                    "tenant_id": str(r.tenant_id),
                    "chain_id": str(r.chain_id),
                    "request_type": r.request_type,
                    "requested_by": str(r.requested_by),
                    "request_status": r.request_status,
                    "current_step_number": r.current_step_number,
                    "total_amount_minor": r.total_amount_minor,
                    "currency": r.currency,
                    "due_date": r.due_date.isoformat() if r.due_date else None,
                    "created_at": r.created_at.isoformat()
                }
                for r in requests
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"❌ List approval requests failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/approvals/requests/{request_id}")
async def get_approval_request(
    request_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.requests.view",
            None
        )
    )
):
    """Get approval request details"""
    try:
        request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).first()
        
        if not request:
            raise HTTPException(status_code=404, detail="Approval request not found")
        
        # Get approvers
        approvers = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id)
        ).order_by(ApprovalRequestApprover.step_number).all()
        
        return {
            "request_id": str(request.request_id),
            "request_number": request.request_number,
            "tenant_id": str(request.tenant_id),
            "chain_id": str(request.chain_id),
            "request_type": request.request_type,
            "request_data": request.request_data,
            "requested_by": str(request.requested_by),
            "request_status": request.request_status,
            "current_step_number": request.current_step_number,
            "total_amount_minor": request.total_amount_minor,
            "currency": request.currency,
            "due_date": request.due_date.isoformat() if request.due_date else None,
            "completed_date": request.completed_date.isoformat() if request.completed_date else None,
            "approvers": [
                {
                    "id": str(a.id),
                    "approver_user_id": str(a.approver_user_id),
                    "approver_role": a.approver_role,
                    "step_number": a.step_number,
                    "status": a.status,
                    "notes": a.notes,
                    "responded_at": a.responded_at.isoformat() if a.responded_at else None
                }
                for a in approvers
            ],
            "created_at": request.created_at.isoformat()
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get approval request failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/approvals/requests/{request_id}/approvers")
async def get_request_approvers(
    request_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.requests.view",
            None
        )
    )
):
    """Get all approvers for an approval request"""
    try:
        # Verify request exists
        request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).first()
        
        if not request:
            raise HTTPException(status_code=404, detail="Approval request not found")
        
        # Get approvers with user details
        approvers = db.query(ApprovalRequestApprover, User).join(
            User, ApprovalRequestApprover.approver_user_id == User.user_id
        ).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id)
        ).order_by(ApprovalRequestApprover.step_number).all()
        
        return {
            "request_id": request_id,
            "request_number": request.request_number,
            "request_status": request.request_status,
            "current_step_number": request.current_step_number,
            "approvers": [
                {
                    "id": str(a.id),
                    "approver_user_id": str(a.approver_user_id),
                    "approver_email": u.email,
                    "approver_name": u.display_name,
                    "approver_role": a.approver_role,
                    "step_number": a.step_number,
                    "status": a.status,
                    "notes": a.notes,
                    "responded_at": a.responded_at.isoformat() if a.responded_at else None,
                    "escalation_sent": a.escalation_sent,
                    "created_at": a.created_at.isoformat()
                }
                for a, u in approvers
            ],
            "total": len(approvers)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get request approvers failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/approvals/requests/{request_id}/respond")
async def respond_to_approval_request(
    request_id: str,
    req: ApprovalResponseRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(
        require_permission(
            "approvals.requests.respond",
            None
        )
    )
):
    """Respond to an approval request (approve or deny)"""
    start = datetime.now()
    try:
        req_total.labels(operation="respond_approval", status="start").inc()
        
        # Get the approval request
        approval_request = db.query(ApprovalRequest).filter(
            ApprovalRequest.request_id == uuid.UUID(request_id)
        ).first()
        
        if not approval_request:
            raise HTTPException(status_code=404, detail="Approval request not found")
        
        if str(approval_request.tenant_id) != ctx.tenant_id and "*" not in ctx.permissions:
            raise HTTPException(status_code=403, detail="Request outside of scope")
        
        if approval_request.request_status != "pending":
            raise HTTPException(status_code=400, detail=f"Request is not pending (status: {approval_request.request_status})")
        
        # Find the approver assignment
        approver = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.request_id == uuid.UUID(request_id),
            ApprovalRequestApprover.approver_user_id == uuid.UUID(req.approver_user_id),
            ApprovalRequestApprover.step_number == approval_request.current_step_number,
            ApprovalRequestApprover.status == "pending"
        ).first()
        
        if not approver:
            raise HTTPException(status_code=404, detail="Approver assignment not found or already responded")

        if req.approver_user_id != ctx.user_id and req.approver_user_id not in ctx.manager_of:
            raise HTTPException(status_code=403, detail="Not authorized to respond for this approver")
        
        # Update approver response
        approver.status = "approved" if req.approved else "denied"
        approver.notes = req.notes
        approver.responded_at = datetime.now(timezone.utc)
        
        # Update request status
        if not req.approved:
            # Denial at any step fails the request
            approval_request.request_status = "denied"
            approval_request.completed_date = datetime.now(timezone.utc)
        else:
            # Check if there are more steps
            max_step = db.query(func.max(ApprovalChainStep.step_number)).filter(
                ApprovalChainStep.approval_chain_id == approval_request.chain_id
            ).scalar()
            
            if approval_request.current_step_number >= max_step:
                # Last step completed and approved
                approval_request.request_status = "approved"
                approval_request.completed_date = datetime.now(timezone.utc)
            else:
                # Move to next step
                approval_request.current_step_number += 1
        
        approval_request.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        req_total.labels(operation="respond_approval", status="success").inc()
        req_duration.labels(operation="respond_approval").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Approval request {request_id} {'approved' if req.approved else 'denied'} by {req.approver_user_id}")
        
        return {
            "request_id": request_id,
            "approver_user_id": req.approver_user_id,
            "status": approver.status,
            "notes": approver.notes,
            "responded_at": approver.responded_at.isoformat(),
            "request_status": approval_request.request_status,
            "current_step": approval_request.current_step_number,
            "completed": approval_request.request_status in ["approved", "denied"]
        }
    except ValueError:
        req_total.labels(operation="respond_approval", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="respond_approval", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="respond_approval", status="error").inc()
        logger.error(f"❌ Respond to approval failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# PRICING SERVICE - SIMPLE IMPLEMENTATION
# ==================================================================================

@app.post("/v1/pricing/pricebooks", status_code=201)
async def create_pricebook(
    req: PricebookRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.products.manage"))
):
    """Create a new pricebook for a store"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_pricebook", status="start").inc()
        
        # Verify store exists
        store = db.query(Store).filter(Store.store_id == uuid.UUID(req.store_id)).first()
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        
        # Create pricebook
        pricebook = Pricebook(
            pricebook_id=uuid.uuid4(),
            store_id=uuid.UUID(req.store_id),
            tenant_id=store.tenant_id,
            name=req.name,
            description=req.description,
            currency=req.currency,
            is_active=True
        )
        db.add(pricebook)
        db.commit()
        db.refresh(pricebook)
        
        req_total.labels(operation="create_pricebook", status="success").inc()
        req_duration.labels(operation="create_pricebook").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created pricebook: {pricebook.pricebook_id} ({pricebook.name})")
        
        return {
            "pricebook_id": str(pricebook.pricebook_id),
            "store_id": str(pricebook.store_id),
            "tenant_id": str(pricebook.tenant_id),
            "name": pricebook.name,
            "description": pricebook.description,
            "currency": pricebook.currency,
            "is_active": pricebook.is_active,
            "created_at": pricebook.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_pricebook", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid store ID format")
    except HTTPException:
        req_total.labels(operation="create_pricebook", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_pricebook", status="error").inc()
        logger.error(f"❌ Pricebook creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/pricing/pricebooks")
async def list_pricebooks(
    store_id: Optional[str] = Query(None, description="Filter by store ID"),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.products.view"))
):
    """List pricebooks with optional store filtering"""
    try:
        q = db.query(Pricebook).filter(Pricebook.is_active == True)
        if store_id:
            q = q.filter(Pricebook.store_id == uuid.UUID(store_id))
        
        total = q.count()
        pricebooks = q.order_by(Pricebook.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "pricebooks": [
                {
                    "pricebook_id": str(p.pricebook_id),
                    "store_id": str(p.store_id),
                    "tenant_id": str(p.tenant_id),
                    "name": p.name,
                    "description": p.description,
                    "currency": p.currency,
                    "is_active": p.is_active,
                    "created_at": p.created_at.isoformat()
                }
                for p in pricebooks
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        logger.error(f"❌ List pricebooks failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/pricing/pricebooks/{pricebook_id}/rules", status_code=201)
async def create_price_rule(
    pricebook_id: str,
    req: PriceRuleRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.products.manage"))
):
    """Create a price rule for a pricebook"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_price_rule", status="start").inc()
        
        # Verify pricebook exists
        pricebook = db.query(Pricebook).filter(Pricebook.pricebook_id == uuid.UUID(pricebook_id)).first()
        if not pricebook:
            raise HTTPException(status_code=404, detail="Pricebook not found")
        
        # Verify product if provided
        if req.product_id:
            product = db.query(Product).filter(Product.product_id == uuid.UUID(req.product_id)).first()
            if not product:
                raise HTTPException(status_code=404, detail="Product not found")
        
        # Verify variant if provided
        if req.variant_id:
            variant = db.query(Variant).filter(Variant.variant_id == uuid.UUID(req.variant_id)).first()
            if not variant:
                raise HTTPException(status_code=404, detail="Variant not found")
        
        # Create price rule
        rule = PriceRule(
            rule_id=uuid.uuid4(),
            pricebook_id=uuid.UUID(pricebook_id),
            product_id=uuid.UUID(req.product_id) if req.product_id else None,
            variant_id=uuid.UUID(req.variant_id) if req.variant_id else None,
            rule_type=req.rule_type,
            rule_value=req.rule_value,
            min_quantity=req.min_quantity,
            max_quantity=req.max_quantity,
            valid_from=req.valid_from,
            valid_until=req.valid_until,
            is_active=True
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        
        req_total.labels(operation="create_price_rule", status="success").inc()
        req_duration.labels(operation="create_price_rule").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Created price rule: {rule.rule_id} for pricebook {pricebook_id}")
        
        return {
            "rule_id": str(rule.rule_id),
            "pricebook_id": str(rule.pricebook_id),
            "product_id": str(rule.product_id) if rule.product_id else None,
            "variant_id": str(rule.variant_id) if rule.variant_id else None,
            "rule_type": rule.rule_type,
            "rule_value": rule.rule_value,
            "min_quantity": rule.min_quantity,
            "max_quantity": rule.max_quantity,
            "valid_from": rule.valid_from.isoformat() if rule.valid_from else None,
            "valid_until": rule.valid_until.isoformat() if rule.valid_until else None,
            "is_active": rule.is_active,
            "created_at": rule.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_price_rule", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="create_price_rule", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_price_rule", status="error").inc()
        logger.error(f"❌ Price rule creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/pricing/pricebooks/{pricebook_id}/rules")
async def list_price_rules(
    pricebook_id: str,
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.products.view"))
):
    """List all price rules for a pricebook"""
    try:
        # Verify pricebook exists
        pricebook = db.query(Pricebook).filter(Pricebook.pricebook_id == uuid.UUID(pricebook_id)).first()
        if not pricebook:
            raise HTTPException(status_code=404, detail="Pricebook not found")
        
        q = db.query(PriceRule).filter(PriceRule.pricebook_id == uuid.UUID(pricebook_id))
        total = q.count()
        rules = q.order_by(PriceRule.created_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "pricebook_id": pricebook_id,
            "rules": [
                {
                    "rule_id": str(r.rule_id),
                    "product_id": str(r.product_id) if r.product_id else None,
                    "variant_id": str(r.variant_id) if r.variant_id else None,
                    "rule_type": r.rule_type,
                    "rule_value": r.rule_value,
                    "min_quantity": r.min_quantity,
                    "max_quantity": r.max_quantity,
                    "valid_from": r.valid_from.isoformat() if r.valid_from else None,
                    "valid_until": r.valid_until.isoformat() if r.valid_until else None,
                    "is_active": r.is_active,
                    "created_at": r.created_at.isoformat()
                }
                for r in rules
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid pricebook ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ List price rules failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/pricing/calculate")
async def calculate_price(
    req: PriceCalculationRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.products.view"))
):
    """Calculate price for a product based on pricebook rules"""
    start = datetime.now()
    try:
        req_total.labels(operation="calculate_price", status="start").inc()
        
        # Get base price from product or variant
        base_price_minor = 0
        currency = "GBP"
        product_name = ""
        
        if req.variant_id:
            # Get variant price
            variant = db.query(Variant).filter(Variant.variant_id == uuid.UUID(req.variant_id)).first()
            if not variant:
                raise HTTPException(status_code=404, detail="Variant not found")
            base_price_minor = variant.price_minor
            currency = variant.currency
            product_name = variant.name
        else:
            # Get product price
            product = db.query(Product).filter(Product.product_id == uuid.UUID(req.product_id)).first()
            if not product:
                raise HTTPException(status_code=404, detail="Product not found")
            base_price_minor = product.base_price_minor
            currency = product.currency
            product_name = product.name
        
        # Verify pricebook exists
        pricebook = db.query(Pricebook).filter(Pricebook.pricebook_id == uuid.UUID(req.pricebook_id)).first()
        if not pricebook:
            raise HTTPException(status_code=404, detail="Pricebook not found")
        
        # Get all active rules for this product in this pricebook
        now = datetime.now(timezone.utc)
        q = db.query(PriceRule).filter(
            PriceRule.pricebook_id == uuid.UUID(req.pricebook_id),
            PriceRule.is_active == True
        )
        
        # Filter by product or variant
        if req.variant_id:
            q = q.filter(
                (PriceRule.variant_id == uuid.UUID(req.variant_id)) |
                (PriceRule.product_id == uuid.UUID(req.product_id)) |
                ((PriceRule.product_id == None) & (PriceRule.variant_id == None))
            )
        else:
            q = q.filter(
                (PriceRule.product_id == uuid.UUID(req.product_id)) |
                ((PriceRule.product_id == None) & (PriceRule.variant_id == None))
            )
        
        # Filter by date validity
        q = q.filter(
            (PriceRule.valid_from == None) | (PriceRule.valid_from <= now)
        ).filter(
            (PriceRule.valid_until == None) | (PriceRule.valid_until >= now)
        )
        
        # Filter by quantity
        q = q.filter(
            (PriceRule.min_quantity == None) | (PriceRule.min_quantity <= req.quantity)
        ).filter(
            (PriceRule.max_quantity == None) | (PriceRule.max_quantity >= req.quantity)
        )
        
        # Order by specificity: variant-specific > product-specific > general
        rules = q.order_by(
            PriceRule.variant_id.desc().nullslast(),
            PriceRule.product_id.desc().nullslast(),
            PriceRule.created_at.desc()
        ).all()
        
        # Apply rules
        calculated_price_minor = base_price_minor
        applied_rules = []
        
        for rule in rules:
            old_price = calculated_price_minor
            
            if rule.rule_type == "fixed":
                # Fixed price overrides
                calculated_price_minor = rule.rule_value
            elif rule.rule_type == "percentage":
                # Percentage adjustment (rule_value in basis points, e.g., 1000 = 10%)
                adjustment = (calculated_price_minor * rule.rule_value) // 10000
                calculated_price_minor = calculated_price_minor + adjustment
            elif rule.rule_type == "discount":
                # Discount (rule_value in basis points, e.g., 1000 = 10% off)
                discount = (calculated_price_minor * rule.rule_value) // 10000
                calculated_price_minor = calculated_price_minor - discount
            
            applied_rules.append({
                "rule_id": str(rule.rule_id),
                "rule_type": rule.rule_type,
                "rule_value": rule.rule_value,
                "price_before": old_price,
                "price_after": calculated_price_minor
            })
        
        req_total.labels(operation="calculate_price", status="success").inc()
        req_duration.labels(operation="calculate_price").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Calculated price for product {req.product_id}: {base_price_minor} -> {calculated_price_minor}")
        
        return {
            "product_id": req.product_id,
            "variant_id": req.variant_id,
            "pricebook_id": req.pricebook_id,
            "quantity": req.quantity,
            "product_name": product_name,
            "base_price_minor": base_price_minor,
            "calculated_price_minor": calculated_price_minor,
            "currency": currency,
            "rules_applied_count": len(applied_rules),
            "applied_rules": applied_rules
        }
    except ValueError:
        req_total.labels(operation="calculate_price", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        req_total.labels(operation="calculate_price", status="error").inc()
        raise
    except Exception as e:
        req_total.labels(operation="calculate_price", status="error").inc()
        logger.error(f"❌ Price calculation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"🚀 Starting {SERVICE_NAME} v{SERVICE_VERSION}")
    logger.info(f"📊 Database: {SETTINGS.DATABASE_URL.split('@')[1] if '@' in SETTINGS.DATABASE_URL else 'configured'}")
    logger.info(f"💾 Redis: {'enabled' if redis_client else 'disabled'}")
    logger.info(f"🔒 RLS: enabled for tenant isolation")
    
    uvicorn.run(app, host="0.0.0.0", port=SETTINGS.PORT)

