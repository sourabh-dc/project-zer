# ==================================================================================
# AUTHENTICATION & AUTHORIZATION
# ==================================================================================
from datetime import datetime, timezone
from typing import Dict, Optional, List, Tuple, Any
import httpx
import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from starlette import status

from operations_service.Models import RolePermission, Permission, Role, User, Tenant, UserCostCentre, CostCentre, CostCenterBudget, UserRole
from operations_service.core.config import SETTINGS
from operations_service.core.db_config import SessionLocal
from operations_service.utils.logger import logger

DEFAULT_PERMISSIONS: List[Tuple[str, str]] = [
    ("tenants.create", "Create and manage tenants"),
    ("sites.manage", "Manage sites for a tenant"),
    ("stores.manage", "Manage stores for a site"),
    ("users.manage", "Manage tenant users"),
    ("users.password.reset", "Reset user passwords"),
    ("roles.assign", "Assign and remove roles for users"),
    ("vendors.manage", "Manage vendors for a tenant"),
    ("cost_centres.manage", "Manage cost centres for a tenant"),
    ("org_units.manage", "Manage organizational units"),
    ("org_units.assign", "Assign users to organizational units"),
    ("catalog.categories.manage", "Manage catalog categories"),
    ("catalog.products.manage", "Create and update catalog products"),
    ("catalog.products.view", "View catalog products"),
    ("catalog.variants.manage", "Manage catalog variants"),
    ("subscriptions.plans.manage", "Manage subscription plans"),
    ("subscriptions.plans.view", "View subscription plans"),
    ("subscriptions.features.manage", "Manage subscription features"),
    ("subscriptions.features.view", "View subscription features"),
    ("subscriptions.tenant.manage", "Manage tenant subscriptions"),
    ("subscriptions.tenant.view", "View tenant subscription status"),
    ("entitlements.check", "Check entitlements for tenants"),
    ("entitlements.usage.record", "Record entitlement usage"),
    ("entitlements.usage.view", "View entitlement usage summary"),
    ("entitlements.usage.manage", "Reset entitlement usage records"),
    ("approvals.chains.manage", "Manage approval chains and steps"),
    ("approvals.requests.create", "Create approval requests"),
    ("approvals.requests.view", "View approval requests"),
    ("approvals.requests.respond", "Respond to approval requests"),
    ("budget.approve", "Approve budget requests"),
    ("costcentre.manage", "Manage cost centre budgets"),
    ("budgets.manage", "Manage budgets - allocate and configure approver limits"),
    ("budgets.manage.subordinates", "Allocate budget to direct reports only"),
    ("budgets.instant.request", "Request instant budget top-ups"),
    ("budgets.instant.approve", "Approve instant budget requests"),
    ("admin.permissions.manage", "Manage permission catalog"),
    ("admin.roles.manage", "Manage roles and assignments"),
    ("admin.scopes.manage", "Manage role scopes"),
]

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

bearer = HTTPBearer(auto_error=True)

async def decode_jwt_with_settings(creds: HTTPAuthorizationCredentials = Security(bearer)) -> Dict[str, Any]:
    """
    Uses HTTPBearer via Security so Swagger/Redoc shows the Authorize dialog.
    Decodes the raw token with decode_jwt_token() and enforces iat/exp checks.
    """
    if not creds or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")
    raw = creds.credentials  # raw token string (no "Bearer ")
    claims = await decode_jwt_token(raw)

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

def check_user_authorization(permission: str):
    async def dependency(claims: Dict[str, Any] = Security(decode_jwt_with_settings)):
        try:
            claim_perms = claims.get("permissions")
            if isinstance(claim_perms, list):
                if "*" in claim_perms or permission in claim_perms:
                    claims['user_id'] = claims.pop('sub')
                    return claims

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

            try:
                with SessionLocal() as db:
                    match_count = db.query(RolePermission) \
                        .join(Role, RolePermission.role_code == Role.code) \
                        .join(Permission, RolePermission.permission_code == Permission.code) \
                        .filter(Role.code.in_(roles), Permission.code == permission) \
                        .count()
            except Exception as exc:
                logger.error(f"Authorization DB check failed: {exc}")
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Authorization lookup failed")

            if match_count and match_count > 0:
                claims['user_id'] = claims.pop('sub')
                return claims

            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Authorization error: {exc}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization token")
    return dependency

