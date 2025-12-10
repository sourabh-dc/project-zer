# ==================================================================================
# AUTHENTICATION & AUTHORIZATION
# ==================================================================================
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, List, Tuple, Any

import bcrypt
import httpx
import jwt
from fastapi import HTTPException, Depends, Header
from jose import JWTError
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from starlette import status

from Models import User, UserOrgAssignment, RoleScope, RolePermission, Permission, Tenant, Role, UserRole
from Schemas import UserContext
from core.config import SETTINGS
from core.db_config import SessionLocal
from utils.logger import logger
from utils.redis_client import redis_client

PERMISSION_CATALOG: List[Tuple[str, str]] = [
    # Tenants
    ("tenants.create", "Create tenants"),
    ("tenants.view", "View tenant profiles"),
    ("tenants.update", "Update tenant details/settings"),
    ("tenants.deactivate", "Deactivate tenants"),
    ("tenants.delete", "Delete tenants (hard/soft)"),
    ("tenants.assign_site", "Link/unlink tenants to sites"),
    ("tenants.billing.view", "View tenant billing profile"),
    ("tenants.billing.update", "Update tenant billing profile"),
    ("tenants.plan.change", "Change tenant subscription plan"),
    ("tenants.features.configure", "Enable/disable tenant features"),
    ("tenants.keys.manage", "Rotate tenant API keys"),

    # Sites
    ("sites.create", "Create sites"),
    ("sites.view", "View sites"),
    ("sites.update", "Update sites"),
    ("sites.delete", "Delete sites"),
    ("sites.manage", "Full site management"),

    # Stores
    ("stores.create", "Create stores"),
    ("stores.view", "View stores"),
    ("stores.update", "Update stores"),
    ("stores.delete", "Delete stores"),
    ("stores.manage", "Full store management"),
    ("stores.products.manage", "Manage store product assortment"),
    ("stores.products.view", "View store product assortment"),
    ("stores.products.create", "Create store assortment"),
    ("stores.products.delete", "Delete store assortment"),

    # Users
    ("users.create", "Create users"),
    ("users.view", "View users"),
    ("users.update", "Update users"),
    ("users.deactivate", "Deactivate/activate users"),
    ("users.password.reset", "Reset user passwords"),
    ("users.roles.assign", "Assign roles to users"),
    ("users.roles.view", "View user roles"),
    ("users.scopes.assign", "Assign scopes to users"),
    ("users.api_keys.manage", "Manage user API keys"),
    ("users.manage", "Full user management"),

    # Roles & permissions
    ("roles.create", "Create roles"),
    ("roles.view", "View roles"),
    ("roles.update", "Update roles"),
    ("roles.delete", "Delete roles"),
    ("roles.assign", "Assign roles to users"),
    ("roles.scopes.manage", "Manage role scopes"),
    ("roles.copy", "Duplicate roles"),
    ("permissions.view", "View permission catalog"),
    ("admin.permissions.manage", "Manage permission catalog"),
    ("admin.roles.manage", "Manage roles"),
    ("admin.scopes.manage", "Manage RLS scopes"),

    # Org / departments
    ("org_units.create", "Create org/department units"),
    ("org_units.view", "View org/department tree"),
    ("org_units.update", "Update org units"),
    ("org_units.delete", "Delete org units"),
    ("org_units.assign", "Assign users to org units"),
    ("org_units.manage", "Full org unit management"),
    ("org_units.tree.export", "Export org structure"),

    # Vendors
    ("vendors.create", "Create vendors"),
    ("vendors.view", "View vendors"),
    ("vendors.update", "Update vendors"),
    ("vendors.delete", "Delete vendors"),
    ("vendors.manage", "Full vendor management"),

    # Cost centres
    ("cost_centres.create", "Create cost centres"),
    ("cost_centres.view", "View cost centres"),
    ("cost_centres.update", "Update cost centres"),
    ("cost_centres.delete", "Delete cost centres"),
    ("cost_centres.assign_users", "Assign users to cost centres"),
    ("cost_centres.budget.allocate", "Allocate budget to cost centres"),
    ("cost_centres.budget.adjust", "Adjust cost centre budgets"),
    ("cost_centres.reports.view", "View cost centre reports"),
    ("cost_centres.manage", "Full cost centre management"),

    # Budgets
    ("budgets.manage", "Manage budgets"),
    ("budgets.manage.subordinates", "Manage budgets for subordinates only"),
    ("budgets.view", "View budgets"),
    ("budgets.approval_rules.manage", "Manage budget approval rules"),
    ("budgets.workflow.manage", "Manage budget workflows"),
    ("budgets.instant.request", "Request instant budget"),
    ("budgets.instant.approve", "Approve instant budget"),
    ("budgets.reports.view", "View budget reports"),
    ("budgets.audit.view", "View budget audit trail"),

    # Approvals
    ("approvals.chains.manage", "Manage approval chains/steps"),
    ("approvals.steps.manage", "Manage individual approval steps"),
    ("approvals.requests.create", "Create approval requests"),
    ("approvals.requests.view", "View approval requests"),
    ("approvals.requests.respond", "Approve/reject requests"),
    ("approvals.requests.cancel", "Cancel approval requests"),
    ("approvals.delegations.manage", "Manage approval delegations"),
    ("approvals.reports.view", "View approval reports"),

    # Catalog / products
    ("catalog.products.manage", "Manage products"),
    ("catalog.products.view", "View products"),
    ("catalog.products.create", "Create products"),
    ("catalog.products.delete", "Delete products"),

    # Store assortment (duplicate clarity)
    ("stores.products.view", "View store assortment (duplicate)"),
    ("stores.products.manage", "Manage store assortment (duplicate)"),
    ("stores.products.create", "Create store assortment (duplicate)"),
    ("stores.products.delete", "Delete store assortment (duplicate)"),

    # Entitlements
    ("entitlements.check", "Check entitlements"),
    ("entitlements.usage.record", "Record entitlement usage"),
    ("entitlements.usage.view", "View entitlement usage"),
    ("entitlements.usage.manage", "Manage/reset entitlement usage"),
    ("entitlements.features.manage", "Manage feature definitions"),
    ("entitlements.features.view", "View feature definitions"),
    ("entitlements.metering.manage", "Manage metering setup"),

    # Subscriptions
    ("subscriptions.plans.manage", "Manage subscription plans"),
    ("subscriptions.plans.view", "View subscription plans"),
    ("subscriptions.features.manage", "Manage subscription features"),
    ("subscriptions.features.view", "View subscription features"),
    ("subscriptions.tenant.manage", "Manage tenant subscriptions"),
    ("subscriptions.tenant.view", "View tenant subscriptions"),
    ("subscriptions.trials.manage", "Manage trials"),
    ("subscriptions.cancellations.manage", "Manage cancellations"),
    ("subscriptions.invoices.view", "View subscription invoices"),
    ("subscriptions.renewals.manage", "Manage renewals"),

    # Payments
    ("payments.methods.manage", "Manage payment methods"),
    ("payments.methods.view", "View payment methods"),
    ("payments.charge", "Charge payments"),
    ("payments.payouts.manage", "Manage payouts"),
    ("payments.disputes.manage", "Manage disputes/chargebacks"),
    ("payments.webhooks.manage", "Manage payment webhooks"),

    # Orders
    ("orders.create", "Create orders"),
    ("orders.view", "View orders"),
    ("orders.update", "Update orders"),
    ("orders.cancel", "Cancel orders"),
    ("orders.export", "Export orders"),

    # Ledger
    ("ledger.entries.post", "Post ledger entries"),
    ("ledger.entries.view", "View ledger entries"),
    ("ledger.accounts.manage", "Manage ledger accounts"),
    ("ledger.reports.view", "View ledger reports"),
    ("ledger.export", "Export ledger data"),

    # Billing
    ("billing.invoices.create", "Create invoices"),
    ("billing.invoices.view", "View invoices"),
    ("billing.invoices.send", "Send invoices"),
    ("billing.invoices.void", "Void invoices"),
    ("billing.statements.view", "View billing statements"),

    # Provisioning
    ("provisioning.import", "Bulk import tenants/sites/stores/users"),
    ("provisioning.export", "Export provisioning data"),
    ("provisioning.templates.manage", "Manage provisioning templates"),

    # Audit
    ("audit.logs.view", "View audit logs"),
    ("audit.logs.export", "Export audit logs"),
    ("audit.trails.view", "View detailed trails"),
]

