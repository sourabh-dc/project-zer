"""
Policy Service — JWT Authentication

Reuses the same JWT secret/algorithm as provisioning_service.
Protects policy CRUD endpoints — only tenant_admin or users with
'policy.manage' permission can modify policies.
"""
from datetime import datetime, timezone
from typing import Dict, Any

import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from starlette import status

from policy_service.core.config import SETTINGS
from policy_service.utils.logger import logger

bearer = HTTPBearer(auto_error=True)


async def decode_jwt_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(
            token,
            SETTINGS.JWT_SECRET,
            algorithms=[SETTINGS.JWT_ALGORITHM],
            options={"verify_aud": False, "verify_iss": False},
        )
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


async def verify_jwt(creds: HTTPAuthorizationCredentials = Security(bearer)) -> Dict[str, Any]:
    """Validate JWT and return claims."""
    if not creds or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")

    claims = await decode_jwt_token(creds.credentials)

    now_ts = int(datetime.now(timezone.utc).timestamp())
    iat = claims.get("iat")
    exp = claims.get("exp")

    if iat is not None:
        jwt_exp_minutes = int(getattr(SETTINGS, "JWT_EXPIRY_MINUTES", 60))
        if now_ts - int(iat) > jwt_exp_minutes * 60:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT expired")
    elif exp is not None:
        if now_ts > int(exp):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT expired")

    claims["user_id"] = claims.get("sub")
    return claims


def require_policy_admin():
    """Dependency: only users with '*' permission, 'tenant_admin' role, or 'policy.manage' permission."""
    async def dependency(claims: Dict[str, Any] = Security(verify_jwt)) -> Dict[str, Any]:
        perms = claims.get("permissions", [])
        if isinstance(perms, list) and ("*" in perms or "policy.manage" in perms):
            return claims

        roles = claims.get("roles") or claims.get("role") or []
        if isinstance(roles, str):
            roles = [roles]
        if "tenant_admin" in roles:
            return claims

        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Policy management requires tenant_admin or policy.manage permission")
    return dependency
