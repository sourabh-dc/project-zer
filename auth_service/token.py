"""
auth_service.token
------------------
JWT issuance and validation.

Architecture:
  - Azure AD handles AUTHENTICATION (passwords, MFA, email verification)
  - We issue OUR OWN JWTs for API access after Azure AD validates credentials
  - Our JWTs contain: user_id, email, org_id, tenant_id, roles
  - All services validate our JWT (not Azure AD tokens directly)

This keeps our token format consistent across auth modes (azure_ad / local)
and gives us full control over claims without depending on Azure AD token format.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import jwt as pyjwt

from auth_service.config import JWT_SECRET, JWT_ISSUER, JWT_AUDIENCE, JWT_EXPIRY_SECONDS
from auth_service.schemas import UserContext

logger = logging.getLogger("auth_service.token")


def issue_token(
    user_id: str,
    email: str,
    org_id: str,
    *,
    tenant_id: Optional[str] = None,
    roles: Optional[List[str]] = None,
    permissions: Optional[List[str]] = None,
    expires_in: Optional[int] = None,
) -> str:
    """Issue a platform JWT after authentication succeeds."""
    now = datetime.now(timezone.utc)
    exp = expires_in or JWT_EXPIRY_SECONDS
    payload = {
        "sub": user_id,
        "email": email,
        "org_id": org_id,
        "tenant_id": tenant_id or org_id,
        "roles": roles or [],
        "permissions": permissions or [],
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=exp)).timestamp()),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")


def validate_token_sync(token: str) -> UserContext:
    """Validate a platform JWT and return a UserContext."""
    payload = pyjwt.decode(
        token,
        JWT_SECRET,
        algorithms=["HS256"],
        audience=JWT_AUDIENCE,
        issuer=JWT_ISSUER,
    )
    return UserContext(
        user_id=payload.get("sub", ""),
        email=payload.get("email", ""),
        org_id=payload.get("org_id"),
        tenant_id=payload.get("tenant_id"),
        roles=payload.get("roles", []),
        permissions=payload.get("permissions", []),
    )


async def validate_token(token: str) -> UserContext:
    """Async wrapper for token validation."""
    return validate_token_sync(token)