ROLE_SEEDS: Dict[str, Dict[str, Any]] = {
    "tenant_owner": {
        "description": "Full tenant ownership",
        "permissions": ["*"]
    },
    "site_admin": {
        "description": "Manage sites and stores for assigned sites",
        "permissions": [
            "tenants.view",
            "sites.*",
            "stores.*",
            "users.view",
            "users.roles.view"
        ]
    },
    "store_admin": {
        "description": "Manage a store and its assortment",
        "permissions": [
            "stores.*",
            "orders.view",
            "orders.update",
            "orders.cancel",
            "orders.export"
        ]
    },
    "department_manager": {
        "description": "Manage org/department and scoped budgets",
        "permissions": [
            "org_units.*",
            "users.view",
            "users.roles.view",
            "cost_centres.assign_users",
            "budgets.manage.subordinates",
            "budgets.view"
        ]
    },
    "cost_centre_manager": {
        "description": "Manage a cost centre and budgets for it",
        "permissions": [
            "cost_centres.*",
            "budgets.manage.subordinates",
            "budgets.view"
        ]
    },
    "approver_level_1": {
        "description": "Approve requests within L1 limits",
        "permissions": [
            "approvals.requests.view",
            "approvals.requests.respond",
            "approvals.delegations.manage",
            "budgets.instant.approve"
        ]
    },
    "approver_level_2": {
        "description": "Approve requests within L2 limits",
        "permissions": [
            "approvals.requests.view",
            "approvals.requests.respond",
            "approvals.delegations.manage",
            "budgets.instant.approve",
            "approvals.chains.manage",
            "approvals.steps.manage"
        ]
    },
    "budget_requester": {
        "description": "Request budgets and place orders",
        "permissions": [
            "budgets.instant.request",
            "approvals.requests.create",
            "orders.create"
        ]
    },
    "bootstrap_admin": {
        "description": "Bootstrap platform admin (internal)",
        "permissions": ["*"]
    }
}

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


