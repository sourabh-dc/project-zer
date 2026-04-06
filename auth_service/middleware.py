"""
auth_service.middleware
-----------------------
FastAPI dependencies for authentication and authorization.

Uses OUR OWN JWTs (issued after Azure AD authentication).
Same middleware works for both azure_ad and local auth modes.
"""
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth_service.token import validate_token
from auth_service.schemas import UserContext

logger = logging.getLogger("auth_service.middleware")

_bearer_scheme = HTTPBearer(auto_error=False)


async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> UserContext:
    """Validate the Bearer token and return user context.
    Raises 401 if the token is missing or invalid.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authentication token")

    try:
        user = await validate_token(credentials.credentials)
    except Exception as exc:
        logger.warning(f"Token validation failed: {exc}")
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    if not user.user_id:
        raise HTTPException(status_code=401, detail="Token missing user identity")

    return user


async def require_tenant(
    user: UserContext = Depends(require_auth),
) -> UserContext:
    """Ensure the authenticated user belongs to a tenant (org_id present)."""
    if not user.org_id:
        raise HTTPException(
            status_code=403,
            detail="No organization context — user must belong to a tenant",
        )
    return user


def require_role(*required_roles: str):
    """Create a dependency that checks for specific org-level roles."""
    async def _check(user: UserContext = Depends(require_tenant)) -> UserContext:
        if not any(role in user.roles for role in required_roles):
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient role — requires one of: {list(required_roles)}",
            )
        return user
    return _check


def require_permission(*required_permissions: str):
    """Create a dependency that checks for specific permissions."""
    async def _check(user: UserContext = Depends(require_tenant)) -> UserContext:
        if not any(perm in user.permissions for perm in required_permissions):
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions — requires one of: {list(required_permissions)}",
            )
        return user
    return _check
