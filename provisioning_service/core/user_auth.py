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
from sqlalchemy import func
from starlette import status

from provisioning_service.Models import RolePermission, Permission, Role, User
from provisioning_service.core.config import SETTINGS
from provisioning_service.core.db_config import SessionLocal
from provisioning_service.utils.logger import logger

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

async def _try_azure_token(raw: str) -> Optional[Dict[str, Any]]:
    """
    Attempt to validate the token as an Azure AD B2C / Entra ID token.

    If Azure AD is not configured or the token is not an Azure token,
    returns None so the caller can fall back to local JWT validation.
    """
    try:
        from provisioning_service.core.azure_auth import (
            validate_azure_token,
            is_azure_auth_configured,
        )
    except ImportError:
        return None

    if not is_azure_auth_configured():
        return None

    # Peek at the token header to check if it's RS256 (Azure uses RSA)
    try:
        header = jwt.get_unverified_header(raw)
        if header.get("alg") not in ("RS256", "RS384", "RS512"):
            return None
    except Exception:
        return None

    try:
        azure_claims = await validate_azure_token(raw)

        # Map Azure identity to internal user for a unified claims dict
        email = azure_claims.email
        if not email:
            return None

        with SessionLocal() as db:
            user = db.query(User).filter(func.lower(User.email) == email.lower()).first()
            if not user:
                # No internal user mapped — cannot proceed with Azure auth alone.
                # Return basic claims so caller knows auth succeeded but user lookup
                # must happen at a higher level.
                return None

            # Build unified claims dict matching local JWT structure
            return {
                "sub": str(user.user_id),
                "email": user.email,
                "tenant_id": str(user.tenant_id),
                "roles": azure_claims.roles or [],
                "permissions": azure_claims.permissions or [],
                "auth_method": "azure_ad",
                "azure_oid": azure_claims.oid,
                "iat": azure_claims.iat,
                "exp": azure_claims.exp,
            }
    except HTTPException:
        # Azure validation explicitly failed (expired, bad audience, etc.)
        # Don't fall back to local JWT — re-raise so the user gets the real error.
        raise
    except Exception:
        # Non-Azure token or transient error — fall back to local JWT
        return None


async def decode_jwt_with_settings(creds: HTTPAuthorizationCredentials = Security(bearer)) -> Dict[str, Any]:
    """
    Uses HTTPBearer via Security so Swagger/Redoc shows the Authorize dialog.

    Validation order:
      1. If Azure AD is configured, attempt Azure token validation first.
      2. Fall back to local JWT validation (HS256 or configured algorithm).
    """
    if not creds or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")
    raw = creds.credentials  # raw token string (no "Bearer ")

    # Try Azure AD first
    azure_claims = await _try_azure_token(raw)
    if azure_claims is not None:
        return azure_claims

    # Fall back to local JWT
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