def _resolve_permission_codes(patterns: List[str], available_codes: List[str]) -> List[str]:
    """Expand wildcard/prefix patterns to concrete permission codes."""
    resolved: set[str] = set()
    for pattern in patterns:
        normalized = pattern.replace("._", ".").strip()
        if normalized in {"*", "all"}:
            resolved.update(available_codes)
            continue
        if normalized.endswith(".*") or normalized.endswith("."):
            prefix = normalized.rstrip("*").rstrip(".")
            resolved.update([code for code in available_codes if code.startswith(prefix)])
            continue
        if normalized in available_codes:
            resolved.add(normalized)
        else:
            logger.debug(f"Permission pattern did not match any code: {normalized}")
    return sorted(resolved)


def seed_permissions_and_roles():
    """Idempotently seed permission catalog, default roles, and role-permission mappings."""
    try:
        with SessionLocal() as db:
            # Seed permissions
            existing_codes = {code for (code,) in db.query(Permission.code).all()}
            new_permissions = [
                Permission(permission_id=uuid.uuid4(), code=code, description=description)
                for code, description in PERMISSION_CATALOG
                if code not in existing_codes
            ]
            if new_permissions:
                db.add_all(new_permissions)
                db.commit()
                logger.info(f"✅ Seeded {len(new_permissions)} permissions")

            # Refresh permission map
            perm_rows = db.query(Permission.permission_id, Permission.code).all()
            code_to_id = {code: pid for pid, code in perm_rows}
            available_codes = list(code_to_id.keys())

            # Seed roles
            existing_roles = {code: rid for code, rid in db.query(Role.code, Role.role_id).all()}
            for role_code, meta in ROLE_SEEDS.items():
                if role_code not in existing_roles:
                    role = Role(
                        role_id=uuid.uuid4(),
                        code=role_code,
                        description=meta.get("description")
                    )
                    db.add(role)
                    db.flush()
                    existing_roles[role_code] = role.role_id
            db.commit()

            # Map permissions to roles
            mapped = 0
            for role_code, meta in ROLE_SEEDS.items():
                role_id = existing_roles.get(role_code)
                if not role_id:
                    continue
                desired_codes = _resolve_permission_codes(meta.get("permissions", []), available_codes)
                for perm_code in desired_codes:
                    perm_id = code_to_id.get(perm_code)
                    if not perm_id:
                        continue
                    exists = db.query(RolePermission).filter(
                        RolePermission.role_id == role_id,
                        RolePermission.permission_id == perm_id
                    ).first()
                    if not exists:
                        db.add(RolePermission(id=uuid.uuid4(), role_id=role_id, permission_id=perm_id))
                        mapped += 1
            if mapped:
                db.commit()
                logger.info(f"✅ Seeded role-permission mappings: {mapped}")
    except Exception as exc:
        logger.warning(f"⚠️  Permission/role seeding skipped: {exc}")


