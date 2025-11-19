# ==================================================================================
# AUTHENTICATION & AUTHORIZATION
# ==================================================================================
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, List, Tuple, Any

import bcrypt
import jwt
from fastapi import HTTPException, Depends, Header
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from starlette import status

from Models import User, UserOrgAssignment, RoleScope, RolePermission, Permission, Tenant, Role, UserRole
from Schemas import UserContext
from core.config import SETTINGS
from core.db_config import SessionLocal
from utils.logger import logger
from utils.redis_client import redis_client

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
    ("catalog.products.vendor.create", "Vendors can create their own products"),
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