async def get_user_context(user_id: str) -> Dict[str, Any]:
    """
    Retrieves comprehensive user context including:
    - User details (name, email, phone, position, etc.)
    - Tenant information
    - Roles assigned to the user
    - Budget information (allocated, spent, available, max limit)
    - Cost centre details

    Args:
        user_id: The UUID of the user

    Returns:
        Dict containing all user context information

    Raises:
        HTTPException: If user not found or database error
    """
    try:
        with SessionLocal() as db:
            # Get user with tenant info
            user = db.query(User).filter(User.user_id == user_id).first()

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User with id {user_id} not found"
                )

            # Get tenant info
            tenant = db.query(Tenant).filter(Tenant.tenant_id == user.tenant_id).first()

            # Get user roles
            user_roles = db.query(Role.code, Role.description).join(
                UserRole, UserRole.role_id == Role.role_id
            ).filter(UserRole.user_id == user_id).all()

            roles_list = [{"code": r.code, "description": r.description} for r in user_roles]

            # Get user cost centre assignments with budget details
            cost_centre_assignments = db.query(
                UserCostCentre,
                CostCentre,
                CostCenterBudget
            ).join(
                CostCentre, UserCostCentre.cost_centre_id == CostCentre.cost_centre_id
            ).join(
                CostCenterBudget, UserCostCentre.cc_budget_id == CostCenterBudget.budget_id
            ).filter(
                UserCostCentre.user_id == user_id
            ).all()

            # Calculate totals across all cost centres
            total_allocated = 0
            total_spent = 0
            total_available = 0
            total_max_budget = 0

            cost_centres_detail = []
            for ucc, cc, ccb in cost_centre_assignments:
                total_allocated += ucc.allocated_minor or 0
                total_spent += ucc.spent_minor or 0
                total_available += ucc.available_minor or 0
                total_max_budget += ucc.max_budget_minor or 0

                cost_centres_detail.append({
                    "cost_centre_id": str(cc.cost_centre_id),
                    "cost_centre_code": cc.code,
                    "cost_centre_name": cc.name,
                    "description": cc.description,
                    "is_active": cc.is_active,
                    "budget": {
                        "budget_id": str(ccb.budget_id),
                        "fiscal_year": ccb.fiscal_year,
                        "period_type": ccb.period_type,
                        "period_number": ccb.period_number,
                        "period_start": ccb.period_start.isoformat() if ccb.period_start else None,
                        "period_end": ccb.period_end.isoformat() if ccb.period_end else None,
                        "budget_amount_minor": ccb.budget_amount_minor,
                        "total_spent_minor": ccb.total_spent_minor,
                        "status": ccb.status
                    },
                    "user_allocation": {
                        "max_budget_minor": ucc.max_budget_minor,
                        "allocated_minor": ucc.allocated_minor,
                        "spent_minor": ucc.spent_minor,
                        "available_minor": ucc.available_minor,
                        "recurring_amount_minor": ucc.recurring_amount_minor,
                        "recurring_period": ucc.recurring_period,
                        "next_recurring_at": ucc.next_recurring_at.isoformat() if ucc.next_recurring_at else None,
                        "is_blocked": ucc.is_blocked,
                        "blocked_reason": ucc.blocked_reason
                    }
                })

            # Build user context response
            user_context = {
                "user": {
                    "user_id": str(user.user_id),
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "display_name": user.display_name,
                    "phone": user.phone,
                    "position": user.position,
                    "profile_image": user.profile_image,
                    "is_active": user.is_active,
                    "is_sso_enabled": user.is_sso_enabled,
                    "all_locations": user.all_locations,
                    "max_order_limit_minor": user.max_order_limit_minor,
                    "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
                    "created_at": user.created_at.isoformat() if user.created_at else None
                },
                "tenant": {
                    "tenant_id": str(tenant.tenant_id) if tenant else None,
                    "tenant_name": tenant.tenant_name if tenant else None,
                    "tenant_type": tenant.tenant_type if tenant else None,
                    "email": tenant.email if tenant else None,
                    "active": tenant.active if tenant else None,
                    "default_currency": tenant.default_currency if tenant else None,
                    "timezone": tenant.timezone if tenant else None,
                    "locale": tenant.locale if tenant else None,
                    "industry": tenant.industry if tenant else None
                } if tenant else None,
                "roles": roles_list,
                "budget_summary": {
                    "total_max_budget_minor": total_max_budget,
                    "total_allocated_minor": total_allocated,
                    "total_spent_minor": total_spent,
                    "total_available_minor": total_available,
                    "utilization_percent": round((total_spent / total_allocated * 100), 2) if total_allocated > 0 else 0,
                    "cost_centres_count": len(cost_centres_detail)
                },
                "cost_centres": cost_centres_detail
            }

            return user_context

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error fetching user context: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve user context: {str(exc)}"
        )