def seed_default_permissions():
    """Backward compatible wrapper."""
    seed_permissions_and_roles()


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
                    tenant_type="customer",
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
                    password=password_hash,
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

            # Ensure bootstrap admin has tenant_owner role
            tenant_owner_role = db.query(Role).filter(func.lower(Role.code) == "tenant_owner").first()
            if tenant_owner_role:
                has_role = db.query(UserRole).filter(
                    UserRole.user_id == user.user_id,
                    UserRole.role_id == tenant_owner_role.role_id
                ).first()
                if not has_role:
                    db.add(UserRole(
                        id=uuid.uuid4(),
                        tenant_id=tenant.tenant_id,
                        user_id=user.user_id,
                        role_id=tenant_owner_role.role_id
                    ))
                    db.commit()
                    logger.info("✅ Bootstrap admin granted tenant_owner role")

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
        
        # Bootstrap admin gets wildcard permissions, regular users get their role-based permissions
        if user.api_key == SETTINGS.BOOTSTRAP_ADMIN_API_KEY:
            ctx = build_user_context(db, user, claims={"permissions": ["*"]})
        else:
            ctx = build_user_context(db, user, claims=None)
        
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

async def decode_jwt_with_settings(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> Dict[str, Any]:
    """
    Extract token from Authorization header (accepts "Bearer <token>" or raw token),
    decode via existing decode_jwt_token(), and enforce JWT_EXPIRY_MINUTES (default 60).
    Raises HTTPException on any failure so it can be used directly as a FastAPI dependency.
    """
    jwt_secret = SETTINGS.JWT_SECRET
    jwt_algorithm = SETTINGS.JWT_ALGORITHM
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")

    # accept "Bearer <token>" or raw token
    raw = authorization
    if isinstance(raw, str) and raw.lower().startswith("bearer "):
        raw = raw.split(" ", 1)[1]

    if not isinstance(raw, str) or not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization token")

    # try:
    claims = jwt.decode(
        raw,
        jwt_secret,
        algorithms=[jwt_algorithm],
        options={"verify_aud": False}  # adjust if you want audience/issuer checks
    )
    # except HTTPException:
    #     raise
    # except Exception as exc:
    #     logger.debug(f"JWT decode error: {exc}")
    #     raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT verification failed")

    jwt_exp_minutes = int(getattr(SETTINGS, "JWT_EXPIRY_MINUTES", 60))
    now_ts = int(datetime.now(timezone.utc).timestamp())

    iat = claims.get("iat")
    if iat is not None:
        try:
            iat_ts = int(iat)
        except Exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid iat claim")
        max_age_seconds = jwt_exp_minutes * 60
        if now_ts - iat_ts > max_age_seconds:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT expired (age exceeds configured expiry)")
    elif "exp" in claims:
        try:
            exp_ts = int(claims["exp"])
        except Exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid exp claim")
        if now_ts > exp_ts:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT expired")
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT missing iat/exp claims")

    return claims


# python
def check_user_authorization(permission: str):
    """
    Dependency factory usable as Depends(check_user_authorization("some.permission"))
    """
    def dependency(claims: Dict[str, Any] = Depends(decode_jwt_with_settings)):
        try:
            # prefer explicit permissions in token
            claim_perms = claims.get("permissions")
            logger.debug(f"token permissions: {claim_perms}")
            if isinstance(claim_perms, list):
                if "*" in claim_perms or permission in claim_perms:
                    return True

            # extract role codes from token (accept string, list, or iterable)
            roles = claims.get("roles") or claims.get("role") or []
            if isinstance(roles, str):
                roles = [roles]
            elif not isinstance(roles, list):
                try:
                    roles = list(roles)
                except Exception:
                    roles = []

            if not roles:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No roles available in token")

            # DB check: does any role have the requested permission?
            try:
                with SessionLocal() as db:
                    match_count = db.query(RolePermission) \
                        .join(Role, RolePermission.role_id == Role.role_id) \
                        .join(Permission, RolePermission.permission_id == Permission.permission_id) \
                        .filter(Role.code.in_(roles), Permission.code == permission) \
                        .count()
            except Exception as exc:
                logger.error(f"Authorization DB check failed: {exc}")
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Authorization lookup failed")

            if match_count and match_count > 0:
                return claims

            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Authorization error: {exc}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization token")

    return dependency
